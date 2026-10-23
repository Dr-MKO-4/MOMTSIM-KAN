"""
calibration_sse.py  Calibration SSE/SPSA (section 3.1.6 du mémoire).
Minimise θ* = argmin Σ_c Σ_t (Dr(c,t) - Ds(c,t;θ))² par SPSA.
Utilise le pipeline torch (TorchParameters + TorchMoMTSimEngine + TorchFraudInjector).

Exécution :
  - chaque simulation tourne en mode compteurs (aucune ligne de journal gardée) ;
  - les simulations d'une itération sont indépendantes et tournent en parallèle
    dans des processus séparés (n_workers) ;
  - l'évaluation de θ_{k+1} et celles de θ_{k+1} ± c·δ_{k+1} ne dépendent que de
    θ_{k+1} : elles sont lancées dans le même lot (9 simulations par lot avec
    K = 3), sans changer l'algorithme ;
  - un point de reprise est écrit après chaque itération.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from pathlib import Path

import numpy as np

SCENARIOS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing"]
THETA_KEYS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing_freq_mult"]
SCENARIO_LABELS = {"ato": "ATO", "refund": "REFUND", "fake_credentials": "FAKE_CRED",
                   "split_deposit": "SPLIT_DEP", "smurfing": "SMURFING"}
# Bornes de Θ (section 3.1.6)
BOUNDS_LO = np.array([0.02, 0.02, 1e-4, 0.02, 0.5])
BOUNDS_HI = np.array([0.5, 0.5, 0.3, 0.5, 10.0])


def theta_to_probas(theta) -> dict:
    return {k: float(v) for k, v in zip(THETA_KEYS, theta)}


def file_fingerprint(paths) -> str:
    """Empreinte des fichiers dont dépend un résultat de calibration."""
    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        files = sorted(p.glob("*.csv")) if p.is_dir() else [p]
        for f in files:
            if f.exists():
                h.update(f.name.encode())
                h.update(f.read_bytes())
    return h.hexdigest()[:16]


# ── travail d'une simulation (exécuté dans un processus de travail) ──────────

_WORKER = {"params": {}, "queue": None, "cancel": None}


def _init_worker(queue, cancel_event, n_threads: int = 1):
    import torch
    torch.set_num_threads(max(1, n_threads))
    _WORKER["queue"] = queue
    _WORKER["cancel"] = cancel_event


def _get_params(spec: dict):
    from momtsim_torch import TorchParameters
    key = (spec["param_dir"], spec["fraud_config_path"], spec["n_clients"],
           spec["pop_seed"], spec["volume_scale"])
    cache = _WORKER["params"]
    if key not in cache:
        cache.clear()
        cache[key] = TorchParameters(spec["param_dir"], spec["fraud_config_path"],
                                     n_clients=spec["n_clients"], seed=spec["pop_seed"],
                                     volume_scale=spec["volume_scale"])
    return cache[key]


def simulate_counts(spec: dict, report=None, cancelled=None) -> "dict | None":
    """Une simulation complète en mode compteurs. Retourne Ds (scénarios x bins),
    le volume légitime par bin et les totaux, ou None si annulée."""
    from momtsim_torch import TorchMoMTSimEngine, TorchFraudInjector
    queue, cancel_ev = _WORKER["queue"], _WORKER["cancel"]
    if report is None and queue is not None:
        report = lambda tag, s: queue.put((tag, s))
    if cancelled is None and cancel_ev is not None:
        cancelled = cancel_ev.is_set

    params = _get_params(spec)
    seed = spec["seed"]
    engine = TorchMoMTSimEngine(
        params, n_clients=spec["n_clients"], n_merchants=spec["n_merchants"],
        n_banks=spec["n_banks"], n_mules=spec["n_mules"],
        max_slots_per_step=spec["max_slots"], seed=seed, keep_log=False)
    injector = TorchFraudInjector(engine, params, fraud_probas=theta_to_probas(spec["theta"]),
                                  seed=seed, volume_follow=spec["volume_follow"])
    n_steps, n_bins = spec["n_steps"], spec["n_bins"]
    every = max(1, n_steps // 30)
    for step in range(n_steps):
        engine.simulate_step(step, injector)
        if (step + 1) % every == 0 or step + 1 == n_steps:
            if cancelled is not None and cancelled():
                return None
            if report is not None:
                report(spec["tag"], step + 1)

    fraud = engine.fraud_counts_by_step(n_steps)          # (5, n_steps)
    legit = engine.legit_counts_by_step(n_steps)          # (n_steps,)
    bin_size = n_steps // n_bins
    bins = np.minimum(np.arange(n_steps) // bin_size, n_bins - 1)
    Ds = np.zeros((len(SCENARIOS), n_bins))
    for i in range(len(SCENARIOS)):
        Ds[i] = np.bincount(bins, weights=fraud[i], minlength=n_bins)[:n_bins]
    legit_bins = np.bincount(bins, weights=legit, minlength=n_bins)[:n_bins]
    return {"tag": spec["tag"], "Ds": Ds, "legit_bins": legit_bins,
            "fraud_total": float(fraud.sum()), "legit_total": float(legit.sum())}


def default_workers() -> int:
    env = os.environ.get("MOMTSIM_WORKERS")
    if env:
        return max(1, int(env))
    if getattr(sys, "frozen", False):
        return 1   # application empaquetée : pas de sous-processus par défaut
    return max(1, min(9, (os.cpu_count() or 2) - 1))


class SSEFraudCalibrator:
    SCENARIOS = SCENARIOS
    SCENARIO_LABELS = SCENARIO_LABELS

    def __init__(self, param_dir: str, fraud_config_path: str, seed: int = 1000,
                 n_clients=2000, n_merchants=200, n_banks=8, n_mules=800,
                 target_mid=0.23, n_steps=720, n_bins=30, n_seeds_per_eval=3,
                 max_slots_per_step=50, volume_scale: float = 1.0,
                 volume_follow: bool = False, n_workers: int | None = None):
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
        self.volume_scale = float(volume_scale)
        self.volume_follow = bool(volume_follow)
        self.n_workers = default_workers() if not n_workers else max(1, int(n_workers))

        self._Dr = None
        self._Dr_scale = 1.0
        self._pool = None
        self._queue = None
        self._cancel_ev = None
        self._progress_cb = None
        self._cancel_check = None

    #
    def _build_target_distribution(self) -> np.ndarray:
        """Dr(c,t) : distribution cible par scénario (5) x bin (n_bins).
        Les 5 scénarios se partagent équitablement le taux cible (section 3.1.6) :
        Dr(c,t) = N_lég(t)·r / ((1-r)·5), N_lég(t) = somme du profil horaire sur le bin."""
        from momtsim_torch import TorchParameters
        params = TorchParameters(self.param_dir, self.fraud_config_path,
                                 n_clients=min(self.n_clients, 10), seed=self.seed,
                                 volume_scale=self.volume_scale)
        legit_per_step = params.step_target_np
        n_steps_used = self.n_bins * self.bin_size
        n_repeats = (n_steps_used + len(legit_per_step) - 1) // len(legit_per_step)
        legit_per_step = np.tile(legit_per_step, n_repeats)[:n_steps_used]
        legit_per_bin = legit_per_step.reshape(self.n_bins, self.bin_size).sum(axis=1)

        fraud_ratio = self.target_mid / (1 - self.target_mid)
        fraud_total_per_bin = legit_per_bin * fraud_ratio
        return np.tile(fraud_total_per_bin / len(SCENARIOS), (len(SCENARIOS), 1))  # (5, n_bins)

    # ── exécution d'un lot de simulations ────────────────────────────────────
    def _spec(self, theta, k: int, tag: str) -> dict:
        return {
            "tag": tag, "theta": [float(v) for v in theta], "seed": self.seed + k,
            "pop_seed": self.seed, "param_dir": self.param_dir,
            "fraud_config_path": self.fraud_config_path,
            "n_clients": self.n_clients, "n_merchants": self.n_merchants,
            "n_banks": self.n_banks, "n_mules": self.n_mules,
            "max_slots": self.max_slots_per_step, "n_steps": self.n_steps,
            "n_bins": self.n_bins, "volume_scale": self.volume_scale,
            "volume_follow": self.volume_follow,
        }

    def _jobs(self, theta, prefix: str) -> list:
        return [self._spec(theta, k, f"{prefix}#{k}") for k in range(self.n_seeds_per_eval)]

    def _open_pool(self):
        if self.n_workers <= 1 or self._pool is not None:
            return
        ctx = mp.get_context("spawn")
        self._queue = ctx.Queue()
        self._cancel_ev = ctx.Event()
        # Les processus de travail importent calibration_sse et momtsim_torch depuis src/
        src = str(Path(__file__).parent)
        os.environ["PYTHONPATH"] = src + os.pathsep + os.environ.get("PYTHONPATH", "")
        # Simulations de calibration : nombreuses et petites, donc un coeur CPU par
        # processus est le plus efficace (pas de partage d'un GPU entre 9 processus)
        self._prev_device = os.environ.get("MOMTSIM_DEVICE")
        os.environ["MOMTSIM_DEVICE"] = "cpu"
        self._pool = ProcessPoolExecutor(max_workers=self.n_workers, mp_context=ctx,
                                         initializer=_init_worker,
                                         initargs=(self._queue, self._cancel_ev, 1))

    def close(self):
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None
            if getattr(self, "_prev_device", None) is None:
                os.environ.pop("MOMTSIM_DEVICE", None)
            else:
                os.environ["MOMTSIM_DEVICE"] = self._prev_device

    def _cancelled(self) -> bool:
        return bool(self._cancel_check and self._cancel_check())

    def _run_batch(self, specs: list, label: str) -> "dict | None":
        """Exécute les simulations d'un lot ; renvoie {tag: résultat} ou None si annulé."""
        progress = {s["tag"]: 0 for s in specs}

        def emit():
            if self._progress_cb is not None:
                self._progress_cb(sum(progress.values()), label)

        if self._pool is None:
            results = {}
            for s in specs:
                def rep(tag, st):
                    progress[tag] = st
                    emit()
                r = simulate_counts(s, report=rep, cancelled=self._cancelled)
                if r is None:
                    return None
                results[r["tag"]] = r
            return results

        pending = {self._pool.submit(simulate_counts, s) for s in specs}
        results = {}
        while pending:
            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            while True:
                try:
                    tag, st = self._queue.get_nowait()
                except Exception:
                    break
                if tag in progress:
                    progress[tag] = max(progress[tag], st)
            for f in done:
                r = f.result()
                if r is None:
                    return None
                results[r["tag"]] = r
                progress[r["tag"]] = self.n_steps
            emit()
            if self._cancelled():
                self._cancel_ev.set()
                for f in pending:
                    f.cancel()
                return None
        return results

    def _objective(self, results: dict, prefix: str) -> dict:
        """sse(θ) = Σ ((Dr - D̄s) / ΣDr)², avec D̄s moyen sur les K réplications."""
        reps = [results[f"{prefix}#{k}"] for k in range(self.n_seeds_per_eval)]
        Ds_mean = np.mean([r["Ds"] for r in reps], axis=0)
        legit_bins = np.mean([r["legit_bins"] for r in reps], axis=0)
        fraud_total = float(np.mean([r["fraud_total"] for r in reps]))
        legit_total = float(np.mean([r["legit_total"] for r in reps]))
        # Normalisation par ΣDr : gradient indépendant de l'échelle de la population
        sse = float(np.sum(((self._Dr - Ds_mean) / self._Dr_scale) ** 2))
        denom = fraud_total + legit_total
        return {"sse": sse, "Ds": Ds_mean, "legit_bins": legit_bins,
                "fraud_rate": fraud_total / denom if denom > 0 else 0.0,
                "fraud_total": fraud_total, "legit_total": legit_total}

    #
    def analytic_x0(self) -> np.ndarray:
        """Estimation analytique : p* ≈ Dr_step / (k_eff × avg_tx_par_événement).
        k_eff = n_mules pour ATO/REFUND/SPLIT_DEP (tirés n_mules fois/step),
        k_eff = 1 pour FAKE_CRED (un nouveau compte dormant au plus par step)."""
        Dr_per_step = float(self._Dr.mean()) / self.bin_size
        k = max(1, self.n_mules)
        k_eff = [k, k, 1.0, k]          # ATO, REFUND, FAKE_CRED, SPLIT_DEP
        avg_tx = [3.0, 1.5, 2.0, 6.0]   # tx moyennes par événement
        p_init = [float(np.clip(Dr_per_step / max(1.0, k_eff[i] * avg_tx[i]),
                                BOUNDS_LO[i], BOUNDS_HI[i])) for i in range(4)]
        p_init.append(2.0)              # smurfing_freq_mult
        return np.clip(np.array(p_init), BOUNDS_LO, BOUNDS_HI)

    def calibrate(self, x0=None, maxiter=30, lr=0.05, spsa_c=0.02, verbose=True,
                  cancel_check=None, progress_cb=None, gain_schedule: str = "constant",
                  checkpoint_path: str | None = None, resume: bool = False,
                  iteration_cb=None) -> dict:
        """SPSA (Spall, 1992) : deux évaluations par itération suffisent à estimer un
        gradient approché, quel que soit le nombre de paramètres (section 3.1.6).

        progress_cb(frac, message, info) : progression globale dans [0, 1], info
            contient elapsed_s, eta_s, sims_done, sims_total, iteration, maxiter.
        iteration_cb(entry) : appelé à chaque itération évaluée (historique en direct).
        gain_schedule : "constant" (a, c fixes, mémoire) ou "spall" (a_k, c_k décroissants).
        """
        self._cancel_check = cancel_check
        self._Dr = self._build_target_distribution()
        self._Dr_scale = max(1.0, float(self._Dr.sum()))
        sse_zero = float(np.sum((self._Dr / self._Dr_scale) ** 2))   # SSE d'une sortie sans fraude
        K = self.n_seeds_per_eval
        t_start = time.time()

        theta0 = self.analytic_x0() if x0 is None else np.clip(np.asarray(x0, float), BOUNDS_LO, BOUNDS_HI)
        rng = np.random.default_rng(self.seed)
        state = {"it": 0, "theta": theta0.tolist(), "best_theta": theta0.tolist(),
                 "best_sse": None, "history": [], "theta0": theta0.tolist(),
                 "sse_theta0": None, "eval_theta0": None, "best_eval": None, "rng": None}
        ckpt = Path(checkpoint_path) if checkpoint_path else None
        signature = self._signature(maxiter, lr, spsa_c, gain_schedule, theta0)
        if resume and ckpt is not None and ckpt.exists():
            saved = json.loads(ckpt.read_text(encoding="utf-8"))
            if saved.get("signature") == signature:
                state.update(saved["state"])
                rng.bit_generator.state = state["rng"]
                theta0 = np.array(state["theta0"])
                if verbose:
                    print(f"[REPRISE] reprise à l'itération {state['it']}/{maxiter}", flush=True)
            elif verbose:
                print("[REPRISE] le point de reprise vient d'une autre configuration : ignoré",
                      flush=True)

        # Comptabilité de la progression (en simulations complètes)
        total_sims = 3 * K * maxiter + K                     # + évaluation de θ0
        done_at_start = 3 * K * state["it"] + (K if state["sse_theta0"] is not None else 0)
        done_before_batch = [done_at_start]

        def report(done_steps, label):
            if progress_cb is None:
                return
            done_sims = done_before_batch[0] + done_steps / self.n_steps
            elapsed = time.time() - t_start
            run = done_sims - done_at_start
            eta = elapsed / run * (total_sims - done_sims) if run > 0.05 else None
            progress_cb(min(1.0, done_sims / total_sims), label,
                        {"elapsed_s": elapsed, "eta_s": eta, "sims_done": done_sims,
                         "sims_total": total_sims, "iteration": state["it"], "maxiter": maxiter})
        self._progress_cb = report

        self._open_pool()
        theta = np.array(state["theta"])
        best_theta = np.array(state["best_theta"])
        best_sse = state["best_sse"] if state["best_sse"] is not None else float("inf")
        history = state["history"]
        need_current = state["it"] > 0          # sse(θ_k) pas encore évaluée
        cancelled = False
        try:
            k = state["it"]
            while k <= maxiter:
                last = k == maxiter
                if last and not need_current:
                    break
                a_k, c_k = self._gains(k, maxiter, lr, spsa_c, gain_schedule)
                delta = None if last else rng.choice([-1.0, 1.0], size=5)
                specs = []
                if state["sse_theta0"] is None:
                    specs += self._jobs(theta0, "theta0")
                if need_current:
                    specs += self._jobs(theta, "cur")
                if not last:
                    theta_plus = np.clip(theta + c_k * delta, BOUNDS_LO, BOUNDS_HI)
                    theta_minus = np.clip(theta - c_k * delta, BOUNDS_LO, BOUNDS_HI)
                    specs += self._jobs(theta_plus, "plus") + self._jobs(theta_minus, "minus")
                label = (f"Itération {min(k + 1, maxiter)}/{maxiter} : {len(specs)} simulations "
                         f"({min(self.n_workers, len(specs))} en parallèle)")
                results = self._run_batch(specs, label)
                if results is None:
                    cancelled = True
                    break
                done_before_batch[0] += len(specs)

                if state["sse_theta0"] is None:
                    ev0 = self._objective(results, "theta0")
                    state["sse_theta0"] = ev0["sse"]
                    state["eval_theta0"] = self._eval_summary(ev0)
                    if verbose:
                        print(f"[theta0] SSE={ev0['sse']:.6f} fraude={ev0['fraud_rate']:.3f} "
                              f"(SSE sans aucune fraude : {sse_zero:.6f})", flush=True)
                if need_current:
                    ev = self._objective(results, "cur")
                    entry = history[-1]
                    entry.update({"sse": ev["sse"], "fraud_rate": ev["fraud_rate"],
                                  "elapsed_s": time.time() - t_start})
                    if ev["sse"] < best_sse:
                        best_sse, best_theta = ev["sse"], theta.copy()
                        state["best_eval"] = self._eval_summary(ev)
                    entry["best_sse"] = best_sse
                    if verbose:
                        print(f"[iter {entry['iter']}] theta={[round(v, 4) for v in theta.tolist()]} "
                              f"SSE={ev['sse']:.6f} fraude={ev['fraud_rate']:.3f}", flush=True)
                    if iteration_cb is not None:
                        iteration_cb(dict(entry))
                if last:
                    break

                sse_plus = self._objective(results, "plus")["sse"]
                sse_minus = self._objective(results, "minus")["sse"]
                grad_hat = (sse_plus - sse_minus) / (2 * c_k * delta)
                theta = np.clip(theta - a_k * grad_hat, BOUNDS_LO, BOUNDS_HI)
                history.append({"iter": k, "sse": None, "theta": theta.tolist(),
                                "grad": grad_hat.tolist(), "sse_plus": sse_plus,
                                "sse_minus": sse_minus, "a_k": a_k, "c_k": c_k})
                need_current = True
                k += 1
                state.update({"it": k, "theta": theta.tolist(), "best_theta": best_theta.tolist(),
                              "best_sse": None if best_sse == float("inf") else best_sse,
                              "history": history, "rng": rng.bit_generator.state})
                if ckpt is not None:
                    self._write_checkpoint(ckpt, signature, state)
        finally:
            self.close()

        history = [h for h in history if h.get("sse") is not None]
        if best_sse == float("inf") and state["sse_theta0"] is not None:
            best_sse, best_theta = state["sse_theta0"], theta0.copy()
            state["best_eval"] = state.get("eval_theta0")
        best_sse = float(best_sse) if best_sse != float("inf") else float("nan")

        from calibration_report import interpret_calibration
        result = {
            "probas": theta_to_probas(best_theta),
            "sse_final": best_sse,
            "history": history,
            "cancelled": cancelled,
            "theta0": theta0.tolist(),
            "sse_theta0": state["sse_theta0"],
            "sse_zero_fraud": sse_zero,
            "Dr": self._Dr.tolist(),
            "best_eval": state.get("best_eval"),
            "eval_theta0": state.get("eval_theta0"),
            "bounds_lo": BOUNDS_LO.tolist(), "bounds_hi": BOUNDS_HI.tolist(),
            "config": self.config_dict(maxiter=maxiter, lr=lr, spsa_c=spsa_c,
                                       gain_schedule=gain_schedule),
            "fingerprint": self.fingerprint(),
            "elapsed_s": time.time() - t_start,
            "n_workers": self.n_workers,
        }
        verdict = interpret_calibration(result, fraud_config_path=self.fraud_config_path)
        result["converged"] = verdict["converged"]
        result["verdict"] = verdict
        return result

    #
    @staticmethod
    def _gains(k, maxiter, a, c, schedule):
        if schedule == "spall":
            # Suites de gains standard de Spall (1998) : α = 0,602, γ = 0,101, A = 10 % de K_max
            A = 0.1 * maxiter
            return a / (k + 1 + A) ** 0.602, c / (k + 1) ** 0.101
        return a, c

    @staticmethod
    def _eval_summary(ev: dict) -> dict:
        return {"sse": ev["sse"], "Ds": np.asarray(ev["Ds"]).tolist(),
                "legit_bins": np.asarray(ev["legit_bins"]).tolist(),
                "fraud_rate": ev["fraud_rate"], "fraud_total": ev["fraud_total"],
                "legit_total": ev["legit_total"]}

    def config_dict(self, **extra) -> dict:
        d = {"n_clients": self.n_clients, "n_merchants": self.n_merchants,
             "n_banks": self.n_banks, "n_mules": self.n_mules,
             "max_slots": self.max_slots_per_step, "target_mid": self.target_mid,
             "n_steps": self.n_steps, "n_bins": self.n_bins,
             "n_seeds_per_eval": self.n_seeds_per_eval, "seed": self.seed,
             "volume_scale": self.volume_scale, "volume_follow": self.volume_follow}
        d.update(extra)
        return d

    def fingerprint(self) -> dict:
        src = Path(__file__).parent
        return {"fraud_config": file_fingerprint([self.fraud_config_path]),
                "param_files": file_fingerprint([self.param_dir]),
                "engine": file_fingerprint([src / "momtsim_torch.py"]),
                "param_dir": str(self.param_dir)}

    def _signature(self, maxiter, lr, spsa_c, gain_schedule, theta0) -> str:
        cfg = self.config_dict(maxiter=maxiter, lr=lr, spsa_c=spsa_c, gain_schedule=gain_schedule)
        cfg["fingerprint"] = {k: v for k, v in self.fingerprint().items() if k != "param_dir"}
        cfg["theta0"] = [round(float(v), 10) for v in theta0]
        return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]

    @staticmethod
    def _write_checkpoint(path: Path, signature: str, state: dict):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"signature": signature, "state": state}, default=float),
                       encoding="utf-8")
        os.replace(tmp, path)


if __name__ == "__main__":
    print("Utiliser : python momtsim_cli.py calibrer   (depuis le dossier MOMTSIM)")
