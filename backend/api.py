"""
backend/api.py  FastAPI app MoMTSim-KAN.

Endpoints :
  GET  /api/config                 → lire fraudScenariosConfig.json
  PUT  /api/config                 → écrire + backup
  GET  /api/config/backups         → liste des backups
  POST /api/config/restore/{name}  → restaurer un backup

  POST /api/simulate               → lancer simulation (job async)
  POST /api/features               → lancer feature engineering
  POST /api/kan/validate           → lancer validation topologique KAN
  POST /api/calibrate              → lancer calibration SSE/SPSA

  GET  /api/jobs/{job_id}          → statut + résultat d'un job
  GET  /api/jobs                   → liste de tous les jobs

  GET  /api/probas                 → calibrated_probas.json courant

  GET  /api/data/raw               → rawLog_torch.parquet paginé
  GET  /api/data/features          → featuresLog.csv paginé
  GET  /api/data/fraudsters        → fraudsters.csv complet

  GET  /api/runs                   → historique des runs (SQLite)
  GET  /api/runs/{run_id}          → détail d'un run
  DELETE /api/runs/{run_id}        → supprimer un run
"""

from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .schemas import SimulationParams, CalibrationParams
from . import config_manager as cm
from . import pipeline_runner as pr
from . import run_registry as rr
from . import test_case_manager as tcm

app = FastAPI(
    title="MoMTSim-KAN API",
    description="Pipeline de simulation et détection de fraude Mobile Money (CEMAC/Cameroun)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 
# Config
# 

@app.get("/api/config", tags=["config"])
def get_config():
    try:
        return cm.load_fraud_config()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.put("/api/config", tags=["config"])
def update_config(data: dict):
    errors = cm.validate_fraud_config(data)
    if errors:
        raise HTTPException(422, {"validation_errors": errors})
    path = cm.save_fraud_config(data, backup=True)
    return {"saved": path}


@app.get("/api/config/backups", tags=["config"])
def list_backups():
    return cm.list_backups()


@app.post("/api/config/restore/{backup_name}", tags=["config"])
def restore_backup(backup_name: str):
    try:
        path = cm.restore_backup(backup_name)
        return {"restored": path}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


# 
# Sim config (sim_config.json)
# 

@app.get("/api/sim-config", tags=["config"])
def get_sim_config():
    return cm.load_sim_config()


@app.put("/api/sim-config", tags=["config"])
def put_sim_config(params: SimulationParams):
    data = {k: v for k, v in params.__dict__.items() if k != "fraud_probas"}
    path = cm.save_sim_config(data)
    return {"saved": path}


# 
# Calib config (calib_config.json)
# 

@app.get("/api/calib-config", tags=["calibration"])
def get_calib_config():
    return cm.load_calib_config()


@app.put("/api/calib-config", tags=["calibration"])
def put_calib_config(params: CalibrationParams):
    path = cm.save_calib_config(params.__dict__)
    return {"saved": path}


# 
# Probas calibrées
# 

@app.get("/api/probas", tags=["calibration"])
def get_calibrated_probas():
    p = cm.load_calibrated_probas()
    if p is None:
        raise HTTPException(404, "calibrated_probas.json introuvable. Lancez la calibration d'abord.")
    return p


# 
# Jobs
# 

@app.get("/api/jobs", tags=["jobs"])
def list_jobs():
    return pr.list_jobs()


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str):
    job = pr.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id!r} introuvable.")
    return job


@app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
def cancel_job_endpoint(job_id: str):
    cancelled = pr.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(404, "Job introuvable ou déjà terminé.")
    return {"cancelled": True, "job_id": job_id}


@app.post("/api/jobs/cancel-all", tags=["jobs"])
def cancel_all_jobs():
    """Annule tous les jobs en cours (pending + running)."""
    cancelled = pr.cancel_all_jobs()
    return {"cancelled": cancelled}


# 
# Pipeline
# 

@app.post("/api/simulate", tags=["pipeline"])
def simulate(params: SimulationParams):
    if params.fraud_probas is None:
        params.fraud_probas = cm.load_calibrated_probas()
    job_id = pr.start_simulation(params)
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/features", tags=["pipeline"])
def run_features():
    job_id = pr.start_features()
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/kan/validate", tags=["pipeline"])
def kan_validate():
    job_id = pr.start_kan_validation()
    return {"job_id": job_id, "status": "pending"}


@app.post("/api/calibrate", tags=["calibration"])
def calibrate(params: CalibrationParams):
    job_id = pr.start_calibration(params)
    return {"job_id": job_id, "status": "pending"}


# 
# Données paginées (BLOC A5)
# 

@app.get("/api/data/raw", tags=["data"])
def get_raw_data(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=1000),
    filter_fraud: bool = Query(False),
):
    try:
        return pr.get_raw_data_page(page=page, page_size=page_size, filter_fraud=filter_fraud)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/api/data/features", tags=["data"])
def get_features_data(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=1000),
    filter_fraud: bool = Query(False),
):
    try:
        return pr.get_features_data_page(page=page, page_size=page_size, filter_fraud=filter_fraud)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/api/data/fraudsters", tags=["data"])
def get_fraudsters():
    return pr.get_fraudsters_data()


# 
# Cas de test
# 

@app.get("/api/test-cases", tags=["test-cases"])
def list_test_cases():
    return tcm.load_test_cases()


@app.post("/api/test-cases", tags=["test-cases"])
def create_test_case(body: dict):
    name = body.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name requis.")
    return tcm.save_test_case(name, body.get("params", {}), body.get("description", ""))


@app.delete("/api/test-cases/{case_id}", tags=["test-cases"])
def remove_test_case(case_id: str):
    if not tcm.delete_test_case(case_id):
        raise HTTPException(status_code=404, detail="Cas de test introuvable.")
    return {"ok": True}


# 
# Historique des runs (BLOC C4)
# 

@app.get("/api/runs", tags=["history"])
def list_runs(
    run_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    return rr.list_runs(run_type=run_type, limit=limit)


@app.get("/api/runs/{run_id}", tags=["history"])
def get_run(run_id: str):
    run = rr.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id!r} introuvable.")
    return run


@app.delete("/api/runs/{run_id}", tags=["history"])
def delete_run(run_id: str):
    found = rr.delete_run(run_id)
    if not found:
        raise HTTPException(404, f"Run {run_id!r} introuvable.")
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}/params", tags=["history"])
def get_run_params(run_id: str):
    """Retourne les SimulationParams sauvegardés pour un run de type simulation."""
    run = rr.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Run {run_id!r} introuvable.")
    params = run.get("summary", {}).get("sim_params") or run.get("metadata", {}).get("sim_params")
    if params is None:
        raise HTTPException(404, "Paramètres de simulation introuvables pour ce run (run trop ancien ou type non simulation).")
    return params


# 
# Santé
# 

@app.get("/api/health", tags=["system"])
def health():
    _data = Path(os.environ.get("MOMTSIM_DATA_DIR", str(Path(__file__).parent.parent / "config")))
    return {
        "status": "ok",
        "files": {
            "fraudScenariosConfig": (_data / "fraudScenariosConfig.json").exists(),
            "rawLog_torch":         (_data / "rawLog_torch.parquet").exists(),
            "featuresLog":          (_data / "featuresLog.parquet").exists(),
            "calibrated_probas":    (_data / "calibrated_probas.json").exists(),
        },
    }


# ── Serve React SPA  must be mounted LAST so API routes take priority ────────
_frontend_dist = os.environ.get(
    "MOMTSIM_FRONTEND_DIST",
    str(Path(__file__).parent.parent / "frontend" / "dist"),
)
if Path(_frontend_dist).exists():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
