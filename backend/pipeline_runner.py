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
from . import run_registry as rr

_bundle = Path(os.environ.get("MOMTSIM_BUNDLE_DIR", str(Path(__file__).parent.parent)))
_data   = Path(os.environ.get("MOMTSIM_DATA_DIR",   str(Path(__file__).parent.parent)))

PARAM_DIR         = str(_bundle / "paramFiles")
FRAUD_CONFIG_PATH = str(_data   / "fraudScenariosConfig.json")
OUTPUT_DIR        = _data

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

            if step % 30 == 0:
                pct = 5 + int(80 * step / p.n_steps)
                _update(job_id, progress=pct,
                        message=f"Step {step}/{p.n_steps} — {len(engine.log_step)} tx")

        _update(job_id, progress=87, message="Sauvegarde du rawLog…")
        df = engine.to_dataframe()
        csv_path = str(OUTPUT_DIR / "rawLog_torch.csv")
        df.to_csv(csv_path, index=False)

        tracking = injector.get_tracking()
        fraud_rate = float(df["isFraud"].mean())
        by_scenario: dict[str, float] = {}
        if df["isFraud"].any():
            vc = df.loc[df["isFraud"], "fraudScenario"].value_counts(normalize=True)
            by_scenario = {k: float(v) for k, v in vc.items()}

        # Fraudster summary CSV
        try:
            fs_df = injector.export_fraudster_summary()
            if not fs_df.empty:
                fs_df.to_csv(str(OUTPUT_DIR / "fraudsters.csv"), index=False)
        except Exception:
            pass

        _update(job_id, progress=90, message="Génération des graphiques…")
        viz = MoMTSimVisualizer(df, injector_tracking=tracking)

        # Charger aggregatedTransactions pour le NRMSE heatmap si disponible
        agg_path = Path(PARAM_DIR) / "aggregatedTransactions.csv"
        if agg_path.exists():
            try:
                df_agg = pd.read_csv(agg_path)
                viz.df_target = df_agg
            except Exception:
                pass

        charts: dict[str, str] = {
            "volume_par_action":   _plotly_html(viz.plot_volume_per_action()),
            "repartition_fraude":  _plotly_html(viz.plot_fraud_scenario_distribution()),
            "timeline_fraude":     _plotly_html(viz.plot_fraud_timeline()),
            "fraudster_summary":   _plotly_html(viz.plot_fraudster_summary()),
            "ato_exfiltration":    _plotly_html(viz.plot_ato_exfiltration_window()),
            "refund_delays":       _plotly_html(viz.plot_refund_delay_distribution()),
            "fake_cred_dormance":  _plotly_html(viz.plot_fake_credentials_dormance()),
            "split_deposit_var":   _plotly_html(viz.plot_split_deposit_variance()),
            "smurfing_periodicity": _plotly_html(viz.plot_smurfing_periodicity()),
            "smurfing_sankey":     _plotly_html(viz.plot_smurfing_sankey()),
        }
        if viz.df_target is not None:
            try:
                charts["nrmse_heatmap"] = _plotly_html(viz.plot_nrmse_heatmap())
            except Exception:
                pass

        plain_summary = MoMTSimVisualizer.generate_simulation_plain_summary({
            "n_transactions": len(df),
            "fraud_rate": fraud_rate,
            "fraud_by_scenario": by_scenario,
            "steps_run": p.n_steps,
        })

        result = {
            "n_transactions": len(df),
            "fraud_rate": fraud_rate,
            "fraud_by_scenario": by_scenario,
            "steps_run": p.n_steps,
            "csv_path": csv_path,
            "plain_summary": plain_summary,
            "charts": charts,
        }
        _update(job_id, status="done", progress=100,
                message="Simulation terminée.", result=result)

        try:
            rr.register_run(job_id, "simulation", result)
        except Exception:
            pass

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
            "r1_r2_scatter":  _plotly_html(viz.plot_r1_r2_scatter()),
            "distributions":  _plotly_html(viz.plot_feature_distributions()),
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

        try:
            rr.register_run(job_id, "features", result)
        except Exception:
            pass

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
        _update(job_id, progress=20,
                message="Validation topologique (normalisation → PCA → Fisher → KS → décision)…")

        validator = TopologyValidator(df_feat, features=FEATURES_12)
        r = validator.run_full_validation_with_retry(max_retries=1)
        decision = r.get("decision", "inconnu")

        _update(job_id, progress=85, message="Génération des graphiques…")
        charts = {
            "pca_projection": _plotly_html(validator.plot_pca_projection()),
            "ks_summary":     _plotly_html(validator.plot_ks_summary()),
        }

        plain_summary = MoMTSimVisualizer.generate_kan_plain_summary(r)

        result = {
            "VE2":            r.get("VE2", float("nan")),
            "J_Fisher":       r.get("J_Fisher", float("nan")),
            "D_KS_mean":      r.get("ks_mean", float("nan")),
            "k_for_VE80":     r.get("k_for_VE80", 0),
            "decision":       decision,
            "features_needing_transform": r.get("features_needing_transform", []),
            "features_poor_coverage":     r.get("features_poor_coverage", []),
            "ks_per_feature": r.get("ks_per_feature", {}),
            "grid_coverage":  r.get("grid_coverage", {}),
            "transform_applied": r.get("transform_applied"),
            "transform_warning": r.get("transform_warning"),
            "plain_summary":  plain_summary,
            "charts": charts,
        }
        _update(job_id, status="done", progress=100,
                message="Validation topologique terminée.", result=result)

        try:
            rr.register_run(job_id, "kan", result)
        except Exception:
            pass

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

        _update(job_id, progress=5, message="Calibration SPSA en cours…")
        result_raw = calib.calibrate(
            maxiter=p.maxiter, lr=p.lr, spsa_c=p.spsa_c, verbose=False)

        save_calibrated_probas(result_raw["probas"])

        result = {
            "probas":    result_raw["probas"],
            "sse_final": result_raw["sse_final"],
            "converged": result_raw["converged"],
            "history":   result_raw["history"],
        }
        _update(job_id, status="done", progress=100,
                message="Calibration terminée.", result=result)

        try:
            rr.register_run(job_id, "calibration", result)
        except Exception:
            pass

    except Exception:
        _update(job_id, status="error", error=traceback.format_exc(),
                message="Erreur pendant la calibration.")


def start_calibration(p: CalibrationParams) -> str:
    job_id = _new_job()
    t = threading.Thread(target=_run_calibration_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


# ---------------------------------------------------------------------------
# Endpoints données paginées
# ---------------------------------------------------------------------------

def get_raw_data_page(page: int = 1, page_size: int = 100,
                      filter_fraud: bool = False) -> dict:
    csv_path = OUTPUT_DIR / "rawLog_torch.csv"
    if not csv_path.exists():
        raise FileNotFoundError("rawLog_torch.csv introuvable.")
    df = pd.read_csv(csv_path)
    if filter_fraud:
        df = df[df["isFraud"].astype(bool)]
    total = len(df)
    start = (page - 1) * page_size
    end   = start + page_size
    chunk = df.iloc[start:end]
    return {
        "page": page, "page_size": page_size, "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "columns": list(chunk.columns),
        "rows": chunk.values.tolist(),
    }


def get_features_data_page(page: int = 1, page_size: int = 100,
                           filter_fraud: bool = False) -> dict:
    csv_path = OUTPUT_DIR / "featuresLog.csv"
    if not csv_path.exists():
        raise FileNotFoundError("featuresLog.csv introuvable.")
    df = pd.read_csv(csv_path)
    if filter_fraud:
        df = df[df["isFraud"].astype(bool)]
    total = len(df)
    start = (page - 1) * page_size
    end   = start + page_size
    chunk = df.iloc[start:end]
    return {
        "page": page, "page_size": page_size, "total": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
        "columns": list(chunk.columns),
        "rows": chunk.values.tolist(),
    }


def get_fraudsters_data() -> dict:
    csv_path = OUTPUT_DIR / "fraudsters.csv"
    if not csv_path.exists():
        return {"columns": [], "rows": [], "total": 0}
    df = pd.read_csv(csv_path)
    return {
        "total": len(df),
        "columns": list(df.columns),
        "rows": df.values.tolist(),
    }
