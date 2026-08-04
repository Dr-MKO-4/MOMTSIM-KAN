from __future__ import annotations
from pathlib import Path
import json
import os
from datetime import datetime


def _path() -> Path:
    return Path(os.environ.get("MOMTSIM_DATA_DIR", str(Path(__file__).parent.parent / "config"))) / "test_cases.json"


def load_test_cases() -> list:
    p = _path()
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_test_case(name: str, params: dict, description: str = "") -> dict:
    cases = load_test_cases()
    case = {
        "id": name.lower().replace(" ", "_") + "_" + datetime.now().strftime("%Y%m%d%H%M%S"),
        "name": name,
        "description": description,
        "params": params,
        "created_at": datetime.now().isoformat(),
    }
    cases.append(case)
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cases, f, indent=2, ensure_ascii=False)
    return case


def delete_test_case(case_id: str) -> bool:
    cases = load_test_cases()
    new_cases = [c for c in cases if c["id"] != case_id]
    if len(new_cases) == len(cases):
        return False
    p = _path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(new_cases, f, indent=2, ensure_ascii=False)
    return True
