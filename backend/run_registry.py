"""
backend/run_registry.py — Persistance SQLite des runs MoMTSim-KAN.
Table unique : runs(id TEXT PK, run_type TEXT, timestamp TEXT, folder TEXT, summary JSON).
Le dossier runs/ est créé à côté de ce fichier si absent.
"""

from __future__ import annotations
import os
import sqlite3
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

_data     = Path(os.environ.get("MOMTSIM_DATA_DIR", str(Path(__file__).parent.parent)))
_RUNS_DIR = _data / "runs"
_DB_PATH  = _RUNS_DIR / "registry.db"


def _connect() -> sqlite3.Connection:
    _RUNS_DIR.mkdir(exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id          TEXT PRIMARY KEY,
            run_type    TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            folder      TEXT NOT NULL,
            summary_json TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def register_run(job_id: str, run_type: str, result: dict) -> str:
    """
    Sauvegarde un run terminé :
    - crée runs/<timestamp>_<type>/ avec les CSV et métadonnées
    - insère une ligne dans la DB SQLite
    Retourne le chemin du dossier créé.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    folder_name = f"{ts}_{run_type}"
    folder_path = _RUNS_DIR / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    # Copier les CSV produits si présents
    csv_key = "csv_path"
    if csv_key in result and result[csv_key]:
        src = Path(result[csv_key])
        if src.exists():
            shutil.copy2(src, folder_path / src.name)

    # Sauvegarder les métadonnées (sans les HTML Plotly — trop lourds)
    meta = {k: v for k, v in result.items() if k != "charts"}
    meta["job_id"] = job_id
    meta["run_type"] = run_type
    meta["timestamp"] = ts
    (folder_path / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # Résumé court pour la liste (sans charts)
    summary = {
        "n_transactions": result.get("n_transactions"),
        "fraud_rate":     result.get("fraud_rate"),
        "fraud_by_scenario": result.get("fraud_by_scenario"),
        "n_rows":         result.get("n_rows"),
        "n_features":     result.get("n_features"),
        "decision":       result.get("decision"),
        "VE2":            result.get("VE2"),
        "J_Fisher":       result.get("J_Fisher"),
        "D_KS_mean":      result.get("D_KS_mean"),
        "sse_final":      result.get("sse_final"),
        "converged":      result.get("converged"),
        "plain_summary":  result.get("plain_summary"),
    }
    summary = {k: v for k, v in summary.items() if v is not None}

    con = _connect()
    try:
        con.execute(
            "INSERT OR REPLACE INTO runs (id, run_type, timestamp, folder, summary_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (job_id, run_type, ts, str(folder_path), json.dumps(summary, ensure_ascii=False))
        )
        con.commit()
    finally:
        con.close()

    return str(folder_path)


def list_runs(run_type: str | None = None, limit: int = 50) -> list[dict]:
    """Liste les runs enregistrés, du plus récent au plus ancien."""
    con = _connect()
    try:
        if run_type:
            rows = con.execute(
                "SELECT * FROM runs WHERE run_type=? ORDER BY timestamp DESC LIMIT ?",
                (run_type, limit)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {
                "id": r["id"],
                "run_type": r["run_type"],
                "timestamp": r["timestamp"],
                "folder": r["folder"],
                "summary": json.loads(r["summary_json"]),
            }
            for r in rows
        ]
    finally:
        con.close()


def get_run(job_id: str) -> dict | None:
    """Retourne le détail d'un run par job_id, ou None si introuvable."""
    con = _connect()
    try:
        row = con.execute("SELECT * FROM runs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        folder = Path(row["folder"])
        meta = {}
        meta_file = folder / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        return {
            "id": row["id"],
            "run_type": row["run_type"],
            "timestamp": row["timestamp"],
            "folder": row["folder"],
            "summary": json.loads(row["summary_json"]),
            "metadata": meta,
        }
    finally:
        con.close()


def delete_run(job_id: str) -> bool:
    """Supprime un run de la DB et son dossier. Retourne True si trouvé."""
    con = _connect()
    try:
        row = con.execute("SELECT folder FROM runs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return False
        folder = Path(row["folder"])
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
        con.execute("DELETE FROM runs WHERE id=?", (job_id,))
        con.commit()
        return True
    finally:
        con.close()
