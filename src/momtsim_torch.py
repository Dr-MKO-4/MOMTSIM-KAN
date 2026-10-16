"""
momtsim_torch.py  Moteur MoMTSim vectorisé PyTorch.
Boucle externe : steps (séquentiel, dépendance de solde inter-steps).
Boucle interne : créneaux du step, vectorisés sur les seuls clients actifs du
créneau (les autres clients ne coûtent rien, ce qui compte en régime clairsemé :
~3 000 clients actifs par step sur 500 000).

Représentation : tous les acteurs (clients, marchands, banques, mules) sont
indexés dans un unique tenseur de solde `balance` de taille n_actors, pour
permettre des opérations scatter/gather uniformes.

Module d'injection : il partage le même tenseur, lu et écrit à travers un miroir
NumPy (`host_balance()`). Sur CPU le miroir EST le tenseur (vue sans copie) ; sur
GPU il est synchronisé une fois par step au lieu d'une synchronisation par
transaction frauduleuse.

Journal : écrit par colonnes (blocs NumPy) au lieu de 14 listes Python. En
régime de calibration (`keep_log=False`), seuls des compteurs par step et par
scénario sont tenus.
"""

import os
import numpy as np
import torch
import pandas as pd
import json


def _select_device() -> torch.device:
    """cuda > mps > cpu, avec override manuel via MOMTSIM_DEVICE (cpu/cuda/mps)."""
    forced = os.environ.get("MOMTSIM_DEVICE")
    if forced:
        return torch.device(forced)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


DEVICE = _select_device()

SCENARIO_NAMES = ["ATO", "REFUND", "FAKE_CRED", "SPLIT_DEP", "SMURFING"]

# Colonnes du journal interne (blocs NumPy) et leur type
_LOG_DTYPES = {
    "step": np.int32, "time_s": np.float32, "action": np.int16, "amount": np.float32,
    "orig": np.int32, "dest": np.int32,
    "old_o": np.float32, "new_o": np.float32, "old_d": np.float32, "new_d": np.float32,
    "success": np.bool_, "fraud": np.bool_, "flag": np.bool_, "scen": np.int16,
}
_LOG_KEYS = list(_LOG_DTYPES)


class TorchParameters:
    """Charge les 6 CSV + config fraude JSON, et pré-calcule des tenseurs
    par client (un profil moyen/std par action, tiré une fois à l'initialisation
    -- équivalent du tirage de profil aléatoire par client de la version NumPy)."""

    ACTIONS = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER", "DEPOSIT"]
    IN_ACTIONS = {"CASH_IN", "DEPOSIT"}   # actions qui font entrer de l'argent (spring model)
    OUT_ACTIONS = {"CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"}
    # Population de référence à laquelle les volumes horaires sont ramenés (§3.1.1)
    N_CLIENTS_REF = 500_000

    def __init__(self, param_dir: str, fraud_config_path: str, n_clients: int,
                 seed: int = 1000, volume_scale: float = 1.0):
        self.rng = np.random.default_rng(seed)
        self.n_clients = n_clients
        # Facteur appliqué au volume de transactions légitimes par step (1.0 = profil
        # calibré). Permet un régime clairsemé (peu de transactions par client) avec
        # une population de taille raisonnable, sans toucher aux calibrations offline.
        self.volume_scale = float(volume_scale)

        self.client_profiles_df = pd.read_csv(f"{param_dir}/clientsProfiles.csv")
        self.agg_df = pd.read_csv(f"{param_dir}/aggregatedTransactions.csv")
        self.balances_df = pd.read_csv(f"{param_dir}/initialBalancesDistribution.csv")
        self.agent_float_df = pd.read_csv(f"{param_dir}/agentFloatDistribution.csv")
        self.overdraft_df = pd.read_csv(f"{param_dir}/overdraftLimits.csv")
        self.max_occ_df = pd.read_csv(f"{param_dir}/maxOccurrencesPerClient.csv")

        with open(fraud_config_path, "r", encoding="utf-8") as f:
            self.fraud_config = json.load(f)

        self._build_client_tensors()
        self._build_step_target_tensors()

    #
    def _sample_profile_pool(self, action: str):
        """Tirage pondéré (n_clients tirages indépendants) parmi les profils
        disponibles pour une action, équivalent RandomCollection."""
        sub = self.client_profiles_df[self.client_profiles_df["action"] == action]
        if sub.empty:
            return (np.zeros(self.n_clients), np.zeros(self.n_clients),
                    np.zeros(self.n_clients, dtype=bool))
        weights = sub["weight"].values / sub["weight"].values.sum()
        idx = self.rng.choice(len(sub), size=self.n_clients, p=weights)
        means = sub["mean_amount"].values[idx]
        stds = sub["std_amount"].values[idx]
        return means, stds, np.ones(self.n_clients, dtype=bool)

    def _build_client_tensors(self):
        n = self.n_clients
        mean_mat = np.zeros((n, len(self.ACTIONS)))
        std_mat = np.zeros((n, len(self.ACTIONS)))
        avail_mat = np.zeros((n, len(self.ACTIONS)), dtype=bool)

        for j, action in enumerate(self.ACTIONS):
            means, stds, avail = self._sample_profile_pool(action)
            mean_mat[:, j] = means
            std_mat[:, j] = stds
            avail_mat[:, j] = avail

        self.mean_amount_tensor = torch.tensor(mean_mat, dtype=torch.float32, device=DEVICE)
        self.std_amount_tensor = torch.tensor(std_mat, dtype=torch.float32, device=DEVICE)
        self.action_available = torch.tensor(avail_mat, dtype=torch.bool, device=DEVICE)
        # Copies NumPy lues par le module d'injection (accès scalaires sans synchronisation)
        self.mean_amount_np = mean_mat.astype(np.float32)
        self.std_amount_np = std_mat.astype(np.float32)

        # solde initial par tranche empirique
        lo = self.balances_df["range_min"].values
        hi = self.balances_df["range_max"].values
        props = self.balances_df["proportion"].values / self.balances_df["proportion"].values.sum()
        bin_idx = self.rng.choice(len(self.balances_df), size=n, p=props)
        init_balance = self.rng.uniform(lo[bin_idx], hi[bin_idx])
        self.initial_balance = torch.tensor(init_balance, dtype=torch.float32, device=DEVICE)

        # Mobile Money CEMAC : pas de découvert  le solde ne peut pas être négatif.
        # On force overdraft_limit >= 0 quelle que soit la valeur dans le CSV.
        mean_global = mean_mat.mean(axis=1)
        self.mean_amount_client_np = mean_global
        overdraft = np.maximum(0.0, self._overdraft_vec(mean_global))
        self.overdraft_limit = torch.tensor(overdraft, dtype=torch.float32, device=DEVICE)
        self.equilibrium = torch.clamp(torch.tensor(40 * mean_global, dtype=torch.float32,
                                                      device=DEVICE), min=1.0)

        # target_total_count par client (nb tx cible sur toute la sim, somme des profils)
        target_counts = np.zeros(n)
        for j, action in enumerate(self.ACTIONS):
            sub = self.client_profiles_df[self.client_profiles_df["action"] == action]
            if not sub.empty:
                target_counts += self.rng.integers(
                    sub["min_tx_per_month"].min(), sub["max_tx_per_month"].max() + 1, size=n)
        self.target_total_count = torch.tensor(target_counts, dtype=torch.float32, device=DEVICE)
        total = self.target_total_count.sum()
        self.client_weight = self.target_total_count / total if total > 0 else torch.zeros(n, device=DEVICE)

    def sample_agent_float(self, n: int, rng: "np.random.Generator | None" = None) -> np.ndarray:
        """Tire n valeurs de float initial pour les agents distributeurs/banques
        selon agentFloatDistribution.csv  §3.2.4 du mémoire, \citet{gsma2010agents,ifc2017liquidity}."""
        rng = self.rng if rng is None else rng
        lo = self.agent_float_df["range_min"].values
        hi = self.agent_float_df["range_max"].values
        props = self.agent_float_df["proportion"].values / self.agent_float_df["proportion"].values.sum()
        bin_idx = rng.choice(len(self.agent_float_df), size=n, p=props)
        return rng.uniform(lo[bin_idx], hi[bin_idx])

    def _overdraft_bounds(self):
        for _, row in self.overdraft_df.iterrows():
            lo = -np.inf if str(row["mean_amount_min"]) == "-inf" else float(row["mean_amount_min"])
            hi = np.inf if str(row["mean_amount_max"]) == "inf" else float(row["mean_amount_max"])
            yield lo, hi, float(row["overdraft_limit"])

    def _overdraft_for(self, mean_amount: float) -> float:
        for lo, hi, limit in self._overdraft_bounds():
            if lo <= mean_amount < hi:
                return limit
        return 0.0

    def _overdraft_vec(self, mean_amount: np.ndarray) -> np.ndarray:
        """Version vectorisée de _overdraft_for (première tranche qui contient le montant)."""
        out = np.zeros(len(mean_amount))
        assigned = np.zeros(len(mean_amount), dtype=bool)
        for lo, hi, limit in self._overdraft_bounds():
            m = ~assigned & (mean_amount >= lo) & (mean_amount < hi)
            out[m] = limit
            assigned |= m
        return out

    def _build_step_target_tensors(self):
        """stepTargetCount(step) : volume total de tx attendu par step, toutes
        actions confondues -- pilote la binomiale."""
        by_step = self.agg_df.groupby("step")["count"].sum()
        arr = np.zeros(720)
        for s, c in by_step.items():
            if 0 <= int(s) < 720:
                arr[int(s)] = c
        arr = np.round(arr * self.volume_scale)   # entiers : requis par la loi binomiale
        self.step_target_np = arr
        self.step_target_count = torch.tensor(arr, dtype=torch.float32, device=DEVICE)

        # profils horaires par action (avg, std) pour le mix avec le profil client
        step_avg = np.zeros((720, len(self.ACTIONS)))
        step_std = np.zeros((720, len(self.ACTIONS)))
        for j, action in enumerate(self.ACTIONS):
            sub = self.agg_df[self.agg_df["action"] == action]
            for _, row in sub.iterrows():
                s = int(row["step"])
                if 0 <= s < 720:
                    step_avg[s, j] = row["avg"]
                    step_std[s, j] = row["std"]
        self.step_avg = torch.tensor(step_avg, dtype=torch.float32, device=DEVICE)
        self.step_std = torch.tensor(step_std, dtype=torch.float32, device=DEVICE)

    def reference_counts_by_action(self) -> np.ndarray:
        """Volume horaire de référence par action (len(ACTIONS) x 720), mis à l'échelle
        de volume_scale : base de comparaison SSE de MoMTSim (Azamuke et al., 2024)."""
        ref = np.zeros((len(self.ACTIONS), 720))
        for j, action in enumerate(self.ACTIONS):
            sub = self.agg_df[self.agg_df["action"] == action]
            for s, c in zip(sub["step"].astype(int), sub["count"]):
                if 0 <= s < 720:
                    ref[j, s] += c
        return ref * self.volume_scale


class TorchMoMTSimEngine:
    """Moteur vectorisé : n_clients clients + n_merchants marchands + n_banks
    banques, tous indexés dans un même tenseur `balance`."""

    REBALANCE_EVERY_STEPS = 24   # cycle quotidien de réapprovisionnement du float
    HISTORY_SIZE = 100

    def __init__(self, params: TorchParameters, n_clients: int, n_merchants: int,
                 n_banks: int, n_mules: int = 60, max_slots_per_step: int = 6, seed: int = 1000,
                 keep_log: bool = True):
        self.params = params
        self.n_clients = n_clients
        self.n_merchants = n_merchants
        self.n_banks = n_banks
        self.n_mules = n_mules
        # layout des indices d'acteurs : [clients | merchants | banks | mules]
        self.CLIENT_OFFSET = 0
        self.MERCHANT_OFFSET = n_clients
        self.BANK_OFFSET = n_clients + n_merchants
        self.MULE_OFFSET = n_clients + n_merchants + n_banks
        self.n_actors = n_clients + n_merchants + n_banks + n_mules
        self.max_slots = max_slots_per_step
        # keep_log=False : aucune ligne n'est conservée, seuls les compteurs par step
        # sont tenus (calibration : seule la distribution de la fraude est utile).
        self.keep_log = bool(keep_log)
        self.gen = torch.Generator(device=DEVICE).manual_seed(seed)
        # La binomiale est tirée sur CPU (non implémentée partout sur GPU)
        self._gen_cpu = self.gen if DEVICE.type == "cpu" else torch.Generator().manual_seed(seed)
        self._w_cpu = params.client_weight.clamp(0, 1).float().cpu()
        # RNG NumPy propre au moteur (float des agents) : deux moteurs de même graine
        # partageant un même TorchParameters tirent les mêmes floats (réplications SPSA).
        self.np_rng = np.random.default_rng(seed)

        self.balance = torch.zeros(self.n_actors, dtype=torch.float32, device=DEVICE)
        self.balance[:n_clients] = params.initial_balance
        # Float initial des agents distributeurs et banques (§3.2.4  GSMA 2010 / IFC 2017).
        # Tiré depuis agentFloatDistribution.csv : petits agents 100k-500k FCFA (60 %),
        # agents moyens 500k-2M FCFA (30 %), grands agents/banques 2M-10M FCFA (10 %).
        n_agents = n_merchants + n_banks
        agent_float = params.sample_agent_float(n_agents, rng=self.np_rng)
        self.balance[self.MERCHANT_OFFSET:self.MULE_OFFSET] = torch.tensor(
            agent_float, dtype=torch.float32, device=DEVICE)
        # mules : soldes initiaux nuls (comptes créés pour la fraude)
        self.balance[self.MULE_OFFSET:self.MULE_OFFSET + n_mules] = 0.0

        # Règle CEMAC : solde abonnés ≥ 0. Agents : plancher -1e9 pour les opérations
        # légitimes (CASH_IN bilatéral  flux physique compensatoire documenté).
        _AGENT_FLOOR = -1e9
        self.overdraft_limit = torch.full((self.n_actors,), _AGENT_FLOOR,
                                           dtype=torch.float32, device=DEVICE)
        # Clients abonnés : solde ≥ 0 imposé
        self.overdraft_limit[:n_clients] = torch.clamp(params.overdraft_limit, min=0.0)
        self._floor_np = self.overdraft_limit.cpu().numpy().copy()

        # marchands "high risk" (90% comme dans le doc MoMTSim, réutilisé comme
        # registre de vulnérabilité par défaut pour Refund Fraud)
        self.merchant_high_risk = torch.rand(n_merchants, generator=self.gen, device=DEVICE) < 0.90
        self.merchant_refund_proba = torch.rand(n_merchants, generator=self.gen, device=DEVICE) * 0.65 + 0.30

        # Probabilités de base p_in0 / p_out0 du modèle à rappel (§3.1.1), fixées à 0,5
        self.p_in0 = 0.5
        self.p_out0 = 0.5

        # historique "stickiness" : buffer circulaire de 100 contacts par client
        # (int32 : 200 Mo au lieu de 400 Mo pour 500 000 clients)
        self.history_buf = torch.full((n_clients, self.HISTORY_SIZE), -1,
                                      dtype=torch.int32, device=DEVICE)
        self.history_ptr = torch.zeros(n_clients, dtype=torch.int64, device=DEVICE)
        self.history_len = torch.zeros(n_clients, dtype=torch.int64, device=DEVICE)

        # Remboursements LÉGITIMES : une fraction p des PAYMENT légitimes réussis est
        # remboursée par le marchand après un délai tiré dans la même loi que celle de
        # la Refund Fraud (le délai ne doit pas, à lui seul, distinguer les deux).
        # Sans eux, tout REFUND du journal serait frauduleux et le type de transaction
        # révélerait l'étiquette. Valeur par défaut : 10 % -- ordre de grandeur des
        # retours en magasin (10,02 % des ventes, NRF & Appriss Retail, 2023), à
        # ajuster lors de la calibration.
        fc = params.fraud_config
        self.legit_refund_p = float(fc.get("legit_refund", {}).get("p_refund", 0.10))
        self.refund_delay_min = int(fc.get("refund", {}).get("delay_min_hours", 1))
        self.refund_delay_max = int(fc.get("refund", {}).get("delay_max_hours", 48))
        # step d'échéance -> liste de blocs (marchands, clients, montants)
        self._pending_legit_refunds: dict = {}

        # Tables d'actions et de scénarios (codes entiers du journal)
        A = params.ACTIONS
        self.action_names = list(A) + ["REFUND"]
        self._action_code = {a: i for i, a in enumerate(self.action_names)}
        self.scenario_names = list(SCENARIO_NAMES)
        self._scenario_code = {s: i for i, s in enumerate(self.scenario_names)}
        self._is_in_action = torch.tensor([a in params.IN_ACTIONS for a in A],
                                          dtype=torch.bool, device=DEVICE)
        self._is_merchant_action = torch.tensor([a in ("CASH_IN", "PAYMENT") for a in A],
                                                dtype=torch.bool, device=DEVICE)
        self._pay_j = A.index("PAYMENT")

        # Miroir NumPy du tenseur de soldes pour les opérations scalaires
        self._on_cpu = self.balance.device.type == "cpu"
        self._host = self.balance.numpy() if self._on_cpu else None
        self._host_valid = self._on_cpu
        self._device_stale = False

        # Journal par colonnes + compteurs par step
        self._chunks: list = []
        self._rows: list = []
        self.n_logged = 0
        self.n_fraud_logged = 0
        self._cap = 0
        self._legit_model = np.zeros((len(self.action_names), 0), dtype=np.int64)
        self._legit_other = np.zeros(0, dtype=np.int64)
        self._fraud_steps = np.zeros((len(self.scenario_names), 0), dtype=np.int64)

    # ── miroir hôte du tenseur de soldes ─────────────────────────────────────
    def host_balance(self) -> np.ndarray:
        """Soldes sous forme de tableau NumPy modifiable. Sur CPU : vue du tenseur."""
        if not self._host_valid:
            self._host = self.balance.cpu().numpy()
            self._host_valid = True
        return self._host

    def _host_written(self):
        if not self._on_cpu:
            self._device_stale = True

    def _sync_device(self):
        if self._device_stale:
            self.balance.copy_(torch.from_numpy(self._host).to(DEVICE))
            self._device_stale = False

    def _device_written(self):
        if not self._on_cpu:
            self._host_valid = False

    # ── sauvegarde / reprise (torch.save / torch.load) ───────────────────────
    def __getstate__(self):
        """État complet pour une reprise exacte : les générateurs torch ne sont pas
        sérialisables tels quels, on en garde l'état ; la vue NumPy est recréée."""
        self._sync_device()
        st = self.__dict__.copy()
        st["_host"] = None
        st["_host_valid"] = False
        st["gen"] = self.gen.get_state()
        st["_gen_device"] = str(self.gen.device)
        st["_gen_cpu"] = None if self._gen_cpu is self.gen else self._gen_cpu.get_state()
        return st

    def __setstate__(self, st):
        gen_state, dev, cpu_state = st.pop("gen"), st.pop("_gen_device"), st.pop("_gen_cpu")
        self.__dict__.update(st)
        self.gen = torch.Generator(device=dev)
        self.gen.set_state(gen_state)
        if cpu_state is None:
            self._gen_cpu = self.gen
        else:
            self._gen_cpu = torch.Generator()
            self._gen_cpu.set_state(cpu_state)
        self._on_cpu = self.balance.device.type == "cpu"
        self._host = self.balance.numpy() if self._on_cpu else None
        self._host_valid = self._on_cpu
        self._device_stale = False

    # ── compteurs ────────────────────────────────────────────────────────────
    def _ensure_cap(self, step: int):
        if step < self._cap:
            return
        new_cap = max(step + 1, 2 * self._cap, 720)
        pad = new_cap - self._cap
        self._legit_model = np.pad(self._legit_model, ((0, 0), (0, pad)))
        self._legit_other = np.pad(self._legit_other, (0, pad))
        self._fraud_steps = np.pad(self._fraud_steps, ((0, 0), (0, pad)))
        self._cap = new_cap

    def _act_code(self, action: str) -> int:
        code = self._action_code.get(action)
        if code is None:
            code = len(self.action_names)
            self.action_names.append(action)
            self._action_code[action] = code
            self._legit_model = np.vstack([self._legit_model,
                                           np.zeros((1, self._cap), dtype=np.int64)])
        return code

    def _scen_code(self, scenario) -> int:
        if scenario is None:
            return -1
        code = self._scenario_code.get(scenario)
        if code is None:
            code = len(self.scenario_names)
            self.scenario_names.append(scenario)
            self._scenario_code[scenario] = code
            self._fraud_steps = np.vstack([self._fraud_steps,
                                           np.zeros((1, self._cap), dtype=np.int64)])
        return code

    def fraud_counts_by_step(self, n_steps: int | None = None) -> np.ndarray:
        """Transactions frauduleuses par scénario (ordre SCENARIO_NAMES) et par step."""
        n = self._cap if n_steps is None else n_steps
        self._ensure_cap(max(n - 1, 0))
        return self._fraud_steps[:len(SCENARIO_NAMES), :n].copy()

    def legit_counts_by_step(self, n_steps: int | None = None) -> np.ndarray:
        """Transactions légitimes (moteur + camouflage + remboursements) par step."""
        n = self._cap if n_steps is None else n_steps
        self._ensure_cap(max(n - 1, 0))
        return self._legit_model[:, :n].sum(axis=0) + self._legit_other[:n]

    def legit_model_counts_by_action(self, n_steps: int | None = None) -> np.ndarray:
        """Transactions légitimes du modèle comportemental seul, par action et par step
        (lignes : ACTIONS puis REFUND)."""
        n = self._cap if n_steps is None else n_steps
        self._ensure_cap(max(n - 1, 0))
        return self._legit_model[:, :n].copy()

    #
    def _draw_amounts(self, step: int, idx: torch.Tensor, action_idx: torch.Tensor) -> torch.Tensor:
        P = self.params
        _step_idx = step % P.step_avg.shape[0]
        mu = (P.mean_amount_tensor[idx, action_idx] + P.step_avg[_step_idx, action_idx]) / 2
        sigma = torch.sqrt(P.std_amount_tensor[idx, action_idx] ** 2
                           + P.step_std[_step_idx, action_idx] ** 2) / 2
        sigma = torch.clamp(sigma, min=1e-3)

        amounts = torch.normal(mu, sigma, generator=self.gen)
        # retirage vectorisé tant que négatif (borné à quelques essais)
        for _ in range(5):
            neg_mask = amounts <= 0
            if not neg_mask.any():
                break
            resample = torch.normal(mu, sigma, generator=self.gen)
            amounts = torch.where(neg_mask, resample, amounts)
        return torch.clamp(amounts, min=1.0)

    #
    def _run_slot(self, step: int, idx: torch.Tensor):
        """Traite un créneau pour les clients d'indices `idx` (tenseur long trié).

        Sémantique des flux bilatéraux (section 3.1 du mémoire) :
          IN  (CASH_IN, DEPOSIT) : l'agent/banque (dest) cède de la liquidité digitale
              au client (orig). Flux : dest → orig.
          OUT (CASH_OUT, DEBIT, PAYMENT, TRANSFER) : le client envoie. Flux : orig → dest.
              Condition : solde client ≥ amount (overdraft_limit = 0 au CEMAC).
          Les marchands/banques ont un floor = -1e9 (float agent).
        """
        k = idx.numel()
        if k == 0:
            return
        P = self.params
        bal = self.balance

        # Modèle à rappel (Azamuke et al., 2024) : F = (E - B) / E
        eq = P.equilibrium[idx]
        b_orig = bal[idx]
        spring = (eq - b_orig) / eq
        in_prob = torch.clamp(0.5 * (1 + spring + (self.p_in0 - self.p_out0)), 0.0, 1.0)

        # Choix d'action : actions IN pondérées par p_in, OUT par 1 - p_in
        w = P.action_available[idx].float()
        w = w * torch.where(self._is_in_action, in_prob.unsqueeze(1), (1.0 - in_prob).unsqueeze(1))
        action_idx = torch.multinomial(w + 1e-8, num_samples=1, generator=self.gen).squeeze(1)

        amounts = self._draw_amounts(step, idx, action_idx)

        # Contreparties : fidélité 90/10 à l'historique des 100 derniers contacts
        is_merchant = self._is_merchant_action[action_idx]
        hlen = self.history_len[idx]
        use_history = (torch.rand(k, generator=self.gen, device=DEVICE) < 0.90) & (hlen > 0)
        rand_slot = (torch.rand(k, generator=self.gen, device=DEVICE)
                     * hlen.clamp(min=1).float()).long().clamp_(max=self.HISTORY_SIZE - 1)
        hist_choice = self.history_buf[idx, rand_slot].long()
        rand_merchant = torch.randint(self.n_clients, self.n_clients + self.n_merchants,
                                      (k,), generator=self.gen, device=DEVICE)
        rand_client = torch.randint(0, self.n_clients, (k,), generator=self.gen, device=DEVICE)
        rand_new = torch.where(is_merchant, rand_merchant, rand_client)
        dest = torch.where(use_history & (hist_choice >= 0), hist_choice, rand_new)
        dest = torch.where(dest == idx, rand_new, dest)   # éviter l'auto-transaction

        # Solvabilité et flux
        is_in = self._is_in_action[action_idx]
        can_pay_out = (b_orig - amounts) >= self.overdraft_limit[idx]
        active_in = is_in
        active_out = ~is_in & can_pay_out
        active = active_in | active_out
        n_act = int(active.sum())
        if n_act == 0:
            return

        old_dest = bal[dest]
        signed = torch.where(active_in, amounts,
                             torch.where(active_out, -amounts, torch.zeros_like(amounts)))
        bal.index_add_(0, idx, signed)      # client : + (IN) / - (OUT)
        bal.index_add_(0, dest, -signed)    # contrepartie : - (IN, float agent) / + (OUT)
        self._device_written()

        # Mémorisation des nouveaux contacts (probabilité 0,9)
        dest32 = dest.to(torch.int32)
        already_known = (self.history_buf[idx] == dest32.unsqueeze(1)).any(dim=1)
        remember = active & ~already_known & (torch.rand(k, generator=self.gen, device=DEVICE) < 0.90)
        if remember.any():
            r_idx = idx[remember]
            ptrs = self.history_ptr[r_idx]
            self.history_buf[r_idx, ptrs] = dest32[remember]
            self.history_ptr[r_idx] = (ptrs + 1) % self.HISTORY_SIZE
            self.history_len[r_idx] = torch.clamp(self.history_len[r_idx] + 1, max=self.HISTORY_SIZE)

        # Journal / compteurs
        codes = action_idx[active].cpu().numpy().astype(np.int16)
        self._ensure_cap(step)
        self._legit_model[:len(P.ACTIONS), step] += np.bincount(codes, minlength=len(P.ACTIONS))
        self.n_logged += n_act
        if self.keep_log:
            self._flush_rows()
            self._chunks.append({
                "step": np.full(n_act, step, dtype=np.int32),
                "time_s": np.zeros(n_act, dtype=np.float32),
                "action": codes,
                "amount": amounts[active].cpu().numpy().astype(np.float32),
                "orig": idx[active].cpu().numpy().astype(np.int32),
                "dest": dest[active].cpu().numpy().astype(np.int32),
                "old_o": b_orig[active].cpu().numpy().astype(np.float32),
                "new_o": bal[idx][active].cpu().numpy().astype(np.float32),
                "old_d": old_dest[active].cpu().numpy().astype(np.float32),
                "new_d": bal[dest][active].cpu().numpy().astype(np.float32),
                "success": np.ones(n_act, dtype=np.bool_),
                "fraud": np.zeros(n_act, dtype=np.bool_),
                "flag": np.zeros(n_act, dtype=np.bool_),
                "scen": np.full(n_act, -1, dtype=np.int16),
            })

        # Planification des remboursements légitimes de PAYMENT réussis
        if self.legit_refund_p > 0:
            draw = torch.rand(k, generator=self.gen, device=DEVICE) < self.legit_refund_p
            refunded = active_out & (action_idx == self._pay_j) & draw
            if refunded.any():
                n_ref = int(refunded.sum())
                delays = torch.randint(self.refund_delay_min, self.refund_delay_max + 1,
                                       (n_ref,), generator=self.gen, device=DEVICE).cpu().numpy()
                m_arr = dest[refunded].cpu().numpy()
                c_arr = idx[refunded].cpu().numpy()
                a_arr = amounts[refunded].cpu().numpy().astype(np.float64)
                due = step + delays
                for d in np.unique(due):
                    sel = due == d
                    self._pending_legit_refunds.setdefault(int(d), []).append(
                        (m_arr[sel], c_arr[sel], a_arr[sel]))

    def _run_step_slot(self, step: int, slot_mask: torch.Tensor):
        """Compatibilité : créneau défini par un masque booléen sur les clients."""
        self._sync_device()
        self._run_slot(step, slot_mask.nonzero(as_tuple=True)[0])

    def _flush_legit_refunds(self, step: int):
        """Exécute les remboursements légitimes arrivés à échéance : REFUND émis par
        le marchand au bénéfice du client, même convention que la Refund Fraud."""
        due = [s for s in self._pending_legit_refunds if s <= step]
        for s in sorted(due):
            for m_arr, c_arr, a_arr in self._pending_legit_refunds.pop(s):
                for merchant, client, amount in zip(m_arr.tolist(), c_arr.tolist(), a_arr.tolist()):
                    old_m, new_m, old_c, new_c, success = self.transfer(merchant, client, amount)
                    self.log_transaction(step, "REFUND", amount, merchant, client, old_m, new_m,
                                         old_c, new_c, is_fraud=False, scenario=None,
                                         success=success)

    #
    def step_once(self, step: int):
        """Volume légitime d'un step : n_i(t) ~ B(N(t), w_i), borné par max_slots,
        puis un créneau vectorisé par rang de transaction.

        `step` est un indice absolu fourni par l'appelant : il peut croître
        indéfiniment (flux live), le rebouclage ne concerne que le profil
        step_target_count.
        """
        n_target = float(self.params.step_target_np[step % len(self.params.step_target_np)])
        if n_target <= 0:
            return
        counts = torch.binomial(torch.full_like(self._w_cpu, n_target), self._w_cpu,
                                generator=self._gen_cpu)
        counts = counts.clamp_(max=self.max_slots).to(DEVICE)
        active = (counts > 0).nonzero(as_tuple=True)[0]
        if active.numel() == 0:
            return
        self._sync_device()
        c_act = counts[active]
        for slot in range(self.max_slots):
            sel = c_act > slot
            if slot > 0:
                active, c_act = active[sel], c_act[sel]
            if active.numel() == 0:
                break
            self._run_slot(step, active)

    def simulate_step(self, step: int, injector: "TorchFraudInjector | None" = None):
        """Un step complet, identique dans tous les régimes : volume légitime,
        injection de la fraude, fin de step (remboursements, float des agents)."""
        self.step_once(step)
        if injector is not None:
            injector.inject(step)
        self.end_of_step(step)

    def run(self, n_steps: int = 720, verbose=True) -> pd.DataFrame:
        for step in range(n_steps):
            self.simulate_step(step)
            if verbose and step % 50 == 0:
                print(f"step {step}/{n_steps}  {self.n_logged} tx cumulées", flush=True)
        return self.to_dataframe()

    # ── journal ──────────────────────────────────────────────────────────────
    def _flush_rows(self):
        """Convertit les lignes scalaires accumulées en un bloc (ordre conservé)."""
        if not self._rows:
            return
        cols = list(zip(*self._rows))
        self._rows = []
        self._chunks.append({k: np.asarray(cols[i], dtype=_LOG_DTYPES[k])
                             for i, k in enumerate(_LOG_KEYS)})

    def _concat_log(self) -> dict:
        self._flush_rows()
        if not self._chunks:
            return {k: np.zeros(0, dtype=t) for k, t in _LOG_DTYPES.items()}
        return {k: np.concatenate([c[k] for c in self._chunks]) for k in _LOG_KEYS}

    def to_dataframe(self) -> pd.DataFrame:
        cat = self._concat_log()
        action_names = np.array(self.action_names, dtype=object)
        # index -1 (aucun scénario) -> dernier élément -> None
        scen_names = np.array(self.scenario_names + [None], dtype=object)
        return pd.DataFrame({
            "step":           cat["step"],
            "time_s":         cat["time_s"],
            "action":         action_names[cat["action"]],
            "amount":         cat["amount"],
            "nameOrig":       cat["orig"],
            "nameDest":       cat["dest"],
            "oldBalanceOrig": cat["old_o"],
            "newBalanceOrig": cat["new_o"],
            "oldBalanceDest": cat["old_d"],
            "newBalanceDest": cat["new_d"],
            "isSuccessful":   cat["success"],
            "isFraud":        cat["fraud"],
            "isFlaggedFraud": cat["flag"],
            "fraudScenario":  scen_names[cat["scen"]],
        })

    def flush_log(self) -> pd.DataFrame:
        """Retourne le DataFrame des transactions accumulées et vide le tampon."""
        df = self.to_dataframe()
        self._chunks = []
        return df

    # Accès de compatibilité (lents : reconstruisent le tampon courant)
    @property
    def log_step(self) -> list:
        return self._concat_log()["step"].tolist()

    @property
    def log_is_fraud(self) -> list:
        return self._concat_log()["fraud"].tolist()

    @property
    def log_scenario(self) -> list:
        names = self.scenario_names + [None]
        return [names[c] for c in self._concat_log()["scen"].tolist()]

    #
    def log_transaction(self, step: int, action: str, amount: float,
                         orig_idx: int, dest_idx: int, old_orig: float, new_orig: float,
                         old_dest: float, new_dest: float, is_fraud: bool = True,
                         is_flagged: bool = False, scenario: str = None,
                         success: bool = True, time_s: float = 0.0):
        """Point d'entrée unique utilisé par les fraudeurs pour journaliser
        une transaction générée hors du flux légitime standard.

        time_s : secondes dans le step courant (précision intra-step pour ATO
                 et Split Deposit  cf. scénarios 3.2.1 et 3.2.4 du mémoire).
        """
        act = self._act_code(action)
        sc = self._scen_code(scenario)
        self._ensure_cap(step)
        self.n_logged += 1
        if is_fraud:
            self.n_fraud_logged += 1
            if sc >= 0:
                self._fraud_steps[sc, step] += 1
        elif action == "REFUND":
            self._legit_model[act, step] += 1
        else:
            self._legit_other[step] += 1
        if self.keep_log:
            self._rows.append((step, time_s, act, amount, orig_idx, dest_idx, old_orig, new_orig,
                               old_dest, new_dest, success, is_fraud, is_flagged, sc))

    def end_of_step(self, step: int, params=None) -> None:
        """À appeler après chaque step (moteur + injection), dans TOUS les régimes
        d'exécution (calibration, génération des jeux, interface, flux live) pour
        que le float des agents suive le même cycle quotidien partout, et que les
        remboursements légitimes arrivés à échéance soient exécutés."""
        self._flush_legit_refunds(step)
        if step > 0 and step % self.REBALANCE_EVERY_STEPS == 0:
            self.rebalance_agents(params)

    def rebalance_agents(self, params=None) -> None:
        """Réapprovisionne le float e-money des agents/banques toutes les 24 steps
        (simulation du cycle de rebalancement quotidien documenté par GSMA 2010).
        Les clients et les mules ne sont pas affectés."""
        params = self.params if params is None else params
        n_agents = self.n_merchants + self.n_banks
        hb = self.host_balance()
        hb[self.MERCHANT_OFFSET:self.MULE_OFFSET] = params.sample_agent_float(n_agents, rng=self.np_rng)
        self._host_written()

    def transfer(self, orig_idx: int, dest_idx: int, amount: float) -> tuple:
        """Effectue un virement entre deux acteurs (indices globaux) sur le
        tenseur balance partagé, retourne (old_orig, new_orig, old_dest, new_dest, success)."""
        hb = self.host_balance()
        old_orig = float(hb[orig_idx])
        old_dest = float(hb[dest_idx])
        can_pay = (old_orig - amount) >= self._floor_np[orig_idx]
        if can_pay:
            hb[orig_idx] = old_orig - amount
            hb[dest_idx] = hb[dest_idx] + amount
            self._host_written()
        return old_orig, float(hb[orig_idx]), old_dest, float(hb[dest_idx]), bool(can_pay)


#
# FRAUDEURS  branchés directement sur TorchMoMTSimEngine.balance (tenseur partagé)
# Formules identiques à la section 3.2 du mémoire, adaptées à l'indexation
# tensorielle du moteur torch.
#

class TorchFraudInjector:
    DEFAULT_PROBAS = {"ato": 0.02, "refund": 0.02, "fake_credentials": 0.005,
                      "split_deposit": 0.03, "smurfing_freq_mult": 1.0}
    FAKE_CRED_POOL = 200

    def __init__(self, engine: TorchMoMTSimEngine, params: TorchParameters,
                 fraud_probas: dict = None, seed: int = 1000, volume_follow: bool = False):
        self.engine = engine
        self.params = params
        self.cfg = params.fraud_config
        self.gen = np.random.default_rng(seed)

        self.probas = dict(self.DEFAULT_PROBAS)
        if fraud_probas is not None:
            self.probas.update(fraud_probas)

        self.n_c, self.n_m, self.n_u = engine.n_clients, engine.n_merchants, engine.n_mules
        self.m_off, self.u_off = engine.MERCHANT_OFFSET, engine.MULE_OFFSET
        self.client_ids = np.arange(self.n_c)
        self.merchant_ids = np.arange(self.m_off, self.m_off + self.n_m)
        self.mule_ids = np.arange(self.u_off, self.u_off + self.n_u)

        self._mean_client = params.mean_amount_client_np
        self._payment_idx = params.ACTIONS.index("PAYMENT")
        self._pay_mu = params.mean_amount_np[:, self._payment_idx]
        self._pay_sd = params.std_amount_np[:, self._payment_idx]

        self._fake_cred_agents: dict = {}
        self._split_dep_agents = self.merchant_ids[engine.merchant_high_risk.cpu().numpy()]
        grid = self.cfg["split_deposit"]["tariff_grid"]
        self._tariff = [(float(t["threshold"]), float(t["commission"])) for t in grid]

        # Transactions différées (REFUND delay, mule→récepteur Smurfing) : step -> liste
        self._pending: dict = {}

        # Tracking par scénario  alimenté par chaque _run_* pour export_fraudster_summary()
        self._tracking: dict = {
            "ato":              [],   # {step, victim, n_mules, total_amount}
            "refund":           [],   # {step, fraudster, merchant, amount, delay_hours}
            "fake_credentials": [],   # {step_activation, cid, dormance_hours, amount}
            "split_deposit":    [],   # {step, agent, client, n_frags, total_amount}
            "smurfing":         [],   # {step, emitter, n_mules, receiver, total_x}
        }

        # Refund Fraud : un fraudeur persistant, liste ordonnée de marchands vulnérables,
        # compteur de cycles par marchand (non global)
        vuln_mask = engine.merchant_refund_proba.cpu().numpy() > self.cfg["refund"]["p_refund_threshold"]
        self._refund_vuln_list: list = [int(m) for m in self.merchant_ids[vuln_mask]]
        self._refund_fraudster: int = int(self.gen.integers(self.n_c))
        self._refund_merchant_idx: int = 0
        self._refund_cycle_count: int = 0

        # Smurfing : nombre de réseaux proportionnel aux mules disponibles
        # (2 réseaux par mule en moyenne pour assurer suffisamment de volume).
        # Chaque réseau compte k mules (k ~ U[n_mules_min, n_mules_max]) de deux natures :
        #   - mules CONSCIENTES : comptes mules dédiés (bloc MULE du moteur), entièrement
        #     pilotés par l'émetteur ; sans activité propre dans le moteur, elles reçoivent
        #     des transactions légitimes de couverture entre deux opérations (§3.2.5) ;
        #   - mules INCONSCIENTES : comptes clients légitimes existants, compromis
        #     (victimes d'hameçonnage), qui gardent leur activité légitime ordinaire.
        # La part de conscientes est pct_conscious / (pct_conscious + pct_unconscious).
        sm = self.cfg["smurfing"]
        p_c = float(sm.get("pct_conscious", 1.0))
        p_u = float(sm.get("pct_unconscious", 0.0))
        share_conscious = p_c / (p_c + p_u) if (p_c + p_u) > 0 else 1.0
        n_networks = max(5, engine.n_mules * 2)
        self.smurf_networks = []
        for _ in range(n_networks):
            emitter = int(self.gen.integers(self.n_c))
            receiver = self._other_client(emitter)
            k = int(self.gen.integers(sm["n_mules_min"], sm["n_mules_max"] + 1))
            n_conscious = min(int(round(k * share_conscious)), self.n_u)
            conscious = self.u_off + self._distinct(self.n_u, n_conscious)
            unconscious = self._distinct(self.n_c, k - n_conscious, exclude=(emitter, receiver))
            net_mules = np.concatenate([conscious, unconscious]).astype(np.int64)
            self.smurf_networks.append({
                "emitter": emitter, "receiver": receiver, "mules": net_mules,
                "conscious": set(int(m) for m in conscious),
                "next_op_step": int(self.gen.integers(0, 30 * 24)),
            })
        self._smurf_next = np.array([n["next_op_step"] for n in self.smurf_networks], dtype=np.int64)
        # Transactions légitimes de couverture des mules conscientes : step -> [mules]
        self._pending_legit: dict = {}

        # Nombre d'injections fraude par step : proportionnel au nombre de mules
        # pour que le taux de fraude cible (~23%) soit atteignable par SPSA.
        self._n_inject_per_step = max(1, engine.n_mules)
        # Option : le profil de volume légitime varie fortement d'un step à l'autre
        # alors que l'injection est constante. Avec volume_follow, le nombre
        # d'injections suit le volume du step (moyenne inchangée).
        self.volume_follow = bool(volume_follow)
        tgt = params.step_target_np
        self._target = tgt
        self._mean_target = float(tgt.mean()) or 1.0

    # ── tirages rapides ──────────────────────────────────────────────────────
    def _distinct(self, n: int, k: int, exclude=()) -> np.ndarray:
        """k entiers distincts de [0, n), en ordre aléatoire, hors `exclude`."""
        excl = set(int(e) for e in exclude if 0 <= int(e) < n)
        k = min(int(k), n - len(excl))
        if k <= 0:
            return np.zeros(0, dtype=np.int64)
        if 4 * (k + len(excl)) > n:
            pool = self.gen.permutation(n)
            if excl:
                pool = pool[~np.isin(pool, list(excl))]
            return pool[:k].astype(np.int64)
        out, seen = [], set(excl)
        while len(out) < k:
            for v in self.gen.integers(0, n, size=2 * (k - len(out))).tolist():
                if v not in seen:
                    seen.add(v)
                    out.append(v)
                    if len(out) == k:
                        break
        return np.array(out, dtype=np.int64)

    def _other_client(self, c: int) -> int:
        if self.n_c < 2:
            return c
        while True:
            v = int(self.gen.integers(self.n_c))
            if v != c:
                return v

    def _random_merchant(self) -> int:
        return self.m_off + int(self.gen.integers(self.n_m))

    #
    def _log(self, step, action, amount, orig, dest, scenario,
              flagged=False, time_s=0.0):
        old_o, new_o, old_d, new_d, success = self.engine.transfer(orig, dest, amount)
        self.engine.log_transaction(step, action, amount, orig, dest, old_o, new_o, old_d, new_d,
                                     is_fraud=True, is_flagged=flagged, scenario=scenario,
                                     success=success, time_s=time_s)
        return success

    def _log_cash_in(self, step, amount, client, agent, scenario, time_s=0.0):
        """CASH_IN frauduleux journalisé avec la MÊME convention que les CASH_IN
        légitimes du moteur (et de MoMTSim d'origine) : nameOrig = client crédité,
        nameDest = agent. Le flux reste agent -> client (l'agent cède son float).
        Journaliser l'agent en nameOrig ferait de l'orientation (et du solde de
        l'émetteur, un float d'agent) un indicateur direct de l'étiquette."""
        old_a, new_a, old_c, new_c, success = self.engine.transfer(agent, client, amount)
        self.engine.log_transaction(step, "CASH_IN", amount, client, agent, old_c, new_c,
                                    old_a, new_a, is_fraud=True, is_flagged=False,
                                    scenario=scenario, success=success, time_s=time_s)
        return success

    def _log_legit(self, step, action, amount, orig, dest, time_s=0.0):
        """Transaction légitime de camouflage (is_fraud=False, is_flagged=False)."""
        old_o, new_o, old_d, new_d, success = self.engine.transfer(orig, dest, amount)
        self.engine.log_transaction(step, action, amount, orig, dest, old_o, new_o, old_d, new_d,
                                     is_fraud=False, is_flagged=False, scenario=None,
                                     success=success, time_s=time_s)
        return success

    def _add_pending(self, sched_step: int, entry: tuple):
        self._pending.setdefault(int(sched_step), []).append(entry)

    def _flush_pending(self, current_step: int):
        """Exécute toutes les transactions différées dont le step planifié <= current_step."""
        due = [s for s in self._pending if s <= current_step]
        for s in sorted(due):
            for action, amount, orig, dest, scenario, flagged in self._pending.pop(s):
                self._log(current_step, action, amount, orig, dest, scenario, flagged)

    #
    # 3.2.1  ATO
    #
    def _run_ato(self, step: int):
        c = self.cfg["ato"]
        victim = int(self.gen.integers(self.n_c))
        B0 = float(self.engine.host_balance()[victim])
        if B0 < c["B_min"]:
            return
        n = int(self.gen.integers(c["n_min"], c["n_max"] + 1))
        chosen_mules = self.u_off + self._distinct(self.n_u, n)
        if len(chosen_mules) == 0:
            return

        # Timing intra-step : Δt_i ~ Exp(λ_ATO) (§3.2.1)
        # lambda_ato (config) = intervalle moyen en minutes entre transferts ATO
        scale_s = float(c.get("lambda_ato", 2)) * 60
        time_offsets_s = self.gen.exponential(scale=scale_s, size=len(chosen_mules)).cumsum().tolist()
        fracs = self.gen.uniform(c["frag_min"], c["frag_max"], size=len(chosen_mules)).tolist()

        remaining = B0
        total_exfil = 0.0
        for i, mule in enumerate(chosen_mules.tolist()):
            if remaining <= 0:
                break
            amount = min(remaining, fracs[i] * B0)
            if amount <= 1:
                continue
            self._log(step, "TRANSFER", amount, victim, mule, "ATO", time_s=time_offsets_s[i])
            remaining -= amount
            total_exfil += amount
        if total_exfil > 0:
            self._tracking["ato"].append({
                "step": step, "victim": victim,
                "n_mules": len(chosen_mules), "total_amount": total_exfil,
            })

    #
    # 3.2.2  Refund Fraud
    #
    def _run_refund(self, step: int):
        c = self.cfg["refund"]
        if not self._refund_vuln_list or self._refund_merchant_idx >= len(self._refund_vuln_list):
            return

        # ratio_legit (défaut 0.30 §3.2.2) : probabilité de faire une tx légitime de camouflage
        if self.gen.random() < c["ratio_legit"]:
            merchant = self._random_merchant()
            amount = max(float(self.gen.normal(3325, 800)), 100.0)
            self._log_legit(step, "PAYMENT", amount, self._refund_fraudster, merchant)
            return

        merchant = self._refund_vuln_list[self._refund_merchant_idx]
        amount = max(float(self.gen.normal(3325, 800)), 100.0)

        # PAYMENT immédiat : fraudeur → marchand vulnérable
        self._log(step, "PAYMENT", amount, self._refund_fraudster, merchant, "REFUND")

        # REFUND différé : Δt ~ U(delay_min_hours, delay_max_hours)  marchand rembourse le fraudeur (§3.2.2)
        delay = int(self.gen.integers(c["delay_min_hours"], c["delay_max_hours"] + 1))
        self._add_pending(step + delay, ("REFUND", amount, merchant,
                                         self._refund_fraudster, "REFUND", False))
        self._tracking["refund"].append({
            "step": step, "fraudster": self._refund_fraudster,
            "merchant": merchant, "amount": amount, "delay_hours": delay,
        })

        # Compteur par marchand (k_max cycles avant de passer au marchand suivant)
        self._refund_cycle_count += 1
        if self._refund_cycle_count >= c["k_max"]:
            self._refund_merchant_idx += 1
            self._refund_cycle_count = 0

    #
    # 3.2.3  Fake Credentials
    #
    def _fake_credentials_step(self, step: int, allow_new: bool):
        c = self.cfg["fake_credentials"]
        agents = self._fake_cred_agents   # comptes non encore exploités
        if allow_new and len(agents) < self.FAKE_CRED_POOL:
            cid = int(self.gen.integers(self.n_c))
            if cid not in agents:
                dormance_h = int(self.gen.integers(c["dormance_min_days"] * 24,
                                                    c["dormance_max_days"] * 24))
                agents[cid] = {
                    "dormant_until": step + dormance_h, "dormance_h": dormance_h,
                    "n_leg_done": 0,
                    "n_leg_target": int(self.gen.integers(c["n_leg_min"], c["n_leg_max"] + 1)),
                    "activated": False,
                }
        if not agents:
            return

        eng = self.engine
        hb = eng.host_balance()
        exploited = []
        for cid, state in agents.items():
            if step < state["dormant_until"]:
                if state["n_leg_done"] < state["n_leg_target"] and self.gen.random() < 0.1:
                    merchant = self._random_merchant()
                    amount = float(self.gen.uniform(500, c["m_leg_max"]))
                    old_o, new_o, old_d, new_d, success = eng.transfer(cid, merchant, amount)
                    eng.log_transaction(step, "PAYMENT", amount, cid, merchant, old_o, new_o,
                                        old_d, new_d, is_fraud=False, scenario=None, success=success)
                    state["n_leg_done"] += 1
                continue
            # Fin de dormance : exfiltration unique, le compte quitte le réservoir
            exploited.append(cid)
            state["activated"] = True
            dest = int(self.gen.integers(self.n_c))
            # Calibre le plafond sur le solde réel disponible pour éviter les transfers nuls
            solde_cid = float(hb[cid])
            if solde_cid <= 0:
                continue
            plafond = min(max(float(self._mean_client[cid]) * 10, 50000), solde_cid)
            amount = max(1.0, float(self.gen.uniform(c["m_exp_ratio_min"] * plafond, plafond)))
            # is_flagged=False : le KYC n'a pas détecté l'usurpation  c'est l'essence du scénario
            self._log(step, "TRANSFER", amount, cid, dest, "FAKE_CRED", flagged=False)
            self._tracking["fake_credentials"].append({
                "step_activation": step, "cid": cid,
                "dormance_hours": state.get("dormance_h", 0),
                "amount": amount,
            })
        for cid in exploited:
            del agents[cid]

    #
    # 3.2.4  Split Deposit
    #
    def _commission(self, amount: float) -> float:
        c = 0.0
        for threshold, commission in self._tariff:
            if amount >= threshold:
                c = commission
        return c

    def _optimal_fragmentation(self, total: float) -> list:
        best_k, best_gain = 1, self._commission(total)
        for k in range(2, 6):
            gain_k = k * self._commission(total / k)
            if gain_k > best_gain:
                best_gain, best_k = gain_k, k

        eps_max = self.cfg["split_deposit"]["epsilon_max"]
        base = total / best_k
        frags = []
        remaining = total
        for j in range(best_k - 1):
            eps_j = self.gen.uniform(0, eps_max)  # ε_j indépendant par fragment (eq. 3.2.4)
            frag = base + self.gen.uniform(-eps_j, eps_j)
            max_frag = remaining - (best_k - 1 - j) * 1.0
            frag = max(1.0, min(frag, max_frag))
            frags.append(frag)
            remaining -= frag
        frags.append(max(1.0, remaining))  # dernier fragment garanti positif, Σm_j = M conservée
        return frags

    def _run_split_deposit(self, step: int):
        if len(self._split_dep_agents) == 0:
            return
        agent = int(self._split_dep_agents[self.gen.integers(len(self._split_dep_agents))])
        client = int(self.gen.integers(self.n_c))
        available = float(self.engine.host_balance()[agent])
        if available < 2000:
            return  # agent vraiment à sec  cas rare grâce au rebalancement toutes les 24h
        total_deposit = float(self.gen.uniform(2000, min(80000.0, available)))
        fragments = self._optimal_fragmentation(total_deposit)

        # Fenêtre temporelle intra-step : T_split ~ U(T_split_min_sec, T_split_max_sec) (§3.2.4)
        # Les k fragments sont répartis uniformément dans cette fenêtre.
        c_sd = self.cfg["split_deposit"]
        T_split = float(self.gen.uniform(c_sd.get("T_split_min_sec", 120),
                                         c_sd.get("T_split_max_sec", 600)))
        n_f = len(fragments)
        times_s = [T_split * i / (n_f - 1) for i in range(n_f)] if n_f > 1 else [0.0]

        for frag, t_s in zip(fragments, times_s):
            self._log_cash_in(step, frag, client, agent, "SPLIT_DEP", time_s=t_s)
        self._tracking["split_deposit"].append({
            "step": step, "agent": agent, "client": client,
            "n_frags": n_f, "total_amount": total_deposit,
            "fragments": [float(f) for f in fragments],
        })

    #
    # 3.2.5  Smurfing (Zhdanova et al.)
    #
    def _run_smurfing(self, step: int):
        due = np.flatnonzero(self._smurf_next <= step)
        if len(due) == 0:
            return
        c = self.cfg["smurfing"]
        smurf_mult = self.probas.get("smurfing_freq_mult", 1.0)
        interval = (c["operation_interval_days"] * 24) / max(smurf_mult, 1e-3)
        hb = self.engine.host_balance()
        for j in due.tolist():
            net = self.smurf_networks[j]
            # next_op_step mis à jour AVANT la vérification du solde (évite busy-retry)
            nxt = step + max(1, int(self.gen.normal(interval, 24)))
            net["next_op_step"] = nxt
            self._smurf_next[j] = nxt

            emitter_balance = float(hb[net["emitter"]])
            s_seuil = c["S_seuil"]

            # total_X ∝ solde courant de l'émetteur (40–80 %), indépendant de l'échelle FCFA.
            total_X = emitter_balance * float(self.gen.uniform(0.4, 0.8))
            # Seuil minimal : au moins 2 fragments à ≥ 70 % du seuil COBAC simulé
            frag_min_viable = 2 * 0.70 * s_seuil
            if total_X < frag_min_viable or emitter_balance < frag_min_viable:
                # Adapter le seuil de référence à l'échelle du solde si besoin
                s_seuil = emitter_balance / (2 * 0.70 * 2)  # 4 demi-fragments
                total_X = emitter_balance * float(self.gen.uniform(0.4, 0.8))
            if total_X < 1.0 or len(net["mules"]) < 2:
                continue

            mules = net["mules"]
            k = int(self.gen.integers(2, len(mules) + 1))
            chosen = mules[self._distinct(len(mules), k)]
            # x_i ~ U(0.70·S, 0.99·S) indépendants, renormalisés pour respecter total_X
            raw = self.gen.uniform(0.70 * s_seuil, 0.99 * s_seuil, size=len(chosen))
            fractions = (raw / raw.sum() * min(total_X, len(chosen) * 0.99 * s_seuil)).tolist()
            deltas = self.gen.uniform(c["delta_min"], c["delta_max"], size=len(chosen)).tolist()
            delays = self.gen.integers(c["delay_mule_min_hours"], c["delay_mule_max_hours"] + 1,
                                       size=len(chosen)).tolist()

            total_emitted = 0.0
            for mule, x_i, delta_i, delay_mule in zip(chosen.tolist(), fractions, deltas, delays):
                # Émetteur → mule (immédiat)
                self._log(step, "TRANSFER", x_i, net["emitter"], mule, "SMURFING")
                total_emitted += x_i
                # Mule → récepteur différé : Δt_mule ~ U(1h, 12h) (eq. 3.2.5)
                self._add_pending(step + delay_mule, ("TRANSFER", x_i * (1 - delta_i), mule,
                                                      net["receiver"], "SMURFING", False))
            if total_emitted > 0:
                self._tracking["smurfing"].append({
                    "step": step, "emitter": net["emitter"],
                    "n_mules": len(chosen), "receiver": net["receiver"],
                    "total_x": total_emitted,
                })
                self._schedule_mule_cover(net, step)

    def _schedule_mule_cover(self, net: dict, step: int):
        """Planifie, pour chaque mule consciente du réseau, n_leg ~ U[n_leg_mule_min,
        n_leg_mule_max] transactions légitimes réparties uniformément entre cette
        opération et la suivante (§3.2.5) : elles donnent au compte mule dédié un
        profil d'activité ordinaire. Les mules inconscientes, comptes clients réels,
        ont déjà leur activité légitime propre dans le moteur."""
        c = self.cfg["smurfing"]
        lo, hi = step + 1, net["next_op_step"]
        if hi <= lo:
            return
        for mule in net["conscious"]:
            n_leg = int(self.gen.integers(c.get("n_leg_mule_min", 0),
                                          c.get("n_leg_mule_max", 0) + 1))
            for s in self.gen.integers(lo, hi, size=n_leg).tolist():
                self._pending_legit.setdefault(s, []).append(mule)

    def _flush_mule_cover(self, current_step: int):
        """Exécute les transactions de couverture des mules conscientes arrivées à
        échéance : PAYMENT légitime vers un marchand, montant tiré du profil PAYMENT
        d'un client de la population, borné à 90 % du solde de la mule."""
        due = [s for s in self._pending_legit if s <= current_step]
        if not due:
            return
        hb = self.engine.host_balance()
        mules = [m for s in sorted(due) for m in self._pending_legit.pop(s)]
        for mule in mules:
            balance = float(hb[mule])
            ref = int(self.gen.integers(self.n_c))
            mu, sd = float(self._pay_mu[ref]), float(self._pay_sd[ref])
            amount = min(max(float(self.gen.normal(mu, sd)), 1.0), 0.9 * balance)
            if amount < 1.0:
                continue
            self._log_legit(current_step, "PAYMENT", amount, mule, self._random_merchant())

    #
    def inject(self, step: int):
        self.engine.host_balance()
        # Transactions différées traitées une seule fois par step
        self._flush_pending(step)
        self._flush_mule_cover(step)

        # Boucle d'injection : _n_inject_per_step tirages indépendants par step.
        # ATO / REFUND / SPLIT_DEP scalent avec n_mules. Les tirages sont faits en
        # bloc puis les déclenchements exécutés dans l'ordre (tirage, ATO, REFUND,
        # SPLIT_DEP), comme dans la boucle scalaire d'origine.
        # FAKE_CRED et SMURFING sont des machines d'états  appelés une seule fois par step.
        n_inject = self._n_inject_per_step
        if self.volume_follow:
            ratio = float(self._target[step % len(self._target)]) / self._mean_target
            n_inject = max(1, int(round(self._n_inject_per_step * ratio)))
        p = np.array([self.probas["ato"], self.probas["refund"], self.probas["split_deposit"]])
        hits = np.flatnonzero(self.gen.random((n_inject, 3)) < p) % 3
        for h in hits.tolist():
            if h == 0:
                self._run_ato(step)
            elif h == 1:
                self._run_refund(step)
            else:
                self._run_split_deposit(step)
        # FAKE_CRED : 1 appel/step  pool de 200 comptes dormants avec activation unique
        allow_new = self.gen.random() < self.probas["fake_credentials"]
        self._fake_credentials_step(step, allow_new)
        self._run_smurfing(step)

    def get_tracking(self) -> dict:
        """Retourne le dictionnaire de suivi des opérations frauduleuses."""
        return self._tracking

    def export_fraudster_summary(self) -> "pd.DataFrame":
        """Consolide le tracking en DataFrame (une ligne par opération frauduleuse)."""
        rows = []
        for ev in self._tracking["ato"]:
            rows.append({"scenario": "ATO", "step": ev["step"],
                         "actor": ev["victim"], "n_targets": ev["n_mules"],
                         "amount": ev["total_amount"]})
        for ev in self._tracking["refund"]:
            rows.append({"scenario": "REFUND", "step": ev["step"],
                         "actor": ev["fraudster"], "n_targets": 1,
                         "amount": ev["amount"]})
        for ev in self._tracking["fake_credentials"]:
            rows.append({"scenario": "FAKE_CRED", "step": ev["step_activation"],
                         "actor": ev["cid"], "n_targets": 1,
                         "amount": ev["amount"]})
        for ev in self._tracking["split_deposit"]:
            rows.append({"scenario": "SPLIT_DEP", "step": ev["step"],
                         "actor": ev["agent"], "n_targets": ev["n_frags"],
                         "amount": ev["total_amount"]})
        for ev in self._tracking["smurfing"]:
            rows.append({"scenario": "SMURFING", "step": ev["step"],
                         "actor": ev["emitter"], "n_targets": ev["n_mules"],
                         "amount": ev["total_x"]})
        if not rows:
            return pd.DataFrame(columns=["scenario", "step", "actor", "n_targets", "amount"])
        return pd.DataFrame(rows)


if __name__ == "__main__":
    from pathlib import Path as _Path
    _root = _Path(__file__).parent.parent

    params = TorchParameters(
        str(_root / "config" / "paramFiles"),
        str(_root / "config" / "fraudScenariosConfig.json"),
        n_clients=2000, seed=1000)
    engine = TorchMoMTSimEngine(params, n_clients=2000, n_merchants=300, n_banks=20,
                                 n_mules=60, max_slots_per_step=6, seed=1000)

    fraud_probas = None
    _probas_path = str(_root / "config" / "calibrated_probas.json")
    if os.path.exists(_probas_path):
        with open(_probas_path, "r", encoding="utf-8") as f:
            fraud_probas = json.load(f)

    injector = TorchFraudInjector(engine, params, fraud_probas=fraud_probas, seed=1000)

    N_STEPS = 720
    for step in range(N_STEPS):
        engine.simulate_step(step, injector)
        if step % 50 == 0:
            print(f"step {step}/{N_STEPS}  {engine.n_logged} tx cumulées "
                  f"({engine.n_fraud_logged} frauduleuses)", flush=True)

    df = engine.to_dataframe()
    _raw_out = str(_root / "config" / "rawLog_torch.parquet")
    df.to_parquet(_raw_out, index=False)
    fraud_rate = df["isFraud"].mean()
    print(f"\nTerminé  {len(df)} transactions, device={DEVICE}")
    print(f"Taux de fraude global : {fraud_rate:.3f}")
    print(df.loc[df["isFraud"], "fraudScenario"].value_counts(normalize=True))
