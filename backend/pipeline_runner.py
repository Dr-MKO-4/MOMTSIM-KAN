"""
backend/pipeline_runner.py — Exécution asynchrone du pipeline MoMTSim-KAN.
Utilise BackgroundTasks FastAPI + store in-memory (pas de Celery/Redis).
"""

from __future__ import annotations
import sys
import os
import uuid
import traceback
import threading
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import torch

# Ajouter le répertoire parent au path pour importer momtsim_torch, features, viz
sys.path.insert(0, str(Path(__file__).parent.parent))

from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector
from features import FeatureEngineer
from viz import TopologyValidator, MoMTSimVisualizer, FEATURES_12
from .schemas import SimulationParams, CalibrationParams

PARAM_DIR = str(Path(__file__).parent.parent / "paramFiles")
FRAUD_CONFIG_PATH = str(Path(__file__).parent.parent / "fraudScenariosConfig.json")
OUTPUT_DIR = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Store in-memory des jobs
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _new_job() -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "pending",
            "progress": 0,
            "message": "En file d'attente…",
            "result": None,
            "error": None,
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return list(_jobs.values())


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        _jobs[job_id].update(kwargs)


def _plotly_html(fig) -> str:
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"responsive": True})


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _run_simulation_bg(job_id: str, p: SimulationParams) -> None:
    try:
        _update(job_id, status="running", message="Chargement des paramètres…", progress=2)

        params = TorchParameters(PARAM_DIR, FRAUD_CONFIG_PATH,
                                 n_clients=p.n_clients, seed=p.seed)
        engine = TorchMoMTSimEngine(
            params, n_clients=p.n_clients, n_merchants=p.n_merchants,
            n_banks=p.n_banks, n_mules=p.n_mules,
            max_slots_per_step=p.max_slots, seed=p.seed)
        injector = TorchFraudInjector(engine, params,
                                      fraud_probas=p.fraud_probas, seed=p.seed)

        _update(job_id, message="Simulation en cours…", progress=5)

        for step in range(p.n_steps):
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

            if step % 30 == 0:
                pct = 5 + int(85 * step / p.n_steps)
                _update(job_id, progress=pct,
                        message=f"Step {step}/{p.n_steps} — {len(engine.log_step)} tx")

        _update(job_id, progress=90, message="Sauvegarde du rawLog…")
        df = engine.to_dataframe()
        csv_path = str(OUTPUT_DIR / "rawLog_torch.csv")
        df.to_csv(csv_path, index=False)

        fraud_rate = float(df["isFraud"].mean())
        by_scenario: dict[str, float] = {}
        if df["isFraud"].any():
            vc = df.loc[df["isFraud"], "fraudScenario"].value_counts(normalize=True)
            by_scenario = {k: float(v) for k, v in vc.items()}

        _update(job_id, progress=93, message="Génération des graphiques…")
        viz = MoMTSimVisualizer(df)
        charts = {
            "volume_par_action": _plotly_html(viz.plot_volume_per_action()),
            "repartition_fraude": _plotly_html(viz.plot_fraud_scenario_distribution()),
            "timeline_fraude": _plotly_html(viz.plot_fraud_timeline()),
        }

        result = {
            "n_transactions": len(df),
            "fraud_rate": fraud_rate,
            "fraud_by_scenario": by_scenario,
            "steps_run": p.n_steps,
            "csv_path": csv_path,
            "charts": charts,
        }
        _update(job_id, status="done", progress=100,
                message="Simulation terminée.", result=result)

    except Exception:
        _update(job_id, status="error", error=traceback.format_exc(),
                message="Erreur pendant la simulation.")


def start_simulation(p: SimulationParams) -> str:
    job_id = _new_job()
    t = threading.Thread(target=_run_simulation_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _run_features_bg(job_id: str) -> None:
    try:
        _update(job_id, status="running", progress=5,
                message="Chargement du rawLog_torch.csv…")
        csv_in = OUTPUT_DIR / "rawLog_torch.csv"
        if not csv_in.exists():
            raise FileNotFoundError("rawLog_torch.csv introuvable. Lancez la simulation d'abord.")

        df_raw = pd.read_csv(csv_in)
        _update(job_id, progress=15, message="Calcul des 12 features…")

        engineer = FeatureEngineer(df_raw)
        df_feat = engineer.compute_all()

        _update(job_id, progress=85, message="Sauvegarde featuresLog.csv…")
        csv_out = str(OUTPUT_DIR / "featuresLog.csv")
        df_feat.to_csv(csv_out, index=False)

        _update(job_id, progress=90, message="Génération des graphiques…")
        viz = MoMTSimVisualizer(df_feat)
        charts = {
            "r1_r2_scatter": _plotly_html(viz.plot_r1_r2_scatter()),
            "distributions": _plotly_html(viz.plot_feature_distributions()),
            "smurfing_delta": _plotly_html(viz.plot_smurfing_network_delta()),
        }

        result = {
            "n_rows": len(df_feat),
            "n_features": len(FEATURES_12),
            "feature_names": FEATURES_12,
            "csv_path": csv_out,
            "charts": charts,
        }
        _update(job_id, status="done", progress=100,
                message="Feature engineering terminé.", result=result)

    except Exception:
        _update(job_id, status="error", error=traceback.format_exc(),
                message="Erreur pendant le feature engineering.")


def start_features(job_id: str | None = None) -> str:
    if job_id is None:
        job_id = _new_job()
    t = threading.Thread(target=_run_features_bg, args=(job_id,), daemon=True)
    t.start()
    return job_id


# ---------------------------------------------------------------------------
# Validation topologique KAN
# ---------------------------------------------------------------------------

def _run_kan_bg(job_id: str) -> None:
    try:
        _update(job_id, status="running", progress=5,
                message="Chargement du featuresLog.csv…")
        csv_in = OUTPUT_DIR / "featuresLog.csv"
        if not csv_in.exists():
            raise FileNotFoundError("featuresLog.csv introuvable. Lancez le feature engineering d'abord.")

        df_feat = pd.read_csv(csv_in)
        _update(job_id, progress=20, message="Normalisation + PCA…")

        validator = TopologyValidator(df_feat, features=FEATURES_12)
        _update(job_id, progress=35, message="Calcul PCA + VE2…")
        validator.pca()
        _update(job_id, progress=50, message="Indice de Fisher…")
        validator.fisher_index()
        _update(job_id, progress=65, message="Test KS par feature…")
        validator.ks_per_feature()
        _update(job_id, progress=78, message="Couverture de grille…")
        validator.grid_coverage()
        decision = validator.decide()

        _update(job_id, progress=85, message="Génération des graphiques…")
        charts = {
            "pca_projection": _plotly_html(validator.plot_pca_projection()),
            "ks_summary": _plotly_html(validator.plot_ks_summary()),
        }

        r = validator.report
        result = {
            "VE2": r.get("VE2", float("nan")),
            "J_Fisher": r.get("J_Fisher", float("nan")),
            "D_KS_mean": r.get("ks_mean", float("nan")),
            "k_for_VE80": r.get("k_for_VE80", 0),
            "decision": decision,
            "features_needing_transform": r.get("features_needing_transform", []),
            "features_poor_coverage": r.get("features_poor_coverage", []),
            "ks_per_feature": r.get("ks_per_feature", {}),
            "grid_coverage": r.get("grid_coverage", {}),
            "charts": charts,
        }
        _update(job_id, status="done", progress=100,
                message="Validation topologique terminée.", result=result)

    except Exception:
        _update(job_id, status="error", error=traceback.format_exc(),
                message="Erreur pendant la validation KAN.")


def start_kan_validation(job_id: str | None = None) -> str:
    if job_id is None:
        job_id = _new_job()
    t = threading.Thread(target=_run_kan_bg, args=(job_id,), daemon=True)
    t.start()
    return job_id


# ---------------------------------------------------------------------------
# Calibration SSE/SPSA
# ---------------------------------------------------------------------------

def _run_calibration_bg(job_id: str, p: CalibrationParams) -> None:
    try:
        _update(job_id, status="running", progress=2,
                message="Initialisation du calibrateur SSE/SPSA…")

        from calibration_sse import SSEFraudCalibrator
        from .config_manager import save_calibrated_probas

        calib = SSEFraudCalibrator(
            param_dir=PARAM_DIR, fraud_config_path=FRAUD_CONFIG_PATH,
            seed=1000, n_clients=p.n_clients, n_merchants=p.n_merchants,
            n_banks=p.n_banks, n_mules=p.n_mules,
            target_mid=p.target_mid, n_steps=p.n_steps,
            n_bins=p.n_bins, n_seeds_per_eval=p.n_seeds_per_eval)

        def _progress_cb(it: int, total: int, sse: float) -> None:
            pct = 5 + int(90 * it / total)
            _update(job_id, progress=pct,
                    message=f"SPSA iter {it}/{total} — SSE={sse:,.1f}")

        _update(job_id, progress=5, message="Calibration SPSA en cours…")
        result_raw = calib.calibrate(
            maxiter=p.maxiter, lr=p.lr, spsa_c=p.spsa_c, verbose=False)

        save_calibrated_probas(result_raw["probas"])

        result = {
            "probas": result_raw["probas"],
            "sse_final": result_raw["sse_final"],
            "converged": result_raw["converged"],
            "history": result_raw["history"],
        }
        _update(job_id, status="done", progress=100,
                message="Calibration terminée.", result=result)

    except Exception:
        _update(job_id, status="error", error=traceback.format_exc(),
                message="Erreur pendant la calibration.")


def start_calibration(p: CalibrationParams) -> str:
    job_id = _new_job()
    t = threading.Thread(target=_run_calibration_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id
