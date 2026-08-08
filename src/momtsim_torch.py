"""
momtsim_torch.py — Moteur MoMTSim vectorisé PyTorch.
Boucle externe : 720 steps (séquentiel, dépendance de solde inter-steps).
Boucle interne : max_slots par step (petit, ex. 6), vectorisé sur tous les
clients simultanément via des tenseurs.

Représentation : tous les acteurs (clients, marchands, banques, mules) sont
indexés dans un unique tenseur de solde `balance` de taille n_actors, pour
permettre des opérations scatter/gather uniformes.
"""

import numpy as np
import torch
import pandas as pd
import json

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


class TorchParameters:
    """Charge les 6 CSV + config fraude JSON, et pré-calcule des tenseurs
    par client (un profil moyen/std par action, tiré une fois à l'initialisation
    -- équivalent du tirage de profil aléatoire par client de la version NumPy)."""

    ACTIONS = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER", "DEPOSIT"]
    IN_ACTIONS = {"CASH_IN", "DEPOSIT"}   # actions qui font entrer de l'argent (spring model)
    OUT_ACTIONS = {"CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER"}

    def __init__(self, param_dir: str, fraud_config_path: str, n_clients: int,
                 seed: int = 1000):
        self.rng = np.random.default_rng(seed)
        self.n_clients = n_clients

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

    # ------------------------------------------------------------------
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

        # solde initial par tranche empirique
        lo = self.balances_df["range_min"].values
        hi = self.balances_df["range_max"].values
        props = self.balances_df["proportion"].values / self.balances_df["proportion"].values.sum()
        bin_idx = self.rng.choice(len(self.balances_df), size=n, p=props)
        init_balance = self.rng.uniform(lo[bin_idx], hi[bin_idx])
        self.initial_balance = torch.tensor(init_balance, dtype=torch.float32, device=DEVICE)

        # Mobile Money CEMAC : pas de découvert — le solde ne peut pas être négatif.
        # On force overdraft_limit = 0 quelle que soit la valeur dans le CSV.
        mean_global = mean_mat[np.arange(n)[:, None], np.arange(len(self.ACTIONS))].mean(axis=1)
        overdraft = np.zeros(n)
        for i, m in enumerate(mean_global):
            overdraft[i] = max(0.0, self._overdraft_for(m))  # clamp ≥ 0
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

    def sample_agent_float(self, n: int) -> np.ndarray:
        """Tire n valeurs de float initial pour les agents distributeurs/banques
        selon agentFloatDistribution.csv — §3.2.4 du mémoire, \citet{gsma2010agents,ifc2017liquidity}."""
        lo = self.agent_float_df["range_min"].values
        hi = self.agent_float_df["range_max"].values
        props = self.agent_float_df["proportion"].values / self.agent_float_df["proportion"].values.sum()
        bin_idx = self.rng.choice(len(self.agent_float_df), size=n, p=props)
        return self.rng.uniform(lo[bin_idx], hi[bin_idx])

    def _overdraft_for(self, mean_amount: float) -> float:
        for _, row in self.overdraft_df.iterrows():
            lo = -np.inf if str(row["mean_amount_min"]) == "-inf" else float(row["mean_amount_min"])
            hi = np.inf if str(row["mean_amount_max"]) == "inf" else float(row["mean_amount_max"])
            if lo <= mean_amount < hi:
                return float(row["overdraft_limit"])
        return 0.0

    def _build_step_target_tensors(self):
        """stepTargetCount(step) : volume total de tx attendu par step, toutes
        actions confondues -- pilote la binomiale."""
        by_step = self.agg_df.groupby("step")["count"].sum()
        arr = np.zeros(720)
        for s, c in by_step.items():
            if 0 <= int(s) < 720:
                arr[int(s)] = c
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


class TorchMoMTSimEngine:
    """Moteur vectorisé : n_clients clients + n_merchants marchands + n_banks
    banques, tous indexés dans un même tenseur `balance`."""

    def __init__(self, params: TorchParameters, n_clients: int, n_merchants: int,
                 n_banks: int, n_mules: int = 60, max_slots_per_step: int = 6, seed: int = 1000):
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
        self.gen = torch.Generator(device=DEVICE).manual_seed(seed)

        self.balance = torch.zeros(self.n_actors, dtype=torch.float32, device=DEVICE)
        self.balance[:n_clients] = params.initial_balance
        # Float initial des agents distributeurs et banques (§3.2.4 — GSMA 2010 / IFC 2017).
        # Tiré depuis agentFloatDistribution.csv : petits agents 100k-500k FCFA (60 %),
        # agents moyens 500k-2M FCFA (30 %), grands agents/banques 2M-10M FCFA (10 %).
        n_agents = n_merchants + n_banks
        agent_float = params.sample_agent_float(n_agents)
        self.balance[self.MERCHANT_OFFSET:self.MULE_OFFSET] = torch.tensor(
            agent_float, dtype=torch.float32, device=DEVICE)
        # mules : soldes initiaux nuls (comptes créés pour la fraude)
        self.balance[self.MULE_OFFSET:self.MULE_OFFSET + n_mules] = 0.0

        # Règle CEMAC : solde abonnés ≥ 0. Agents : plancher -1e9 pour les opérations
        # légitimes (CASH_IN bilatéral — flux physique compensatoire documenté).
        _AGENT_FLOOR = -1e9
        self.overdraft_limit = torch.full((self.n_actors,), _AGENT_FLOOR,
                                           dtype=torch.float32, device=DEVICE)
        # Clients abonnés : solde ≥ 0 imposé
        self.overdraft_limit[:n_clients] = torch.clamp(params.overdraft_limit, min=0.0)

        # marchands "high risk" (90% comme dans le doc MoMTSim, réutilisé comme
        # registre de vulnérabilité par défaut pour Refund Fraud)
        self.merchant_high_risk = torch.rand(n_merchants, generator=self.gen, device=DEVICE) < 0.90
        self.merchant_refund_proba = torch.rand(n_merchants, generator=self.gen, device=DEVICE) * 0.65 + 0.30

        self.in_prob = torch.full((n_clients,), 0.5, device=DEVICE)
        self.out_prob = torch.full((n_clients,), 0.5, device=DEVICE)

        # historique "stickiness" : buffer circulaire de 100 contacts par client
        self.history_buf = torch.full((n_clients, 100), -1, dtype=torch.int64, device=DEVICE)
        self.history_ptr = torch.zeros(n_clients, dtype=torch.int64, device=DEVICE)

        # historique des 10 derniers montants par (client, action) pour flag anomalie
        self.amount_hist = torch.zeros((n_clients, len(params.ACTIONS), 10),
                                        dtype=torch.float32, device=DEVICE)
        self.amount_hist_ptr = torch.zeros((n_clients, len(params.ACTIONS)),
                                            dtype=torch.int64, device=DEVICE)

        # buffer plat pour toutes les transactions générées (préalloué puis tronqué)
        self.log_step = []
        self.log_time_s = []   # secondes dans le step (précision intra-step ATO/SplitDep)
        self.log_action = []
        self.log_amount = []
        self.log_orig = []
        self.log_dest = []
        self.log_old_orig = []
        self.log_new_orig = []
        self.log_old_dest = []
        self.log_new_dest = []
        self.log_success = []
        self.log_is_fraud = []
        self.log_is_flagged = []
        self.log_scenario = []

    # ------------------------------------------------------------------
    def _spring_probabilities(self):
        """Vectorisé sur tous les clients : modèle de rappel vers l'équilibre.

        Principe (Azamuke et al., 2024 — modèle markovien de comportement client) :
          k             = 1 / équilibre_cible
          spring_force  = k · (équilibre - solde_courant)   ∈ [-1, +1]
          p_in          = clamp(0.5 · (1 + spring_force + (p_in_base - p_out_base)))

        Un client sous-équilibré (solde < équilibre) reçoit une force positive
        qui augmente sa probabilité de faire des dépôts (IN), et inversement.
        """
        k = 1.0 / self.params.equilibrium
        client_balance = self.balance[:self.n_clients]
        spring_force = k * (self.params.equilibrium - client_balance)
        new_in = 0.5 * (1 + spring_force + (self.in_prob - self.out_prob))
        new_in = torch.clamp(new_in, 0.0, 1.0)
        return new_in, 1.0 - new_in

    # ------------------------------------------------------------------
    def _draw_action_indices(self, in_prob: torch.Tensor) -> torch.Tensor:
        """Choix d'action vectorisé : pondère les actions IN par in_prob et
        les actions OUT par out_prob, puis tire selon ces poids modulés par
        disponibilité (profil du client)."""
        n = self.n_clients
        weights = self.params.action_available.float().clone()  # (n, n_actions)
        for j, action in enumerate(self.params.ACTIONS):
            if action in self.params.IN_ACTIONS:
                weights[:, j] *= in_prob
            else:
                weights[:, j] *= (1.0 - in_prob)
        weights = weights + 1e-8
        weights = weights / weights.sum(dim=1, keepdim=True)
        action_idx = torch.multinomial(weights, num_samples=1, generator=self.gen).squeeze(1)
        return action_idx  # (n,)

    # ------------------------------------------------------------------
    def _draw_amounts(self, step: int, action_idx: torch.Tensor) -> torch.Tensor:
        n = self.n_clients
        rows = torch.arange(n, device=DEVICE)
        mu_client = self.params.mean_amount_tensor[rows, action_idx]
        std_client = self.params.std_amount_tensor[rows, action_idx]
        _step_idx = step % self.params.step_avg.shape[0]
        mu_step = self.params.step_avg[_step_idx, action_idx]
        std_step = self.params.step_std[_step_idx, action_idx]

        mu = (mu_client + mu_step) / 2
        sigma = torch.sqrt(std_client**2 + std_step**2) / 2
        sigma = torch.clamp(sigma, min=1e-3)

        amounts = torch.normal(mu, sigma, generator=self.gen)
        # retirage vectorisé tant que négatif (borné à quelques essais)
        for _ in range(5):
            neg_mask = amounts <= 0
            if not neg_mask.any():
                break
            resample = torch.normal(mu, sigma, generator=self.gen)
            amounts = torch.where(neg_mask, resample, amounts)
        amounts = torch.clamp(amounts, min=1.0)
        return amounts

    # ------------------------------------------------------------------
    def _draw_counterparties(self, action_idx: torch.Tensor) -> torch.Tensor:
        """Stickiness 90/10 vectorisée. Actions CASH_IN/PAYMENT -> marchands,
        sinon -> clients. Retourne un index global dans [0, n_actors)."""
        n = self.n_clients
        is_merchant_action = torch.zeros(n, dtype=torch.bool, device=DEVICE)
        for j, action in enumerate(self.params.ACTIONS):
            if action in ("CASH_IN", "PAYMENT"):
                is_merchant_action |= (action_idx == j)

        use_history = (torch.rand(n, generator=self.gen, device=DEVICE) < 0.90) & \
                      (self.history_buf[:, 0] >= 0)

        # choix dans l'historique : index aléatoire parmi les entrées valides (>=0)
        valid_counts = (self.history_buf >= 0).sum(dim=1).clamp(min=1)
        rand_slot = (torch.rand(n, generator=self.gen, device=DEVICE) * valid_counts.float()).long()
        hist_choice = self.history_buf[torch.arange(n, device=DEVICE), rand_slot]

        # choix aléatoire global (nouveau contact)
        rand_merchant = torch.randint(self.n_clients, self.n_clients + self.n_merchants,
                                       (n,), generator=self.gen, device=DEVICE)
        rand_client = torch.randint(0, self.n_clients, (n,), generator=self.gen, device=DEVICE)
        rand_new = torch.where(is_merchant_action, rand_merchant, rand_client)

        dest = torch.where(use_history & (hist_choice >= 0), hist_choice, rand_new)
        # éviter l'auto-transaction
        self_tx = dest == torch.arange(n, device=DEVICE)
        dest = torch.where(self_tx, rand_new, dest)
        return dest

    def _update_history(self, orig_idx: torch.Tensor, dest_idx: torch.Tensor, is_new: torch.Tensor):
        """Ajoute dest_idx à l'historique circulaire des clients concernés, si nouveau
        et avec probabilité 90% (approximé ici à systématique pour les nouveaux --
        cohérent avec la doc qui donne 90% de chance de mémorisation)."""
        remember_mask = is_new & (torch.rand(len(orig_idx), generator=self.gen, device=DEVICE) < 0.90)
        idxs = orig_idx[remember_mask]
        if len(idxs) == 0:
            return
        ptrs = self.history_ptr[idxs]
        self.history_buf[idxs, ptrs] = dest_idx[remember_mask]
        self.history_ptr[idxs] = (ptrs + 1) % 100

    # ------------------------------------------------------------------
    def _run_step_slot(self, step: int, slot_mask: torch.Tensor):
        """Traite un slot de transaction pour tous les clients marqués actifs
        dans slot_mask (tenseur bool de taille n_clients).

        Sémantique des flux bilatéraux (section 3.1 du mémoire) :
          IN  (CASH_IN, DEPOSIT) : l'agent/banque (dest) cède de la liquidité digitale
              au client (orig). Flux : dest → orig.
              → balance[orig] += amount  (client gagne)
              → balance[dest] -= amount  (agent de liquidité cède son float)
              Condition : le client est toujours actif (pas de contrainte de solde
              côté client pour recevoir). L'agent peut descendre en négatif (float).

          OUT (CASH_OUT, DEBIT, PAYMENT, TRANSFER) : le client envoie. Flux : orig → dest.
              → balance[orig] -= amount  (client perd)
              → balance[dest] += amount  (contrepartie gagne)
              Condition : solde client ≥ amount (overdraft_limit = 0 au CEMAC).

          Les marchands/banques ont un floor = -1e9 (float agent).
          Les clients abonnés ont un floor = 0 (règle CEMAC).
        """
        n = self.n_clients
        in_prob, _ = self._spring_probabilities()
        action_idx = self._draw_action_indices(in_prob)
        amounts = self._draw_amounts(step, action_idx)
        dest_idx = self._draw_counterparties(action_idx)

        orig_idx = torch.arange(n, device=DEVICE)

        # Masque actions IN (CASH_IN, DEPOSIT)
        _in_indices = torch.tensor(
            [j for j, a in enumerate(self.params.ACTIONS) if a in self.params.IN_ACTIONS],
            device=DEVICE)
        is_in_action = torch.isin(action_idx, _in_indices)

        # OUT : le client doit avoir assez (solde ≥ 0 CEMAC)
        can_pay_out = (self.balance[orig_idx] - amounts) >= self.overdraft_limit[orig_idx]

        active_in  = slot_mask & is_in_action           # IN : client reçoit (toujours ok)
        active_out = slot_mask & ~is_in_action & can_pay_out  # OUT : client envoie si solde ok
        active     = active_in | active_out

        old_orig = self.balance[orig_idx].clone()
        old_dest = self.balance[dest_idx].clone()

        # IN : dest (agent/banque) → orig (client)  — flux bilatéral inversé
        in_amounts = torch.where(active_in, amounts, torch.zeros_like(amounts))
        self.balance.index_add_(0, orig_idx,  in_amounts)   # client +
        self.balance.index_add_(0, dest_idx, -in_amounts)   # agent  -

        # OUT : orig (client) → dest (marchand/client/banque)
        out_amounts = torch.where(active_out, amounts, torch.zeros_like(amounts))
        self.balance.index_add_(0, orig_idx, -out_amounts)  # client -
        self.balance.index_add_(0, dest_idx,  out_amounts)  # dest   +

        already_known = (self.history_buf == dest_idx.unsqueeze(1)).any(dim=1)
        is_new = ~already_known
        self._update_history(orig_idx[active], dest_idx[active], is_new[active])

        # log (uniquement les actifs)
        active_np = active.cpu().numpy()
        if active_np.any():
            action_names = np.array(self.params.ACTIONS)[action_idx.cpu().numpy()]
            self.log_step.extend([step] * active_np.sum())
            self.log_time_s.extend([0.0] * active_np.sum())
            self.log_action.extend(action_names[active_np].tolist())
            self.log_amount.extend(amounts[active].cpu().numpy().tolist())
            self.log_orig.extend(orig_idx[active].cpu().numpy().tolist())
            self.log_dest.extend(dest_idx[active].cpu().numpy().tolist())
            self.log_old_orig.extend(old_orig[active].cpu().numpy().tolist())
            self.log_new_orig.extend(self.balance[orig_idx][active].cpu().numpy().tolist())
            self.log_old_dest.extend(old_dest[active].cpu().numpy().tolist())
            self.log_new_dest.extend(self.balance[dest_idx][active].cpu().numpy().tolist())
            self.log_success.extend([True] * active_np.sum())
            self.log_is_fraud.extend([False] * active_np.sum())
            self.log_is_flagged.extend([False] * active_np.sum())
            self.log_scenario.extend([None] * active_np.sum())

    # ------------------------------------------------------------------
    def run(self, n_steps: int = 720, verbose=True) -> pd.DataFrame:
        for step in range(n_steps):
            n_tx_target = self.params.step_target_count[step % len(self.params.step_target_count)]
            n_tx_per_client = torch.distributions.Binomial(
                total_count=n_tx_target.clamp(min=0),
                probs=self.params.client_weight.clamp(0, 1)
            ).sample()
            n_tx_per_client = torch.clamp(n_tx_per_client, max=self.max_slots).long()

            for slot in range(self.max_slots):
                slot_mask = n_tx_per_client > slot
                if slot_mask.any():
                    self._run_step_slot(step, slot_mask)

            if verbose and step % 50 == 0:
                print(f"step {step}/{n_steps} — {len(self.log_step)} tx cumulées", flush=True)

        return self.to_dataframe()

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame({
            "step":           np.array(self.log_step,        dtype=np.int32),
            "time_s":         np.array(self.log_time_s,      dtype=np.float32),
            "action":         self.log_action,
            "amount":         np.array(self.log_amount,      dtype=np.float32),
            "nameOrig":       np.array(self.log_orig,        dtype=np.int32),
            "nameDest":       np.array(self.log_dest,        dtype=np.int32),
            "oldBalanceOrig": np.array(self.log_old_orig,    dtype=np.float32),
            "newBalanceOrig": np.array(self.log_new_orig,    dtype=np.float32),
            "oldBalanceDest": np.array(self.log_old_dest,    dtype=np.float32),
            "newBalanceDest": np.array(self.log_new_dest,    dtype=np.float32),
            "isSuccessful":   np.array(self.log_success,     dtype=np.bool_),
            "isFraud":        np.array(self.log_is_fraud,    dtype=np.bool_),
            "isFlaggedFraud": np.array(self.log_is_flagged,  dtype=np.bool_),
            "fraudScenario":  self.log_scenario,
        })

    def flush_log(self) -> pd.DataFrame:
        """Retourne le DataFrame des transactions accumulées et vide les listes."""
        df = self.to_dataframe()
        self.log_step.clear();     self.log_time_s.clear()
        self.log_action.clear();   self.log_amount.clear()
        self.log_orig.clear();     self.log_dest.clear()
        self.log_old_orig.clear(); self.log_new_orig.clear()
        self.log_old_dest.clear(); self.log_new_dest.clear()
        self.log_success.clear();  self.log_is_fraud.clear()
        self.log_is_flagged.clear(); self.log_scenario.clear()
        return df

    # ------------------------------------------------------------------
    def log_transaction(self, step: int, action: str, amount: float,
                         orig_idx: int, dest_idx: int, old_orig: float, new_orig: float,
                         old_dest: float, new_dest: float, is_fraud: bool = True,
                         is_flagged: bool = False, scenario: str = None,
                         success: bool = True, time_s: float = 0.0):
        """Point d'entrée unique utilisé par les fraudeurs pour journaliser
        une transaction générée hors du flux légitime standard.

        time_s : secondes dans le step courant (précision intra-step pour ATO
                 et Split Deposit — cf. scénarios 3.2.1 et 3.2.4 du mémoire).
        """
        self.log_step.append(step)
        self.log_time_s.append(float(time_s))
        self.log_action.append(action)
        self.log_amount.append(float(amount))
        self.log_orig.append(int(orig_idx))
        self.log_dest.append(int(dest_idx))
        self.log_old_orig.append(float(old_orig))
        self.log_new_orig.append(float(new_orig))
        self.log_old_dest.append(float(old_dest))
        self.log_new_dest.append(float(new_dest))
        self.log_success.append(success)
        self.log_is_fraud.append(is_fraud)
        self.log_is_flagged.append(is_flagged)
        self.log_scenario.append(scenario)

    def rebalance_agents(self, params) -> None:
        """Réapprovisionne le float e-money des agents/banques toutes les 24 steps
        (simulation du cycle de rebalancement quotidien documenté par GSMA 2010).
        Les clients et les mules ne sont pas affectés."""
        n_agents = self.n_merchants + self.n_banks
        new_float = params.sample_agent_float(n_agents)
        self.balance[self.MERCHANT_OFFSET:self.MULE_OFFSET] = torch.tensor(
            new_float, dtype=torch.float32, device=DEVICE)

    def transfer(self, orig_idx: int, dest_idx: int, amount: float) -> tuple:
        """Effectue un virement entre deux acteurs (indices globaux) sur le
        tenseur balance partagé, retourne (old_orig, new_orig, old_dest, new_dest, success)."""
        old_orig = float(self.balance[orig_idx].item())
        old_dest = float(self.balance[dest_idx].item())
        can_pay = (old_orig - amount) >= float(self.overdraft_limit[orig_idx].item())
        if can_pay:
            self.balance[orig_idx] -= amount
            self.balance[dest_idx] += amount
        new_orig = float(self.balance[orig_idx].item())
        new_dest = float(self.balance[dest_idx].item())
        return old_orig, new_orig, old_dest, new_dest, can_pay


# ---------------------------------------------------------------------------
# FRAUDEURS — branchés directement sur TorchMoMTSimEngine.balance (tenseur partagé)
# Formules identiques à la section 3.2 du mémoire, adaptées à l'indexation
# tensorielle du moteur torch.
# ---------------------------------------------------------------------------

class TorchFraudInjector:
    def __init__(self, engine: TorchMoMTSimEngine, params: TorchParameters,
                 fraud_probas: dict = None, seed: int = 1000):
        self.engine = engine
        self.params = params
        self.cfg = params.fraud_config
        self.gen = np.random.default_rng(seed)

        default_probas = {"ato": 0.02, "refund": 0.02, "fake_credentials": 0.005,
                           "split_deposit": 0.03, "smurfing_freq_mult": 1.0}
        self.probas = fraud_probas if fraud_probas is not None else default_probas

        n_c, n_m = engine.n_clients, engine.n_merchants
        self.client_ids = np.arange(n_c)
        self.merchant_ids = np.arange(engine.MERCHANT_OFFSET, engine.MERCHANT_OFFSET + n_m)
        self.mule_ids = np.arange(engine.MULE_OFFSET, engine.MULE_OFFSET + engine.n_mules)

        self._fake_cred_agents: dict = {}
        self._split_dep_agents = self.merchant_ids[engine.merchant_high_risk.cpu().numpy()]

        # File d'attente pour transactions différées (REFUND delay, mule→récepteur Smurfing)
        self._pending: list = []

        # Tracking par scénario — alimenté par chaque _run_* pour export_fraudster_summary()
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
        self._refund_vuln_list: list = list(self.merchant_ids[vuln_mask])
        self._refund_fraudster: int = int(self.gen.choice(self.client_ids))
        self._refund_merchant_idx: int = 0
        self._refund_cycle_count: int = 0

        # Smurfing : nombre de réseaux proportionnel aux mules disponibles
        # (2 réseaux par mule en moyenne pour assurer suffisamment de volume)
        n_networks = max(5, engine.n_mules * 2)
        self.smurf_networks = []
        for _ in range(n_networks):
            emitter = int(self.gen.choice(self.client_ids))
            receiver_pool = self.client_ids[self.client_ids != emitter]
            receiver = int(self.gen.choice(receiver_pool))
            k = int(self.gen.integers(self.cfg["smurfing"]["n_mules_min"],
                                       self.cfg["smurfing"]["n_mules_max"] + 1))
            net_mules = self.gen.choice(self.mule_ids, size=min(k, len(self.mule_ids)), replace=False)
            n_conscious = int(len(net_mules) * self.cfg["smurfing"]["pct_conscious"])
            self.smurf_networks.append({
                "emitter": emitter, "receiver": receiver, "mules": net_mules,
                "conscious": set(net_mules[:n_conscious].tolist()),
                "next_op_step": int(self.gen.integers(0, 30 * 24)),
            })

        # Nombre d'injections fraude par step : proportionnel au nombre de mules
        # pour que le taux de fraude cible (~23%) soit atteignable par SPSA.
        # Référence : n_mules >= 300 garantit un taux max >23% sur step_target_count réel.
        self._n_inject_per_step = max(1, engine.n_mules)

    # ------------------------------------------------------------------
    def _log(self, step, action, amount, orig, dest, scenario,
              flagged=False, time_s=0.0):
        old_o, new_o, old_d, new_d, success = self.engine.transfer(orig, dest, amount)
        self.engine.log_transaction(step, action, amount, orig, dest, old_o, new_o, old_d, new_d,
                                     is_fraud=True, is_flagged=flagged, scenario=scenario,
                                     success=success, time_s=time_s)
        return success

    def _log_legit(self, step, action, amount, orig, dest, time_s=0.0):
        """Transaction légitime de camouflage (is_fraud=False, is_flagged=False)."""
        old_o, new_o, old_d, new_d, success = self.engine.transfer(orig, dest, amount)
        self.engine.log_transaction(step, action, amount, orig, dest, old_o, new_o, old_d, new_d,
                                     is_fraud=False, is_flagged=False, scenario=None,
                                     success=success, time_s=time_s)
        return success

    def _flush_pending(self, current_step: int):
        """Exécute toutes les transactions différées dont le step planifié <= current_step."""
        remaining = []
        for entry in self._pending:
            sched_step, action, amount, orig, dest, scenario, flagged = entry
            if sched_step <= current_step:
                self._log(current_step, action, amount, orig, dest, scenario, flagged)
            else:
                remaining.append(entry)
        self._pending = remaining

    # ------------------------------------------------------------------
    # 3.2.1 — ATO
    # ------------------------------------------------------------------
    def _run_ato(self, step: int):
        c = self.cfg["ato"]
        victim = int(self.gen.choice(self.client_ids))
        B0 = float(self.engine.balance[victim].item())
        if B0 < c["B_min"]:
            return
        n = int(self.gen.integers(c["n_min"], c["n_max"] + 1))
        chosen_mules = self.gen.choice(self.mule_ids, size=min(n, len(self.mule_ids)), replace=False)

        # Timing intra-step : Δt_i ~ Exp(λ_ATO) (§3.2.1)
        # lambda_ato (config) = intervalle moyen en minutes entre transferts ATO
        lam_ato = 1.0 / (float(c.get("lambda_ato", 2)) * 60)  # → 1/120 s⁻¹ si lambda_ato=2
        raw_delays = self.gen.exponential(scale=1.0 / lam_ato, size=len(chosen_mules))
        time_offsets_s = [float(v) for v in raw_delays.cumsum()]  # t0=0, t1, t2, ...

        remaining = B0
        total_exfil = 0.0
        for i, mule in enumerate(chosen_mules):
            if remaining <= 0:
                break
            frac = self.gen.uniform(c["frag_min"], c["frag_max"])
            amount = min(remaining, frac * B0)
            if amount <= 1:
                continue
            self._log(step, "TRANSFER", amount, victim, int(mule), "ATO",
                      time_s=time_offsets_s[i])
            remaining -= amount
            total_exfil += amount
        if total_exfil > 0:
            self._tracking["ato"].append({
                "step": step, "victim": victim,
                "n_mules": len(chosen_mules), "total_amount": total_exfil,
            })

    # ------------------------------------------------------------------
    # 3.2.2 — Refund Fraud
    # ------------------------------------------------------------------
    def _run_refund(self, step: int):
        c = self.cfg["refund"]
        if not self._refund_vuln_list or self._refund_merchant_idx >= len(self._refund_vuln_list):
            return

        # ratio_legit (défaut 0.30 §3.2.2) : probabilité de faire une tx légitime de camouflage
        if self.gen.uniform() < c["ratio_legit"]:
            merchant = int(self.gen.choice(self.merchant_ids))
            amount = max(float(self.gen.normal(3325, 800)), 100.0)
            self._log_legit(step, "PAYMENT", amount, self._refund_fraudster, merchant)
            return

        merchant = self._refund_vuln_list[self._refund_merchant_idx]
        amount = max(float(self.gen.normal(3325, 800)), 100.0)

        # PAYMENT immédiat : fraudeur → marchand vulnérable
        self._log(step, "PAYMENT", amount, self._refund_fraudster, merchant, "REFUND")

        # REFUND différé : Δt ~ U(delay_min_hours, delay_max_hours) — marchand rembourse le fraudeur (§3.2.2)
        delay = int(self.gen.integers(c["delay_min_hours"], c["delay_max_hours"] + 1))
        self._pending.append((step + delay, "REFUND", amount, merchant,
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

    # ------------------------------------------------------------------
    # 3.2.3 — Fake Credentials
    # ------------------------------------------------------------------
    def _fake_credentials_step(self, step: int, allow_new: bool):
        # Libérer les comptes déjà activés pour permettre un renouvellement continu du pool
        self._fake_cred_agents = {
            k: v for k, v in self._fake_cred_agents.items() if not v["activated"]
        }
        c = self.cfg["fake_credentials"]
        if allow_new and len(self._fake_cred_agents) < 200:
            cid = int(self.gen.choice(self.client_ids))
            if cid not in self._fake_cred_agents:
                dormance_h = int(self.gen.integers(c["dormance_min_days"] * 24,
                                                    c["dormance_max_days"] * 24))
                self._fake_cred_agents[cid] = {
                    "dormant_until": step + dormance_h, "dormance_h": dormance_h,
                    "n_leg_done": 0,
                    "n_leg_target": int(self.gen.integers(c["n_leg_min"], c["n_leg_max"] + 1)),
                    "activated": False,
                }

        for cid, state in list(self._fake_cred_agents.items()):
            if state["activated"]:
                continue
            if step < state["dormant_until"] and state["n_leg_done"] < state["n_leg_target"]:
                if self.gen.uniform() < 0.1:
                    merchant = int(self.gen.choice(self.merchant_ids))
                    amount = float(self.gen.uniform(500, c["m_leg_max"]))
                    old_o, new_o, old_d, new_d, success = self.engine.transfer(cid, merchant, amount)
                    self.engine.log_transaction(step, "PAYMENT", amount, cid, merchant, old_o, new_o,
                                                 old_d, new_d, is_fraud=False, scenario=None, success=success)
                    state["n_leg_done"] += 1
            elif step >= state["dormant_until"]:
                dest = int(self.gen.choice(self.client_ids))
                mean_amount = float(self.params.mean_amount_tensor[cid].mean().item())
                # Calibre le plafond sur le solde réel disponible pour éviter les transfers nuls
                solde_cid = float(self.engine.balance[cid].item())
                if solde_cid <= 0:
                    state["activated"] = True
                    continue
                plafond = min(max(mean_amount * 10, 50000), solde_cid)
                amount = float(self.gen.uniform(c["m_exp_ratio_min"] * plafond, plafond))
                amount = max(1.0, amount)
                # is_flagged=False : le KYC n'a pas détecté l'usurpation — c'est l'essence du scénario
                self._log(step, "TRANSFER", amount, cid, dest, "FAKE_CRED", flagged=False)
                self._tracking["fake_credentials"].append({
                    "step_activation": step, "cid": cid,
                    "dormance_hours": state.get("dormance_h", 0),
                    "amount": amount,
                })
                state["activated"] = True

    # ------------------------------------------------------------------
    # 3.2.4 — Split Deposit
    # ------------------------------------------------------------------
    def _optimal_fragmentation(self, total: float) -> list:
        grid = self.cfg["split_deposit"]["tariff_grid"]

        def commission(amount):
            c = 0.0
            for tier in grid:
                if amount >= tier["threshold"]:
                    c = tier["commission"]
            return c

        best_k, best_gain = 1, commission(total)
        for k in range(2, 6):
            frag = total / k
            gain_k = k * commission(frag)
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
        agent = int(self.gen.choice(self._split_dep_agents))
        client = int(self.gen.choice(self.client_ids))
        available = float(self.engine.balance[agent].item())
        if available < 2000:
            return  # agent vraiment à sec — cas rare grâce au rebalancement toutes les 24h
        total_deposit = float(self.gen.uniform(2000, min(80000.0, available)))
        fragments = self._optimal_fragmentation(total_deposit)

        # Fenêtre temporelle intra-step : T_split ~ U(T_split_min_sec, T_split_max_sec) (§3.2.4)
        # Config : 60s–120s. Les k fragments sont répartis uniformément dans cette fenêtre.
        c_sd = self.cfg["split_deposit"]
        T_split = float(self.gen.uniform(
            c_sd.get("T_split_min_sec", 120),
            c_sd.get("T_split_max_sec", 600),
        ))
        if len(fragments) > 1:
            times_s = [float(v) for v in
                       (T_split * i / (len(fragments) - 1)
                        for i in range(len(fragments)))]
        else:
            times_s = [0.0]

        for frag, t_s in zip(fragments, times_s):
            self._log(step, "CASH_IN", frag, agent, client, "SPLIT_DEP",
                      time_s=t_s)
        self._tracking["split_deposit"].append({
            "step": step, "agent": agent, "client": client,
            "n_frags": len(fragments), "total_amount": total_deposit,
            "fragments": [float(f) for f in fragments],
        })

    # ------------------------------------------------------------------
    # 3.2.5 — Smurfing (Zhdanova et al.)
    # ------------------------------------------------------------------
    def _run_smurfing(self, step: int):
        c = self.cfg["smurfing"]
        smurf_mult = self.probas.get("smurfing_freq_mult", 1.0)
        for net in self.smurf_networks:
            if step < net["next_op_step"]:
                continue

            # next_op_step mis à jour AVANT la vérification du solde (évite busy-retry)
            interval = (c["operation_interval_days"] * 24) / max(smurf_mult, 1e-3)
            net["next_op_step"] = step + max(1, int(self.gen.normal(interval, 24)))

            emitter_balance = float(self.engine.balance[net["emitter"]].item())
            s_seuil = c["S_seuil"]

            # total_X ∝ solde courant de l'émetteur (40–80 %), indépendant de l'échelle FCFA.
            # L'ancienne borne U(500 000, 5 000 000) supposait des soldes > 500 000 FCFA,
            # ce qui n'est jamais atteint avec la distribution initiale calibrée → smurfing
            # ne déclenchait jamais et delta_commission_ratio restait NaN dans featuresLog.
            total_X = emitter_balance * float(self.gen.uniform(0.4, 0.8))
            # Seuil minimal : au moins 2 fragments à ≥ 70 % du seuil COBAC simulé
            frag_min_viable = 2 * 0.70 * s_seuil
            if total_X < frag_min_viable or emitter_balance < frag_min_viable:
                # Adapter le seuil de référence à l'échelle du solde si besoin
                s_seuil = emitter_balance / (2 * 0.70 * 2)  # 4 demi-fragments
                total_X = emitter_balance * float(self.gen.uniform(0.4, 0.8))
            if total_X < 1.0:
                continue

            k = int(self.gen.integers(2, len(net["mules"]) + 1))
            chosen = self.gen.choice(net["mules"], size=min(k, len(net["mules"])), replace=False)
            # x_i ~ U(0.70·S, 0.99·S) indépendants, renormalisés pour respecter total_X
            raw = self.gen.uniform(0.70 * s_seuil, 0.99 * s_seuil, size=len(chosen))
            fractions = raw / raw.sum() * min(total_X, len(chosen) * 0.99 * s_seuil)

            total_emitted = 0.0
            for mule, x_i in zip(chosen, fractions):
                # Émetteur → mule (immédiat)
                self._log(step, "TRANSFER", float(x_i), net["emitter"], int(mule), "SMURFING")
                delta_i = self.gen.uniform(c["delta_min"], c["delta_max"])
                amount_out = float(x_i) * (1 - delta_i)
                total_emitted += float(x_i)
                # Mule → récepteur différé : Δt_mule ~ U(2h, 24h) (eq. 3.2.5)
                delay_mule = int(self.gen.integers(c["delay_mule_min_hours"],
                                                    c["delay_mule_max_hours"] + 1))
                self._pending.append((step + delay_mule, "TRANSFER", amount_out,
                                       int(mule), net["receiver"], "SMURFING", False))
            if total_emitted > 0:
                self._tracking["smurfing"].append({
                    "step": step, "emitter": net["emitter"],
                    "n_mules": len(chosen), "receiver": net["receiver"],
                    "total_x": total_emitted,
                })

    # ------------------------------------------------------------------
    def inject(self, step: int):
        # Transactions différées traitées une seule fois par step
        self._flush_pending(step)

        # Boucle d'injection : _n_inject_per_step tirages indépendants par step.
        # ATO / REFUND / SPLIT_DEP scalent avec n_mules.
        # FAKE_CRED et SMURFING sont des machines d'états — appelés une seule fois par step.
        for _ in range(self._n_inject_per_step):
            if self.gen.uniform() < self.probas["ato"]:
                self._run_ato(step)
            if self.gen.uniform() < self.probas["refund"]:
                self._run_refund(step)
            if self.gen.uniform() < self.probas["split_deposit"]:
                self._run_split_deposit(step)
        # FAKE_CRED : 1 appel/step — pool de 200 comptes dormants avec activation unique
        allow_new = self.gen.uniform() < self.probas["fake_credentials"]
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
    import os
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
        n_tx_target = params.step_target_count[step]
        n_tx_per_client = torch.distributions.Binomial(
            total_count=n_tx_target.clamp(min=0),
            probs=params.client_weight.clamp(0, 1)
        ).sample()
        n_tx_per_client = torch.clamp(n_tx_per_client, max=engine.max_slots).long()

        for slot in range(engine.max_slots):
            slot_mask = n_tx_per_client > slot
            if slot_mask.any():
                engine._run_step_slot(step, slot_mask)

        injector.inject(step)

        if step % 50 == 0:
            print(f"step {step}/{N_STEPS} — {len(engine.log_step)} tx cumulées "
                  f"({sum(engine.log_is_fraud)} frauduleuses)", flush=True)

    df = engine.to_dataframe()
    _raw_out = str(_root / "config" / "rawLog_torch.parquet")
    df.to_parquet(_raw_out, index=False)
    fraud_rate = df["isFraud"].mean()
    print(f"\nTerminé — {len(df)} transactions, device={DEVICE}")
    print(f"Taux de fraude global : {fraud_rate:.3f}")
    print(df.loc[df["isFraud"], "fraudScenario"].value_counts(normalize=True))