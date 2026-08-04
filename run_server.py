"""
run_server.py — Point d'entrée PyInstaller pour MoMTSim.

En mode développement : python run_server.py  (port 8765, sans reload)
En mode frozen       : lancé par Electron, lit MOMTSIM_PORT depuis l'env.

Stratégie de chemins :
  - MOMTSIM_BUNDLE_DIR  → fichiers read-only embarqués (paramFiles, frontend/dist)
  - MOMTSIM_DATA_DIR    → données utilisateur inscriptibles (parquets, probas)
"""

from __future__ import annotations
import os
import sys
import shutil
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FILE: Path | None = None


def _setup_logging(log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "momtsim.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.info("Logs écrits dans : %s", log_file)
    return log_file


def _uvicorn_log_config(log_file: Path) -> dict:
    """Config de logging passée à uvicorn pour que ses access logs aillent aussi dans le fichier."""
    _fmt = "%(asctime)s [%(levelname)-8s] %(name)s — %(message)s"
    _file = str(log_file)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": _fmt,
                "datefmt": "%Y-%m-%d %H:%M:%S",
                "use_colors": False,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": _file,
                "maxBytes": 5242880,
                "backupCount": 3,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn":        {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error":  {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
            "fastapi":        {"handlers": ["console", "file"], "level": "INFO", "propagate": False},
        },
    }


# ── Résolution des chemins ────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    _bundle = Path(sys._MEIPASS)
    _appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    _data = _appdata / "MoMTSim"
    _data.mkdir(parents=True, exist_ok=True)

    _LOG_FILE = _setup_logging(_data / "logs")

    _src_cfg = _bundle / "fraudScenariosConfig.json"
    _dst_cfg = _data / "fraudScenariosConfig.json"
    if not _dst_cfg.exists() and _src_cfg.exists():
        shutil.copy2(_src_cfg, _dst_cfg)

    os.environ.setdefault("MOMTSIM_BUNDLE_DIR",    str(_bundle))
    os.environ.setdefault("MOMTSIM_DATA_DIR",      str(_data))
    os.environ.setdefault("MOMTSIM_FRONTEND_DIST", str(_bundle / "frontend" / "dist"))
else:
    _project_root = Path(__file__).parent
    _LOG_FILE = _setup_logging(_project_root / "logs")

    os.environ.setdefault("MOMTSIM_BUNDLE_DIR",    str(_project_root / "config"))
    os.environ.setdefault("MOMTSIM_DATA_DIR",      str(_project_root / "config"))
    os.environ.setdefault("MOMTSIM_FRONTEND_DIST", str(_project_root / "frontend" / "dist"))

# ── Import de l'app FastAPI ───────────────────────────────────────────────────
_root = Path(__file__).parent
sys.path.insert(0, str(_root))

from backend.api import app  # noqa: E402

# ── Lancement uvicorn ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("MOMTSIM_PORT", "8765"))
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_config=_uvicorn_log_config(_LOG_FILE),
    )
