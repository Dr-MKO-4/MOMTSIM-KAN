"""
run_server.py — Point d'entrée PyInstaller pour MoMTSim.

En mode développement : python run_server.py  (port 8765, sans reload)
En mode frozen       : lancé par Electron, lit MOMTSIM_PORT depuis l'env.

Stratégie de chemins :
  - MOMTSIM_BUNDLE_DIR  → fichiers read-only embarqués (paramFiles, frontend/dist)
  - MOMTSIM_DATA_DIR    → données utilisateur inscriptibles (CSVs, SQLite, probas)
"""

from __future__ import annotations
import os
import sys
import shutil
from pathlib import Path

# ── Résolution des chemins en mode frozen (PyInstaller) ──────────────────────
if getattr(sys, "frozen", False):
    _bundle = Path(sys._MEIPASS)
    _appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    _data = _appdata / "MoMTSim"
    _data.mkdir(parents=True, exist_ok=True)

    # Premier lancement : copier fraudScenariosConfig.json dans AppData
    # (l'utilisateur doit pouvoir le modifier via l'UI)
    _src_cfg = _bundle / "fraudScenariosConfig.json"
    _dst_cfg = _data / "fraudScenariosConfig.json"
    if not _dst_cfg.exists() and _src_cfg.exists():
        shutil.copy2(_src_cfg, _dst_cfg)

    os.environ.setdefault("MOMTSIM_BUNDLE_DIR", str(_bundle))
    os.environ.setdefault("MOMTSIM_DATA_DIR",   str(_data))
    os.environ.setdefault("MOMTSIM_FRONTEND_DIST", str(_bundle / "frontend" / "dist"))

# ── Import de l'app FastAPI (après injection des env vars) ───────────────────
_root = Path(__file__).parent
sys.path.insert(0, str(_root))

from backend.api import app  # noqa: E402  (import intentionally deferred)

# ── Lancement uvicorn ────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("MOMTSIM_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
