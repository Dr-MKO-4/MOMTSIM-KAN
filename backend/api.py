"""
backend/api.py — FastAPI app MoMTSim-KAN.

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
"""

from __future__ import annotations
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .schemas import (
    FraudConfig, SimulationParams, CalibrationParams,
    JobStatus,
)
from . import config_manager as cm
from . import pipeline_runner as pr

app = FastAPI(
    title="MoMTSim-KAN API",
    description="Pipeline de simulation et détection de fraude Mobile Money (CEMAC/Cameroun)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000","http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Probas calibrées
# ---------------------------------------------------------------------------

@app.get("/api/probas", tags=["calibration"])
def get_calibrated_probas():
    p = cm.load_calibrated_probas()
    if p is None:
        raise HTTPException(404, "calibrated_probas.json introuvable. Lancez la calibration d'abord.")
    return p


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/api/jobs", tags=["jobs"])
def list_jobs():
    return pr.list_jobs()


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str):
    job = pr.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id!r} introuvable.")
    return job


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@app.post("/api/simulate", tags=["pipeline"])
def simulate(params: SimulationParams):
    # Charger les probas calibrées par défaut si non fournies
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


# ---------------------------------------------------------------------------
# Santé
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["system"])
def health():
    raw_ok = (Path(__file__).parent.parent / "rawLog_torch.csv").exists()
    feat_ok = (Path(__file__).parent.parent / "featuresLog.csv").exists()
    probas_ok = (Path(__file__).parent.parent / "calibrated_probas.json").exists()
    config_ok = (Path(__file__).parent.parent / "fraudScenariosConfig.json").exists()
    return {
        "status": "ok",
        "files": {
            "fraudScenariosConfig": config_ok,
            "rawLog_torch": raw_ok,
            "featuresLog": feat_ok,
            "calibrated_probas": probas_ok,
        }
    }
