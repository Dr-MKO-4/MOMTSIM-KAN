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
        Basée sur le volume légitime (step_target_count tensor) et taux cible global.
        Répartition équitable entre les 5 scénarios (section 3.1.1)."""
        legit_per_step = params.step_target_count.cpu().numpy()
        legit_per_bin = legit_per_step.reshape(self.n_bins, self.bin_size).sum(axis=1)

        fraud_ratio = self.target_mid / (1 - self.target_mid)
        fraud_total_per_bin = legit_per_bin * fraud_ratio

        Dr = np.tile(fraud_total_per_bin / len(self.SCENARIOS), (len(self.SCENARIOS), 1))
        return Dr  # shape (5, n_bins)

    # ------------------------------------------------------------------
    def _run_trial_binned(self, theta: np.ndarray, seed_offset: int) -> np.ndarray:
        """Exécute un run complet et retourne Ds(c,t;θ) : compte de tx frauduleuses
        par scénario (5) x bin (n_bins)."""
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
    def _objective(self, theta: np.ndarray) -> float:
        theta = np.clip(theta, 1e-4, None)
        Ds_list = [self._run_trial_binned(theta, seed_offset=k)
                   for k in range(self.n_seeds_per_eval)]
        Ds_mean = np.mean(Ds_list, axis=0)
        sse = float(np.sum((self._Dr - Ds_mean) ** 2))
        return sse

    # ------------------------------------------------------------------
    def calibrate(self, x0=None, maxiter=25, lr=0.05, spsa_c=0.02, verbose=True) -> dict:
        """SPSA : deux évaluations par itération suffisent à estimer un gradient
        approché, quel que soit le nombre de paramètres — adapté à une simulation
        bruitée et non différentiable (section 3.1.3)."""
        params = self._get_params()
        self._Dr = self._build_target_distribution(params)

        bounds_lo = torch.tensor([1e-4, 1e-4, 1e-4, 1e-4, 0.1])
        bounds_hi = torch.tensor([0.5,  0.5,  0.3,  0.5,  10.0])

        if x0 is None:
            theta = torch.tensor([0.02, 0.02, 0.005, 0.03, 1.0], dtype=torch.float32)
        else:
            theta = torch.tensor(x0, dtype=torch.float32)

        best_theta, best_sse = theta.clone(), float("inf")
        history = []

        for it in range(maxiter):
            delta = torch.tensor(np.random.choice([-1.0, 1.0], size=5), dtype=torch.float32)

            theta_plus  = torch.clamp(theta + spsa_c * delta, bounds_lo, bounds_hi)
            theta_minus = torch.clamp(theta - spsa_c * delta, bounds_lo, bounds_hi)

            sse_plus  = self._objective(theta_plus.numpy())
            sse_minus = self._objective(theta_minus.numpy())

            grad_hat = torch.tensor(
                (sse_plus - sse_minus) / (2 * spsa_c * delta.numpy()), dtype=torch.float32)

            theta = torch.clamp(theta - lr * grad_hat, bounds_lo, bounds_hi)

            sse_current = self._objective(theta.numpy())
            history.append({"iter": it, "sse": sse_current, "theta": theta.tolist()})
            if verbose:
                print(f"[iter {it}] theta={[round(v,4) for v in theta.tolist()]} "
                      f"SSE={sse_current:,.1f}", flush=True)

            if sse_current < best_sse:
                best_sse, best_theta = sse_current, theta.clone()

        theta_star = best_theta.numpy()
        probas_final = {
            "ato": float(theta_star[0]), "refund": float(theta_star[1]),
            "fake_credentials": float(theta_star[2]), "split_deposit": float(theta_star[3]),
            "smurfing_freq_mult": float(theta_star[4]),
        }
        return {"probas": probas_final, "sse_final": float(best_sse),
                "converged": best_sse < float("inf"), "history": history}


if __name__ == "__main__":
    calib = SSEFraudCalibrator(
        param_dir="./paramFiles", fraud_config_path="./fraudScenariosConfig.json",
        seed=1000, n_clients=500, n_merchants=100, n_banks=10, n_mules=30,
        target_mid=0.23, n_steps=720, n_bins=30, n_seeds_per_eval=3)

    result = calib.calibrate(maxiter=25)
    print("\n=== Résultat calibration SSE ===")
    print("probas :", result["probas"])
    print("SSE final :", result["sse_final"])

    with open("calibrated_probas.json", "w", encoding="utf-8") as f:
        json.dump(result["probas"], f, indent=2)
    print("Sauvegardé dans calibrated_probas.json")
