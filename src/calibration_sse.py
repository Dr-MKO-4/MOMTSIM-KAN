"""
calibration_sse.py — Calibration SSE/SPSA (section 3.1.3 du mémoire).
Minimise θ* = argmin Σ_c Σ_t (Dr(c,t) - Ds(c,t;θ))² par SPSA.
Utilise le pipeline torch (TorchParameters + TorchMoMTSimEngine + TorchFraudInjector).
"""

import numpy as np
import torch
import json
from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector


class SSEFraudCalibrator:
    SCENARIOS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing"]
    SCENARIO_LABELS = {"ato": "ATO", "refund": "REFUND", "fake_credentials": "FAKE_CRED",
                        "split_deposit": "SPLIT_DEP", "smurfing": "SMURFING"}

    def __init__(self, param_dir: str, fraud_config_path: str, seed: int = 1000,
                 n_clients=500, n_merchants=100, n_banks=10, n_mules=30,
                 target_mid=0.23, n_steps=720, n_bins=30, n_seeds_per_eval=3,
                 max_slots_per_step=6):
        self.param_dir = param_dir
        self.fraud_config_path = fraud_config_path
        self.seed = seed
        self.n_clients = n_clients
        self.n_merchants = n_merchants
        self.n_banks = n_banks
        self.n_mules = n_mules
        self.target_mid = target_mid
        self.n_steps = n_steps
        self.n_bins = n_bins
        self.bin_size = n_steps // n_bins
        self.n_seeds_per_eval = n_seeds_per_eval
        self.max_slots_per_step = max_slots_per_step

        self._Dr = None
        self._Dr_scale = 1.0
        self._params_cache = None

    # ------------------------------------------------------------------
    def _get_params(self) -> TorchParameters:
        if self._params_cache is None:
            self._params_cache = TorchParameters(
                self.param_dir, self.fraud_config_path,
                n_clients=self.n_clients, seed=self.seed)
        return self._params_cache

    # ------------------------------------------------------------------
    def _build_target_distribution(self, params: TorchParameters) -> np.ndarray:
        """Dr(c,t) : distribution cible par scénario (5) x bin (n_bins).
        Les 5 scénarios se partagent équitablement le taux cible (section 3.1.1).
        FAKE_CRED ne peut atteindre sa cible (pool=200, dormance 7-30j) : le SPSA
        pousse p_fake_cred vers sa borne haute (0.3) pour maximiser son output — le
        scénario reste actif et contribue à ~0.3 activations/step en régime permanent."""
        legit_per_step = params.step_target_count.cpu().numpy()
        n_steps_used = self.n_bins * self.bin_size
        n_repeats = (n_steps_used + len(legit_per_step) - 1) // len(legit_per_step)
        legit_per_step = np.tile(legit_per_step, n_repeats)[:n_steps_used]
        legit_per_bin = legit_per_step.reshape(self.n_bins, self.bin_size).sum(axis=1)

        fraud_ratio = self.target_mid / (1 - self.target_mid)
        fraud_total_per_bin = legit_per_bin * fraud_ratio

        # 5 scénarios actifs — répartition équitable
        Dr = np.zeros((len(self.SCENARIOS), self.n_bins))
        for i in range(len(self.SCENARIOS)):
            Dr[i, :] = fraud_total_per_bin / len(self.SCENARIOS)
        return Dr  # shape (5, n_bins)

    # ------------------------------------------------------------------
    def _run_trial_binned(self, theta: np.ndarray, seed_offset: int,
                          cancel_check=None) -> "np.ndarray | None":
        """Exécute un run complet et retourne Ds(c,t;θ) : compte de tx frauduleuses
        par scénario (5) x bin (n_bins). Retourne None si annulé."""
        probas = {
            "ato": float(theta[0]), "refund": float(theta[1]),
            "fake_credentials": float(theta[2]), "split_deposit": float(theta[3]),
            "smurfing_freq_mult": float(theta[4]),
        }

        params = self._get_params()
        engine = TorchMoMTSimEngine(
            params, n_clients=self.n_clients, n_merchants=self.n_merchants,
            n_banks=self.n_banks, n_mules=self.n_mules,
            max_slots_per_step=self.max_slots_per_step, seed=self.seed + seed_offset)
        injector = TorchFraudInjector(engine, params, fraud_probas=probas,
                                       seed=self.seed + seed_offset)

        for step in range(self.n_steps):
            if cancel_check and cancel_check():
                return None
            n_tx_target = params.step_target_count[step % len(params.step_target_count)]
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

        Ds = np.zeros((len(self.SCENARIOS), self.n_bins))
        if not engine.log_step:
            return Ds

        steps_arr = np.array(engine.log_step)
        is_fraud_arr = np.array(engine.log_is_fraud)
        scenario_arr = np.array([s if s is not None else "" for s in engine.log_scenario])

        fraud_mask = is_fraud_arr
        if not fraud_mask.any():
            return Ds

        bins = np.clip(steps_arr[fraud_mask] // self.bin_size, 0, self.n_bins - 1)
        scenarios_f = scenario_arr[fraud_mask]

        for i, key in enumerate(self.SCENARIOS):
            label = self.SCENARIO_LABELS[key]
            sel = scenarios_f == label
            if sel.any():
                counts = np.bincount(bins[sel], minlength=self.n_bins)
                Ds[i, :] = counts[:self.n_bins]
        return Ds

    # ------------------------------------------------------------------
    def _objective(self, theta: np.ndarray, cancel_check=None) -> "float | None":
        theta = np.clip(theta, 1e-4, None)
        Ds_list = []
        for k in range(self.n_seeds_per_eval):
            ds = self._run_trial_binned(theta, seed_offset=k, cancel_check=cancel_check)
            if ds is None:
                return None  # annulé pendant un trial
            Ds_list.append(ds)
        Ds_mean = np.mean(Ds_list, axis=0)
        # Normalisation par Dr.sum() — gradient invariant à l'échelle du multiplicateur k = n_mules.
        # Sans normalisation, le gradient est O(k² × Dr²) ≈ 10^10 avec k=300,
        # ce qui rend lr=0.05 inutilisable (step >> espace des paramètres).
        sse = float(np.sum(((self._Dr - Ds_mean) / self._Dr_scale) ** 2))
        return sse

    # ------------------------------------------------------------------
    def calibrate(self, x0=None, maxiter=25, lr=0.05, spsa_c=0.02, verbose=True, cancel_check=None) -> dict:
        """SPSA : deux évaluations par itération suffisent à estimer un gradient
        approché, quel que soit le nombre de paramètres — adapté à une simulation
        bruitée et non différentiable (section 3.1.3)."""
        params = self._get_params()
        self._Dr = self._build_target_distribution(params)
        # Normalisation : sum(Dr) sur tous les scénarios × bins (section 3.1.4)
        self._Dr_scale = max(1.0, float(self._Dr.sum()))

        bounds_lo = torch.tensor([0.02, 0.02, 1e-4, 0.02, 0.5])
        bounds_hi = torch.tensor([0.5,  0.5,  0.3,  0.5,  10.0])

        if x0 is None:
            # Estimation analytique : p* ≈ Dr_step / (k_eff × avg_tx_par_événement)
            # Ce point de départ élimine la phase de warmup du SPSA.
            # k_eff = n_mules pour ATO/REFUND/SPLIT_DEP (appelés k fois/step dans inject()).
            # k_eff = 1 pour FAKE_CRED (appelé 1 fois/step, pool de 200 comptes dormants).
            Dr_per_step = float(self._Dr.mean()) / self.bin_size
            k = max(1, self.n_mules)
            k_eff   = [k,   k,   1.0, k  ]  # ATO, REFUND, FAKE_CRED, SPLIT_DEP
            avg_tx  = [3.0, 1.5, 2.0, 6.0]  # tx moyennes par événement (SPLIT_DEP ~6 fragments/appel)
            p_init = [
                float(np.clip(Dr_per_step / max(1.0, k_eff[i] * avg_tx[i]),
                              float(bounds_lo[i]), float(bounds_hi[i])))
                for i in range(4)
            ]
            p_init.append(2.0)  # smurfing_freq_mult : valeur initiale raisonnable
            theta = torch.clamp(
                torch.tensor(p_init, dtype=torch.float32), bounds_lo, bounds_hi)
        else:
            theta = torch.tensor(x0, dtype=torch.float32)

        best_theta, best_sse = theta.clone(), float("inf")
        history = []

        for it in range(maxiter):
            if cancel_check and cancel_check():
                break
            delta = torch.tensor(np.random.choice([-1.0, 1.0], size=5), dtype=torch.float32)

            theta_plus  = torch.clamp(theta + spsa_c * delta, bounds_lo, bounds_hi)
            theta_minus = torch.clamp(theta - spsa_c * delta, bounds_lo, bounds_hi)

            sse_plus  = self._objective(theta_plus.numpy(),  cancel_check=cancel_check)
            if sse_plus is None: break
            sse_minus = self._objective(theta_minus.numpy(), cancel_check=cancel_check)
            if sse_minus is None: break

            grad_hat = torch.tensor(
                (sse_plus - sse_minus) / (2 * spsa_c * delta.numpy()), dtype=torch.float32)

            theta = torch.clamp(theta - lr * grad_hat, bounds_lo, bounds_hi)

            sse_current = self._objective(theta.numpy(), cancel_check=cancel_check)
            if sse_current is None: break
            history.append({"iter": it, "sse": sse_current, "theta": theta.tolist()})
            if verbose:
                print(f"[iter {it}] theta={[round(v,4) for v in theta.tolist()]} "
                      f"SSE={sse_current:.6f}", flush=True)

            if sse_current < best_sse:
                best_sse, best_theta = sse_current, theta.clone()

        theta_star = best_theta.numpy()
        probas_final = {
            "ato": float(theta_star[0]), "refund": float(theta_star[1]),
            "fake_credentials": float(theta_star[2]), "split_deposit": float(theta_star[3]),
            "smurfing_freq_mult": float(theta_star[4]),
        }
        # Convergé si le SSE normalisé < 1.0  (NRMSE moyen < ~8 % par cellule)
        converged = float(best_sse) < 1.0
        return {"probas": probas_final, "sse_final": float(best_sse),
                "converged": converged, "history": history}


if __name__ == "__main__":
    from pathlib import Path as _Path
    _root = _Path(__file__).parent.parent

    calib = SSEFraudCalibrator(
        param_dir=str(_root / "config" / "paramFiles"),
        fraud_config_path=str(_root / "config" / "fraudScenariosConfig.json"),
        seed=1000, n_clients=500, n_merchants=100, n_banks=10, n_mules=300,
        target_mid=0.23, n_steps=720, n_bins=30, n_seeds_per_eval=3)

    result = calib.calibrate(maxiter=25)
    print("\n=== Résultat calibration SSE ===")
    print("probas :", result["probas"])
    print("SSE final :", result["sse_final"])

    _out = str(_root / "config" / "calibrated_probas.json")
    with open(_out, "w", encoding="utf-8") as f:
        json.dump(result["probas"], f, indent=2)
    print(f"Sauvegardé dans {_out}")
