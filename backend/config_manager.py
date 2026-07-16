"""
backend/config_manager.py — Lecture / écriture / backup du fichier fraudScenariosConfig.json.
"""

from __future__ import annotations
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from .schemas import FraudConfig, SimulationParams

_data = Path(os.environ.get("MOMTSIM_DATA_DIR", str(Path(__file__).parent.parent)))

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
