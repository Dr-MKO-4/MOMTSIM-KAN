"""
backend/pipeline_runner.py  Exécution asynchrone du pipeline MoMTSim-KAN.
Utilise BackgroundTasks FastAPI + store in-memory (pas de Celery/Redis).
"""

from __future__ import annotations
import sys
import os
import uuid
import json
import traceback
import threading
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import torch

# Ajouter src/ au path pour importer momtsim_torch, features, viz
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector
from features import FeatureEngineer
from viz import TopologyValidator, MoMTSimVisualizer, FEATURES_12
from .schemas import SimulationParams, CalibrationParams
from . import run_registry as rr

_bundle = Path(os.environ.get("MOMTSIM_BUNDLE_DIR", str(Path(__file__).parent.parent / "config")))
_data   = Path(os.environ.get("MOMTSIM_DATA_DIR",   str(Path(__file__).parent.parent / "config")))

PARAM_DIR         = str(_bundle / "paramFiles")
FRAUD_CONFIG_PATH = str(_data   / "fraudScenariosConfig.json")
OUTPUT_DIR        = _data

# 
# Store in-memory des jobs
# 

_jobs: dict[str, dict] = {}
_cancel_flags: dict[str, threading.Event] = {}
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


def cancel_job(job_id: str) -> bool:
    event = _cancel_flags.get(job_id)
    if event is None:
        return False
    event.set()
    return True


def cancel_all_jobs() -> list[str]:
    """Annule tous les jobs actifs. Retourne les job_ids annulés."""
    cancelled = []
    for job_id, event in list(_cancel_flags.items()):
        event.set()
        cancelled.append(job_id)
    return cancelled


def list_jobs() -> list[dict]:
    return list(_jobs.values())


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        _jobs[job_id].update(kwargs)


def _plotly_html(fig) -> str:
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"responsive": True})


# 
# Simulation
# 

def _run_simulation_bg(job_id: str, p: SimulationParams) -> None:
    _cancel_event = _cancel_flags[job_id]  # pré-populé par start_simulation
    try:
        _update(job_id, status="running", message="Chargement des paramètres…", progress=2)

        params = TorchParameters(PARAM_DIR, FRAUD_CONFIG_PATH,
                                 n_clients=p.n_clients, seed=p.seed)
        engine = TorchMoMTSimEngine(
            params, n_clients=p.n_clients, n_merchants=p.n_merchants,
            n_banks=p.n_banks, n_mules=p.n_mules,
            max_slots_per_step=p.max_slots, seed=p.seed)
        # Auto-chargement des probas calibrées si le frontend n'en envoie pas
        _fraud_probas = p.fraud_probas
        if _fraud_probas is None:
            _calib_path = _data / "calibrated_probas.json"
            if _calib_path.exists():
                with open(_calib_path, encoding="utf-8") as _f:
                    _fraud_probas = json.load(_f)

        injector = TorchFraudInjector(engine, params,
                                      fraud_probas=_fraud_probas, seed=p.seed)

        _update(job_id, message="Simulation en cours…", progress=5)

        import pyarrow as _pa
        import pyarrow.parquet as _pq

        parquet_path = str(OUTPUT_DIR / "rawLog_torch.parquet")
        _pq_writer: "_pq.ParquetWriter | None" = None
        _tx_total = 0

        for step in range(p.n_steps):
            if _cancel_event.is_set():
                _update(job_id, status="error", message="Job annulé par l'utilisateur.",
                        error="Annulé")
                return
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

            # Rebalancement quotidien du float agent (toutes les 24 steps = 1 jour simulé)
            if step % 24 == 0 and step > 0:
                engine.rebalance_agents(params)

            if step % 30 == 0:
                pct = 5 + int(80 * step / p.n_steps)
                _update(job_id, progress=pct,
                        message=f"Step {step}/{p.n_steps}  {_tx_total:,} tx")

            # Flush every 50 steps : vide les listes, écrit le chunk sans tout garder en RAM
            if (step + 1) % 50 == 0:
                _chunk_df = engine.flush_log()
                if not _chunk_df.empty:
                    _table = _pa.Table.from_pandas(_chunk_df, preserve_index=False)
                    if _pq_writer is None:
                        _pq_writer = _pq.ParquetWriter(parquet_path, _table.schema, compression="snappy")
                    _pq_writer.write_table(_table)
                    _tx_total += len(_chunk_df)
                    del _chunk_df, _table

        _update(job_id, progress=87, message="Sauvegarde du rawLog…")
        # Flush final
        _last_df = engine.flush_log()
        if not _last_df.empty:
            _table = _pa.Table.from_pandas(_last_df, preserve_index=False)
            if _pq_writer is None:
                _pq_writer = _pq.ParquetWriter(parquet_path, _table.schema, compression="snappy")
            _pq_writer.write_table(_table)
            _tx_total += len(_last_df)
            del _last_df, _table
        if _pq_writer:
            _pq_writer.close()

        # Relire le parquet complet pour viz + stats
        _update(job_id, progress=88, message="Chargement du rawLog pour analyse…")
        df = pd.read_parquet(parquet_path)

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
            "parquet_path": parquet_path,
            "plain_summary": plain_summary,
            "charts": charts,
            "sim_params": {
                "n_clients":   p.n_clients,
                "n_merchants": p.n_merchants,
                "n_banks":     p.n_banks,
                "n_mules":     p.n_mules,
                "n_steps":     p.n_steps,
                "max_slots":   p.max_slots,
                "seed":        p.seed,
            },
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
    finally:
        _cancel_flags.pop(job_id, None)


def start_simulation(p: SimulationParams) -> str:
    job_id = _new_job()
    _cancel_flags[job_id] = threading.Event()  # enregistré avant le thread pour éviter la race condition
    t = threading.Thread(target=_run_simulation_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


# 
# Feature engineering
# 

def _run_features_bg(job_id: str) -> None:
    try:
        _update(job_id, status="running", progress=5,
                message="Chargement du rawLog_torch.parquet…")
        parquet_in = OUTPUT_DIR / "rawLog_torch.parquet"
        if not parquet_in.exists():
            raise FileNotFoundError("rawLog_torch.parquet introuvable. Lancez la simulation d'abord.")

        df_raw = pd.read_parquet(parquet_in)
        _update(job_id, progress=15, message="Calcul des 12 features…")

        engineer = FeatureEngineer(df_raw)
        df_feat = engineer.compute_all()

        _update(job_id, progress=85, message="Sauvegarde featuresLog.parquet…")
        csv_out = str(OUTPUT_DIR / "featuresLog.parquet")
        df_feat.to_parquet(csv_out, index=False)

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
            "parquet_path": csv_out,
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


# 
# Validation topologique KAN
# 

def _run_kan_bg(job_id: str) -> None:
    try:
        _update(job_id, status="running", progress=5,
                message="Chargement du featuresLog.parquet…")
        csv_in = OUTPUT_DIR / "featuresLog.parquet"
        if not csv_in.exists():
            raise FileNotFoundError("featuresLog.parquet introuvable. Lancez le feature engineering d'abord.")

        df_feat = pd.read_parquet(csv_in)

        # Échantillonnage stratifié pour limiter la RAM (100k suffit pour PCA/Fisher/KS)
        _MAX_KAN_ROWS = 100_000
        if len(df_feat) > _MAX_KAN_ROWS:
            _fraud = df_feat[df_feat["isFraud"].astype(bool)]
            _legit = df_feat[~df_feat["isFraud"].astype(bool)]
            _n_fraud = min(len(_fraud), int(_MAX_KAN_ROWS * 0.1))
            _n_legit = _MAX_KAN_ROWS - _n_fraud
            df_feat = pd.concat([
                _fraud.sample(n=_n_fraud, random_state=42) if _n_fraud > 0 else _fraud.iloc[:0],
                _legit.sample(n=min(_n_legit, len(_legit)), random_state=42),
            ], ignore_index=True)

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


# 
# Calibration SSE/SPSA
# 

def _run_calibration_bg(job_id: str, p: CalibrationParams) -> None:
    _cancel_event = _cancel_flags[job_id]  # pré-populé par start_calibration
    try:
        _update(job_id, status="running", progress=2,
                message="Initialisation du calibrateur SSE/SPSA…")

        from calibration_sse import SSEFraudCalibrator
        from .config_manager import save_calibrated_probas

        calib = SSEFraudCalibrator(
            param_dir=PARAM_DIR, fraud_config_path=FRAUD_CONFIG_PATH,
            seed=1000, n_clients=p.n_clients, n_merchants=p.n_merchants,
            n_banks=p.n_banks, n_mules=p.n_mules,
            max_slots_per_step=p.max_slots,
            target_mid=p.target_mid, n_steps=p.n_steps,
            n_bins=p.n_bins, n_seeds_per_eval=p.n_seeds_per_eval)

        _update(job_id, progress=5, message="Calibration SPSA en cours…")
        result_raw = calib.calibrate(
            maxiter=p.maxiter, lr=p.lr, spsa_c=p.spsa_c, verbose=False,
            cancel_check=lambda: _cancel_event.is_set())

        if _cancel_event.is_set():
            _update(job_id, status="error", message="Calibration annulée par l'utilisateur.",
                    error="Annulé")
            return

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
    finally:
        _cancel_flags.pop(job_id, None)


def start_calibration(p: CalibrationParams) -> str:
    job_id = _new_job()
    _cancel_flags[job_id] = threading.Event()  # enregistré avant le thread
    t = threading.Thread(target=_run_calibration_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


# 
# Endpoints données paginées
# 

def _df_to_rows(chunk: pd.DataFrame) -> list:
    return json.loads(chunk.to_json(orient="values"))


def get_raw_data_page(page: int = 1, page_size: int = 100,
                      filter_fraud: bool = False) -> dict:
    parquet_path = OUTPUT_DIR / "rawLog_torch.parquet"
    if not parquet_path.exists():
        raise FileNotFoundError("rawLog_torch.parquet introuvable.")
    df = pd.read_parquet(parquet_path)
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
        "rows": _df_to_rows(chunk),
    }


def get_features_data_page(page: int = 1, page_size: int = 100,
                           filter_fraud: bool = False) -> dict:
    csv_path = OUTPUT_DIR / "featuresLog.parquet"
    if not csv_path.exists():
        raise FileNotFoundError("featuresLog.parquet introuvable.")
    df = pd.read_parquet(csv_path)
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
        "rows": _df_to_rows(chunk),
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
