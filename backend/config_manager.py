"""
backend/config_manager.py — Lecture / écriture / backup du fichier fraudScenariosConfig.json.
"""

from __future__ import annotations
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from .schemas import FraudConfig

_data = Path(os.environ.get("MOMTSIM_DATA_DIR", str(Path(__file__).parent.parent / "config")))

FRAUD_CONFIG_PATH = _data / "fraudScenariosConfig.json"
BACKUP_DIR        = _data / "config_backups"


def _ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(exist_ok=True)


def load_fraud_config() -> dict:
    if not FRAUD_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config introuvable : {FRAUD_CONFIG_PATH}")
    with open(FRAUD_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_fraud_config(data: dict, backup: bool = True) -> str:
    """Sauvegarde la config fraude, crée un backup horodaté si demandé."""
    if backup and FRAUD_CONFIG_PATH.exists():
        _ensure_backup_dir()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = BACKUP_DIR / f"fraudScenariosConfig_{ts}.json"
        shutil.copy2(FRAUD_CONFIG_PATH, dest)

    with open(FRAUD_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return str(FRAUD_CONFIG_PATH)


def validate_fraud_config(data: dict) -> list[str]:
    """Retourne la liste des erreurs de validation (vide = OK)."""
    errors: list[str] = []
    try:
        FraudConfig(**data)
    except Exception as e:
        for err in e.errors() if hasattr(e, "errors") else [{"msg": str(e)}]:
            loc = ".".join(str(x) for x in err.get("loc", []))
            errors.append(f"{loc}: {err.get('msg', err)}")
    return errors


def load_calibrated_probas() -> dict | None:
    p = _data / "calibrated_probas.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_calibrated_probas(probas: dict) -> str:
    p = _data / "calibrated_probas.json"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(probas, f, indent=2)
    return str(p)


SIM_CONFIG_PATH   = _data / "sim_config.json"
CALIB_CONFIG_PATH = _data / "calib_config.json"

_SIM_DEFAULTS: dict = {
    "n_clients": 2000, "n_merchants": 300, "n_banks": 20,
    "n_mules": 300, "max_slots": 50, "n_steps": 720, "seed": 1000,
}

_CALIB_DEFAULTS: dict = {
    "n_clients": 500, "n_merchants": 100, "n_banks": 10,
    "n_mules": 300, "max_slots": 50,
    "target_mid": 0.23, "n_steps": 720, "n_bins": 30,
    "n_seeds_per_eval": 3, "maxiter": 30, "lr": 0.05, "spsa_c": 0.02,
}


def load_sim_config() -> dict:
    """Charge sim_config.json ; retourne les défauts si absent."""
    if not SIM_CONFIG_PATH.exists():
        return dict(_SIM_DEFAULTS)
    with open(SIM_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_sim_config(params: dict) -> str:
    """Persiste les paramètres de simulation (hors fraud_probas)."""
    with open(SIM_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)
    return str(SIM_CONFIG_PATH)


def load_calib_config() -> dict:
    """Charge calib_config.json. max_slots et n_mules sont intentionnellement
    indépendants de sim_config : la calibration utilise max_slots≥50 (volume légit
    non capé) et n_mules=800 (gradient SPSA stable avec 2 000 clients). La simulation
    utilise max_slots=3 et n_mules=3200 (réseau de mules proportionnel à 500 K clients
    pour atteindre le MID cible de 23 %).
    """
    base = dict(_CALIB_DEFAULTS)
    if CALIB_CONFIG_PATH.exists():
        with open(CALIB_CONFIG_PATH, encoding="utf-8") as f:
            base.update(json.load(f))
    return base


def save_calib_config(params: dict) -> str:
    """Persiste les paramètres SPSA."""
    with open(CALIB_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)
    return str(CALIB_CONFIG_PATH)


def list_backups() -> list[dict]:
    _ensure_backup_dir()
    backups = []
    for f in sorted(BACKUP_DIR.glob("*.json"), reverse=True):
        backups.append({
            "name": f.name,
            "path": str(f),
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups


def restore_backup(backup_name: str) -> str:
    src = BACKUP_DIR / backup_name
    if not src.exists():
        raise FileNotFoundError(f"Backup introuvable : {backup_name}")
    # backup du backup (pour ne rien perdre)
    save_fraud_config(load_fraud_config(), backup=True)
    shutil.copy2(src, FRAUD_CONFIG_PATH)
    return str(FRAUD_CONFIG_PATH)
