"""
backend/pipeline_runner.py  Exécution asynchrone du pipeline MoMTSim-KAN.
Fils d'exécution + store in-memory (pas de Celery/Redis).

Chaque job expose, en plus de progress/message : les étapes (stages) et leur
état, le temps écoulé, le temps restant estimé, des métriques en direct et, pour
la calibration, l'historique SPSA au fil des itérations.
"""

from __future__ import annotations
import sys
import os
import time
import uuid
import json
import traceback
import threading
from pathlib import Path

import pandas as pd

# Ajouter src/ au path pour importer momtsim_torch, features, viz
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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

STAGES = {
    "simulation":  [("init", "Initialisation"), ("simulate", "Simulation"),
                    ("analyse", "Contrôles"), ("charts", "Graphiques")],
    "features":    [("load", "Lecture du journal"), ("compute", "Calcul des 12 features"),
                    ("save", "Écriture"), ("charts", "Graphiques")],
    "kan":         [("load", "Lecture"), ("validate", "Validation topologique"),
                    ("charts", "Graphiques")],
    "calibration": [("init", "Cible Dr et départ θ0"), ("spsa", "Itérations SPSA"),
                    ("report", "Verdict")],
}


def _new_job(kind: str = "job") -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "pending",
            "progress": 0,
            "message": "En file d'attente…",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "eta_s": None,
            "stage": None,
            "stages": [{"key": k, "label": l, "status": "pending"} for k, l in STAGES.get(kind, [])],
            "indeterminate": False,
            "metrics": {},
            "history": [],
        }
    return job_id


def get_job(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    with _lock:
        out = dict(job)
    end = out["finished_at"] or time.time()
    out["elapsed_s"] = end - out["started_at"]
    return out


def cancel_job(job_id: str) -> bool:
    event = _cancel_flags.get(job_id)
    if event is None:
        return False
    event.set()
    _update(job_id, message="Annulation demandée…")
    return True


def cancel_all_jobs() -> list[str]:
    """Annule tous les jobs actifs. Retourne les job_ids annulés."""
    cancelled = []
    for job_id, event in list(_cancel_flags.items()):
        event.set()
        cancelled.append(job_id)
    return cancelled


def list_jobs() -> list[dict]:
    return [get_job(j) for j in list(_jobs)]


def _update(job_id: str, **kwargs) -> None:
    with _lock:
        job = _jobs[job_id]
        job.update(kwargs)
        if kwargs.get("status") in ("done", "error"):
            job["finished_at"] = time.time()
            job["eta_s"] = None
            job["indeterminate"] = False
            for s in job["stages"]:
                if s["status"] == "running":
                    s["status"] = "done" if kwargs["status"] == "done" else "error"
            if kwargs["status"] == "done":
                for s in job["stages"]:
                    s["status"] = "done"


def _stage(job_id: str, key: str, message: str | None = None, indeterminate: bool = False) -> None:
    """Passe le job à l'étape `key` : les étapes précédentes sont terminées."""
    with _lock:
        job = _jobs[job_id]
        reached = False
        for s in job["stages"]:
            if s["key"] == key:
                s["status"] = "running"
                reached = True
            elif not reached:
                s["status"] = "done"
        job["stage"] = key
        job["indeterminate"] = indeterminate
        job["status"] = "running"
        if message:
            job["message"] = message


def _metrics(job_id: str, **kwargs) -> None:
    with _lock:
        _jobs[job_id]["metrics"].update(kwargs)


def _plotly_html(fig) -> str:
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"responsive": True})


def _cancelled_job(job_id: str, what: str) -> None:
    _update(job_id, status="error", message=f"{what} annulée par l'utilisateur.", error="Annulé")


#
# Simulation
#

def _run_simulation_bg(job_id: str, p: SimulationParams) -> None:
    import generation as gen
    _cancel_event = _cancel_flags[job_id]  # pré-populé par start_simulation
    try:
        _stage(job_id, "init", "Chargement des paramètres et de la population…")
        _update(job_id, progress=1)
        # Auto-chargement des probas calibrées si le frontend n'en envoie pas
        _fraud_probas = p.fraud_probas
        if _fraud_probas is None:
            _calib_path = _data / "calibrated_probas.json"
            if _calib_path.exists():
                with open(_calib_path, encoding="utf-8") as _f:
                    _fraud_probas = json.load(_f)

        cfg = gen.resolve_config({
            "n_clients": p.n_clients, "n_merchants": p.n_merchants, "n_banks": p.n_banks,
            "n_mules": p.n_mules, "n_steps": p.n_steps, "max_slots": p.max_slots,
            "seed": p.seed, "volume_scale": p.volume_scale, "volume_follow": p.volume_follow,
        })
        parquet_path = OUTPUT_DIR / "rawLog_torch.parquet"
        t_sim = [None]

        def on_step(step, n_steps, n_tx, n_fraud):
            if t_sim[0] is None:
                t_sim[0] = time.time()
                _stage(job_id, "simulate")
            if step % 5 and step != n_steps:
                return
            elapsed = time.time() - t_sim[0]
            eta = elapsed / step * (n_steps - step) if step else None
            rate = n_fraud / n_tx if n_tx else 0.0
            _update(job_id, progress=2 + int(83 * step / n_steps), eta_s=eta,
                    message=f"Pas {step}/{n_steps} : {n_tx:,} transactions, fraude {rate:.1%}"
                    .replace(",", " "))
            _metrics(job_id, step=step, n_steps=n_steps, n_transactions=n_tx,
                     n_fraud=n_fraud, fraud_rate=rate,
                     steps_per_s=step / elapsed if elapsed > 0 else None)

        summary = gen.simulate_to_parquet(cfg, _fraud_probas, parquet_path, progress=on_step,
                                          cancel=_cancel_event.is_set, param_dir=PARAM_DIR,
                                          fraud_config_path=FRAUD_CONFIG_PATH)
        if summary["cancelled"]:
            _cancelled_job(job_id, "Simulation")
            return
        injector = summary.pop("injector")

        _stage(job_id, "analyse", "Contrôles du jeu produit…")
        _update(job_id, progress=86, eta_s=None)
        validation = gen.validate_simulation(summary)
        df = pd.read_parquet(parquet_path)
        tracking = injector.get_tracking()
        fraud_rate = float(df["isFraud"].mean()) if len(df) else 0.0
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

        _stage(job_id, "charts", "Génération des graphiques…", indeterminate=True)
        _update(job_id, progress=90)
        viz = MoMTSimVisualizer(df, injector_tracking=tracking)

        # Charger aggregatedTransactions pour le NRMSE heatmap si disponible
        agg_path = Path(PARAM_DIR) / "aggregatedTransactions.csv"
        if agg_path.exists():
            try:
                viz.df_target = pd.read_csv(agg_path)
            except Exception:
                pass

        chart_fns = {
            "volume_par_action":   viz.plot_volume_per_action,
            "repartition_fraude":  viz.plot_fraud_scenario_distribution,
            "timeline_fraude":     viz.plot_fraud_timeline,
            "fraudster_summary":   viz.plot_fraudster_summary,
            "ato_exfiltration":    viz.plot_ato_exfiltration_window,
            "refund_delays":       viz.plot_refund_delay_distribution,
            "fake_cred_dormance":  viz.plot_fake_credentials_dormance,
            "split_deposit_var":   viz.plot_split_deposit_variance,
            "smurfing_periodicity": viz.plot_smurfing_periodicity,
            "smurfing_sankey":     viz.plot_smurfing_sankey,
        }
        if viz.df_target is not None:
            chart_fns["nrmse_heatmap"] = viz.plot_nrmse_heatmap
        charts: dict[str, str] = {}
        for i, (name, fn) in enumerate(chart_fns.items()):
            _update(job_id, progress=90 + int(9 * i / len(chart_fns)),
                    message=f"Graphique {i + 1}/{len(chart_fns)} : {name}")
            try:
                charts[name] = _plotly_html(fn())
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
            "parquet_path": str(parquet_path),
            "plain_summary": plain_summary,
            "validation": validation,
            "elapsed_sim_s": summary["elapsed_s"],
            "charts": charts,
            "sim_params": {
                "n_clients":   p.n_clients,
                "n_merchants": p.n_merchants,
                "n_banks":     p.n_banks,
                "n_mules":     p.n_mules,
                "n_steps":     p.n_steps,
                "max_slots":   p.max_slots,
                "seed":        p.seed,
                "volume_scale": cfg["volume_scale"],
                "volume_follow": cfg["volume_follow"],
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
    job_id = _new_job("simulation")
    _cancel_flags[job_id] = threading.Event()  # enregistré avant le thread pour éviter la race condition
    t = threading.Thread(target=_run_simulation_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


#
# Feature engineering
#

def _run_features_bg(job_id: str) -> None:
    try:
        _stage(job_id, "load", "Chargement du rawLog_torch.parquet…")
        _update(job_id, progress=3)
        parquet_in = OUTPUT_DIR / "rawLog_torch.parquet"
        if not parquet_in.exists():
            raise FileNotFoundError("rawLog_torch.parquet introuvable. Lancez la simulation d'abord.")

        df_raw = pd.read_parquet(parquet_in)
        _metrics(job_id, n_rows=len(df_raw))
        # Le calcul vectorisé ne fournit pas de progression intermédiaire : barre animée
        _stage(job_id, "compute",
               f"Calcul des 12 features sur {len(df_raw):,} transactions…".replace(",", " "),
               indeterminate=True)
        _update(job_id, progress=10)

        engineer = FeatureEngineer(df_raw)
        df_feat = engineer.compute_all()

        _stage(job_id, "save", "Sauvegarde featuresLog.parquet…")
        _update(job_id, progress=85)
        csv_out = str(OUTPUT_DIR / "featuresLog.parquet")
        df_feat.to_parquet(csv_out, index=False)

        _stage(job_id, "charts", "Génération des graphiques…", indeterminate=True)
        _update(job_id, progress=90)
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
        job_id = _new_job("features")
    t = threading.Thread(target=_run_features_bg, args=(job_id,), daemon=True)
    t.start()
    return job_id


#
# Validation topologique KAN
#

def _run_kan_bg(job_id: str) -> None:
    try:
        _stage(job_id, "load", "Chargement du featuresLog.parquet…")
        _update(job_id, progress=5)
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

        _stage(job_id, "validate",
               "Validation topologique (normalisation → PCA → Fisher → KS → décision)…",
               indeterminate=True)
        _update(job_id, progress=20)

        validator = TopologyValidator(df_feat, features=FEATURES_12)
        r = validator.run_full_validation_with_retry(max_retries=1)
        decision = r.get("decision", "inconnu")

        _stage(job_id, "charts", "Génération des graphiques…")
        _update(job_id, progress=85)
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
        job_id = _new_job("kan")
    t = threading.Thread(target=_run_kan_bg, args=(job_id,), daemon=True)
    t.start()
    return job_id


#
# Calibration SSE/SPSA
#

def _run_calibration_bg(job_id: str, p: CalibrationParams) -> None:
    _cancel_event = _cancel_flags[job_id]  # pré-populé par start_calibration
    try:
        _stage(job_id, "init", "Construction de la cible Dr et du départ analytique θ0…")
        _update(job_id, progress=1)

        from calibration_sse import SSEFraudCalibrator, default_workers
        from .config_manager import (save_calibrated_probas, save_calibration_report,
                                     load_calibrated_probas)

        calib = SSEFraudCalibrator(
            param_dir=PARAM_DIR, fraud_config_path=FRAUD_CONFIG_PATH,
            seed=1000, n_clients=p.n_clients, n_merchants=p.n_merchants,
            n_banks=p.n_banks, n_mules=p.n_mules,
            max_slots_per_step=p.max_slots,
            target_mid=p.target_mid, n_steps=p.n_steps,
            n_bins=p.n_bins, n_seeds_per_eval=p.n_seeds_per_eval,
            volume_scale=p.volume_scale, volume_follow=p.volume_follow,
            n_workers=p.n_workers or default_workers())
        _metrics(job_id, n_workers=calib.n_workers, maxiter=p.maxiter,
                 sims_total=3 * p.n_seeds_per_eval * p.maxiter + p.n_seeds_per_eval)

        x0 = None
        if p.start_from_current:
            cur = load_calibrated_probas()
            if cur:
                x0 = [cur["ato"], cur["refund"], cur["fake_credentials"],
                      cur["split_deposit"], cur["smurfing_freq_mult"]]

        started = [False]

        def _on_progress(frac: float, label: str, info: dict) -> None:
            if not started[0]:
                started[0] = True
                _stage(job_id, "spsa")
            _update(job_id, progress=2 + int(95 * frac), message=label, eta_s=info.get("eta_s"))
            _metrics(job_id, sims_done=round(info["sims_done"], 1),
                     sims_total=info["sims_total"], iteration=info["iteration"])

        def _on_iteration(entry: dict) -> None:
            with _lock:
                _jobs[job_id]["history"].append(
                    {k: entry.get(k) for k in ("iter", "sse", "best_sse", "theta", "fraud_rate")})
            _metrics(job_id, last_sse=entry.get("sse"), best_sse=entry.get("best_sse"),
                     fraud_rate=entry.get("fraud_rate"))

        result_raw = calib.calibrate(
            x0=x0, maxiter=p.maxiter, lr=p.lr, spsa_c=p.spsa_c, verbose=False,
            cancel_check=_cancel_event.is_set, progress_cb=_on_progress,
            iteration_cb=_on_iteration, gain_schedule=p.gain_schedule,
            checkpoint_path=str(_data / "calibration_checkpoint.json"), resume=p.resume)

        if result_raw["cancelled"] or _cancel_event.is_set():
            _cancelled_job(job_id, "Calibration")
            return

        _stage(job_id, "report", "Interprétation du résultat…")
        save_calibrated_probas(result_raw["probas"])
        save_calibration_report(result_raw)
        try:
            (_data / "calibration_checkpoint.json").unlink(missing_ok=True)
        except Exception:
            pass

        result = {k: result_raw[k] for k in
                  ("probas", "sse_final", "converged", "history", "verdict", "theta0",
                   "sse_theta0", "sse_zero_fraud", "best_eval", "Dr", "config", "elapsed_s",
                   "n_workers")}
        _update(job_id, status="done", progress=100,
                message=f"Calibration terminée : {result_raw['verdict']['verdict']}.", result=result)

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
    job_id = _new_job("calibration")
    _cancel_flags[job_id] = threading.Event()  # enregistré avant le thread
    t = threading.Thread(target=_run_calibration_bg, args=(job_id, p), daemon=True)
    t.start()
    return job_id


def calibration_report() -> dict | None:
    """Dernier rapport de calibration, réinterprété avec les fichiers actuels."""
    from calibration_report import interpret_calibration
    from .config_manager import load_calibration_report
    res = load_calibration_report()
    if res is None:
        return None
    res["verdict"] = interpret_calibration(res, fraud_config_path=FRAUD_CONFIG_PATH)
    return res


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
