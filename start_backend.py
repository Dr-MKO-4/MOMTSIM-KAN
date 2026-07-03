"""
start_backend.py — Lance le serveur FastAPI MoMTSim-KAN.
Usage : python start_backend.py
"""

import sys
from pathlib import Path

# Ajouter le répertoire courant au path Python pour que `backend` soit importable
sys.path.insert(0, str(Path(__file__).parent))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "backend.api:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[str(Path(__file__).parent)],
        log_level="info",
    )
