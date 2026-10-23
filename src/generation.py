"""
generation.py  Régimes d'exécution du mémoire (section 3.1.2) et génération des
jeux de données : simulation écrite par blocs de 50 pas, calcul des 12
caractéristiques, rapport de validation du jeu produit.

Régimes (section 3.1.2) :
  - calibration  : 2 000 clients, 200 marchands, 8 banques, 800 mules, 720 pas ;
  - entraînement : 500 000 clients, 12 000 marchands, 8 banques, 2 100 mules,
                   1 440 pas, graine 1000 ;
  - validation / test : 150 000 clients, 3 600 marchands, 8 banques, 630 mules,
                   1 440 pas, graines 1001 et 1002.
Marchands (2,4 %) et mules (0,42 %) sont dans la même proportion des clients dans
les trois jeux, et le volume horaire est proportionné à la population simulée
(facteur n_clients / 500 000, population de référence des volumes horaires).
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import numpy as np

SRC = Path(__file__).parent
MOMTSIM_ROOT = SRC.parent
MODELISATION_ROOT = MOMTSIM_ROOT.parent
PARAM_DIR = MOMTSIM_ROOT / "config" / "paramFiles"
FRAUD_CONFIG_PATH = MOMTSIM_ROOT / "config" / "fraudScenariosConfig.json"
PROBAS_PATH = MOMTSIM_ROOT / "config" / "calibrated_probas.json"
N_CLIENTS_REF = 500_000
SCEN_LABELS = ["ATO", "REFUND", "FAKE_CRED", "SPLIT_DEP", "SMURFING"]
ACTIONS = ["CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER", "DEPOSIT"]

# Valeurs du mémoire (section 3.1.2), utilisées si le fichier de configuration manque
REGIMES = {
    "entrainement": {"n_clients": 500_000, "n_merchants": 12_000, "n_banks": 8, "n_mules": 2_100,
                     "n_steps": 1_440, "max_slots": 3, "seed": 1000,
                     "raw_output": "MOMTSIM/config/rawLog_torch.parquet",
                     "output": "MOMTSIM/config/featuresLog.parquet"},
    "validation":   {"n_clients": 150_000, "n_merchants": 3_600, "n_banks": 8, "n_mules": 630,
                     "n_steps": 1_440, "max_slots": 3, "seed": 1001,
                     "raw_output": "data/val_raw.parquet",
                     "output": "data/val_features.parquet"},
    "test":         {"n_clients": 150_000, "n_merchants": 3_600, "n_banks": 8, "n_mules": 630,
                     "n_steps": 1_440, "max_slots": 3, "seed": 1002,
                     "raw_output": "data/test_raw.parquet",
                     "output": "data/test_features.parquet"},
}
CONFIG_FILES = {"entrainement": "sim_config_train.json", "validation": "sim_config_val.json",
                "test": "sim_config_test.json"}


def load_dataset_config(name_or_path: str) -> tuple[str, dict]:
    """Nom de jeu (entrainement/validation/test) ou chemin d'un JSON de configuration."""
    if name_or_path in REGIMES:
        path = MODELISATION_ROOT / CONFIG_FILES[name_or_path]
        cfg = dict(REGIMES[name_or_path])
        if path.exists():
            cfg.update(json.loads(path.read_text(encoding="utf-8")))
        return name_or_path, resolve_config(cfg)
    path = Path(name_or_path)
    if not path.is_absolute():
        path = (MODELISATION_ROOT / path) if (MODELISATION_ROOT / path).exists() else path.resolve()
    cfg = json.loads(path.read_text(encoding="utf-8"))
    return path.stem, resolve_config(cfg)


def resolve_config(cfg: dict) -> dict:
    cfg = dict(cfg)
    cfg.setdefault("n_banks", 8)
    cfg.setdefault("max_slots", 3)
    cfg.setdefault("seed", 1000)
    cfg.setdefault("volume_follow", False)
    # Volume horaire proportionné à la population simulée (section 3.1.2)
    if cfg.get("volume_scale") is None:
        cfg["volume_scale"] = cfg["n_clients"] / cfg.get("n_clients_ref", N_CLIENTS_REF)
    return cfg


def resolve_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else MODELISATION_ROOT / p


def load_probas(path: Path = PROBAS_PATH) -> dict | None:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def archive_existing(path: Path) -> Path | None:
    """Déplace un fichier existant dans <dossier>/archives/ avant de l'écraser."""
    if not path.exists():
        return None
    dest_dir = path.parent / "archives"
    dest_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{path.stem}_{ts}{path.suffix}"
    shutil.move(str(path), str(dest))
    return dest


# ── simulation ───────────────────────────────────────────────────────────────

def _raw_schema():
    import pyarrow as pa
    f32, i32 = pa.float32(), pa.int32()
    return pa.schema([
        ("step", i32), ("time_s", f32), ("action", pa.string()), ("amount", f32),
        ("nameOrig", i32), ("nameDest", i32),
        ("oldBalanceOrig", f32), ("newBalanceOrig", f32),
        ("oldBalanceDest", f32), ("newBalanceDest", f32),
        ("isSuccessful", pa.bool_()), ("isFraud", pa.bool_()), ("isFlaggedFraud", pa.bool_()),
        ("fraudScenario", pa.string()),
    ])


def run_signature(cfg: dict, fraud_probas: dict | None, param_dir=PARAM_DIR,
                  fraud_config_path=FRAUD_CONFIG_PATH) -> str:
    """Empreinte de tout ce qui détermine un jeu : régime, θ*, scénarios, fichiers de
    calibration, code du moteur. Une reprise n'est acceptée que si elle est identique."""
    import hashlib
    from calibration_sse import file_fingerprint
    keys = ("n_clients", "n_merchants", "n_banks", "n_mules", "n_steps", "max_slots", "seed",
            "volume_scale", "volume_follow")
    payload = {k: cfg.get(k) for k in keys}
    payload["probas"] = fraud_probas
    payload["files"] = [file_fingerprint([fraud_config_path]), file_fingerprint([param_dir]),
                        file_fingerprint([SRC / "momtsim_torch.py"])]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=float).encode()).hexdigest()[:16]


def work_dir_for(raw_path: Path) -> Path:
    return raw_path.with_name(raw_path.stem + ".en_cours")


def simulate_to_parquet(cfg: dict, fraud_probas: dict | None, raw_path: Path,
                        progress=None, cancel=None, block_steps: int = 50,
                        param_dir: str | Path = PARAM_DIR,
                        fraud_config_path: str | Path = FRAUD_CONFIG_PATH,
                        resume: bool = False, checkpoint_every: int = 100,
                        archive: bool = False, log=print) -> dict:
    """Simule le régime `cfg` et écrit le journal brut par blocs de `block_steps` pas.

    Protection contre les interruptions : les blocs sont écrits dans un dossier
    <journal>.en_cours/ et l'état complet de la simulation (soldes, historiques,
    transactions différées, réseaux de mules, générateurs aléatoires) y est sauvegardé
    tous les `checkpoint_every` pas. Avec resume=True, une simulation interrompue
    (plantage, Ctrl+C, coupure) repart du dernier point de sauvegarde, à l'identique,
    si le régime, θ*, les scénarios et le code n'ont pas changé. Le journal final
    n'est assemblé qu'à la fin : un fichier présent est toujours complet.

    progress(step, n_steps, n_tx, n_fraud) est appelé à chaque pas.
    Retourne un résumé ; résumé["injector"] donne accès au suivi par scénario.
    """
    import os
    import pyarrow as pa
    import pyarrow.parquet as pq
    import torch
    from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector

    t0 = time.time()
    n_steps = int(cfg["n_steps"])
    checkpoint_every = max(block_steps, (int(checkpoint_every) // block_steps) * block_steps)
    sig = run_signature(cfg, fraud_probas, param_dir, fraud_config_path)
    work = work_dir_for(raw_path)
    state_path = work / "etat.pt"
    schema = _raw_schema()

    engine = injector = None
    start = 0
    if resume and state_path.exists():
        try:
            state = torch.load(str(state_path), weights_only=False)
        except Exception as exc:
            state = None
            log(f"[REPRISE] point de sauvegarde illisible ({exc}) : nouveau départ.")
        if state is not None and state.get("signature") == sig:
            engine, injector, start = state["engine"], state["injector"], int(state["next_step"])
            for part in work.glob("part_*.parquet"):
                if int(part.stem.split("_")[1]) > start:
                    part.unlink()   # bloc écrit après le dernier point de sauvegarde
            log(f"[REPRISE] reprise au pas {start}/{n_steps} (sauvegarde du "
                f"{state.get('saved_at', '?')}).")
        elif state is not None:
            log("[REPRISE] la sauvegarde vient d'un autre régime, d'autres probabilités ou d'un "
                "autre code : nouveau départ.")
    if engine is None:
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True)
        params = TorchParameters(str(param_dir), str(fraud_config_path), n_clients=cfg["n_clients"],
                                 seed=cfg["seed"], volume_scale=cfg["volume_scale"])
        engine = TorchMoMTSimEngine(params, n_clients=cfg["n_clients"], n_merchants=cfg["n_merchants"],
                                    n_banks=cfg["n_banks"], n_mules=cfg["n_mules"],
                                    max_slots_per_step=cfg["max_slots"], seed=cfg["seed"])
        injector = TorchFraudInjector(engine, params, fraud_probas=fraud_probas, seed=cfg["seed"],
                                      volume_follow=cfg.get("volume_follow", False))
    params = engine.params
    (work / "etat.json").write_text(json.dumps({"signature": sig, "config": cfg,
                                                "fraud_probas": fraud_probas}, default=float),
                                    encoding="utf-8")

    def save_state(next_step: int):
        tmp = work / "etat.tmp"
        torch.save({"signature": sig, "next_step": next_step, "engine": engine,
                    "injector": injector, "saved_at": datetime.now().isoformat(timespec="seconds")},
                   str(tmp))
        os.replace(tmp, state_path)   # écriture atomique : l'ancienne sauvegarde reste valide

    cancelled = False
    steps_done = start
    t_journal = t_ckpt = 0.0
    for step in range(start, n_steps):
        if cancel is not None and cancel():
            cancelled = True
            break
        engine.simulate_step(step, injector)
        steps_done = step + 1
        if steps_done % block_steps == 0 or steps_done == n_steps:
            tj = time.perf_counter()
            df = engine.flush_log()
            table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
            pq.write_table(table, str(work / f"part_{steps_done:07d}.parquet"), compression="snappy")
            t_journal += time.perf_counter() - tj
            if steps_done % checkpoint_every == 0 and steps_done < n_steps:
                tc = time.perf_counter()
                save_state(steps_done)
                t_ckpt += time.perf_counter() - tc
        if progress is not None:
            progress(steps_done, n_steps, engine.n_logged, engine.n_fraud_logged)

    if not cancelled:
        # Assemblage des blocs, puis remplacement atomique du journal final
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        parts = sorted(work.glob("part_*.parquet"), key=lambda q: int(q.stem.split("_")[1]))
        tmp = raw_path.with_name(raw_path.stem + ".assemblage.parquet")
        with pq.ParquetWriter(str(tmp), schema, compression="snappy") as writer:
            for part in parts:
                writer.write_table(pq.read_table(str(part)).cast(schema))
        if archive:
            moved = archive_existing(raw_path)
            if moved:
                log(f"Ancien journal archivé : {moved}")
        tmp.replace(raw_path)
        shutil.rmtree(work, ignore_errors=True)

    fraud = engine.fraud_counts_by_step(max(steps_done, 1))
    legit = engine.legit_counts_by_step(max(steps_done, 1))
    n_fraud = int(fraud.sum())
    n_tx = int(engine.n_logged)
    return {
        "cancelled": cancelled, "steps_run": steps_done, "resumed_from": start,
        "elapsed_s": time.time() - t0, "signature": sig,
        "timings": {**engine.timing_report(), "journal": t_journal, "sauvegardes": t_ckpt,
                    "device": str(engine.balance.device)},
        "n_transactions": n_tx, "n_fraud": n_fraud,
        "fraud_rate": n_fraud / n_tx if n_tx else 0.0,
        "fraud_counts": dict(zip(SCEN_LABELS, fraud.sum(axis=1).astype(int).tolist())),
        "fraud_by_step": fraud.tolist(),
        "legit_by_step": legit.tolist(),
        "legit_model_by_action": engine.legit_model_counts_by_action(max(steps_done, 1))[:len(ACTIONS)].tolist(),
        "reference_by_action": params.reference_counts_by_action().tolist(),
        "raw_path": str(raw_path),
        "config": {k: v for k, v in cfg.items()},
        "fraud_probas": fraud_probas,
        "injector": injector,
    }


def compute_features(raw_path: Path, features_path: Path, log=print, archive: bool = False) -> int:
    """Calcule les 12 caractéristiques. Le fichier final n'apparaît qu'une fois écrit
    en entier : en cas de plantage, le journal brut est conservé et seul ce calcul est
    à refaire."""
    import pandas as pd
    from features import FeatureEngineer
    log(f"Lecture du journal brut : {raw_path}")
    df_raw = pd.read_parquet(raw_path)
    log(f"Calcul des 12 caractéristiques sur {len(df_raw):,} transactions (opération longue, "
        f"sans progression intermédiaire)...".replace(",", " "))
    t0 = time.time()
    df_feat = FeatureEngineer(df_raw).compute_all()
    del df_raw
    features_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = features_path.with_name(features_path.stem + ".ecriture.parquet")
    df_feat.to_parquet(str(tmp), index=False)
    if archive:
        moved = archive_existing(features_path)
        if moved:
            log(f"Anciennes features archivées : {moved}")
    tmp.replace(features_path)
    log(f"Caractéristiques écrites en {time.time() - t0:.0f} s : {features_path}")
    return len(df_feat)


def load_report(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


# ── validation du jeu produit ────────────────────────────────────────────────

def _target_range() -> tuple[float, float]:
    try:
        g = json.loads(FRAUD_CONFIG_PATH.read_text(encoding="utf-8")).get("global", {})
        return float(g.get("fraud_target_min", 0.20)), float(g.get("fraud_target_max", 0.26))
    except Exception:
        return 0.20, 0.26


def validate_simulation(summary: dict) -> dict:
    """Contrôles d'un jeu simulé : taux de fraude, équirépartition, stabilité dans le
    temps, fidélité du volume légitime au profil de référence de MoMTSim (SSE et
    NRMSE par type d'action, méthode d'Azamuke et al., 2024), proportions du régime."""
    checks = []

    def add(level, title, detail, action=None):
        checks.append({"level": level, "title": title, "detail": detail, "action": action})

    lo_t, hi_t = _target_range()
    cfg = summary["config"]
    fr = summary["fraud_rate"]
    metrics = {"fraud_rate": fr, "target_range": [lo_t, hi_t],
               "n_transactions": summary["n_transactions"], "n_fraud": summary["n_fraud"]}

    if summary.get("cancelled"):
        add("bloquant", "Simulation interrompue",
            f"{summary['steps_run']} pas simulés sur {cfg['n_steps']}.", "Relancer la génération.")

    if not summary.get("fraud_probas"):
        add("bloquant", "Probabilités calibrées absentes",
            "calibrated_probas.json introuvable : probabilités par défaut utilisées.",
            "Lancer la calibration avant la génération.")

    if lo_t <= fr <= hi_t:
        add("ok", "Taux de fraude dans la fourchette",
            f"{fr:.2%} des transactions sont frauduleuses (fourchette {lo_t:.0%} à {hi_t:.0%}).")
    else:
        mid = (lo_t + hi_t) / 2
        odds_t, odds = mid / (1 - mid), fr / max(1e-9, 1 - fr)
        sugg = int(round(cfg["n_mules"] * odds_t / odds)) if odds > 0 else None
        add("bloquant", "Taux de fraude hors de la fourchette",
            f"{fr:.2%} des transactions sont frauduleuses (fourchette {lo_t:.0%} à {hi_t:.0%}).",
            f"Ajuster n_mules (estimation au premier ordre : {sugg} au lieu de {cfg['n_mules']}) "
            f"dans le fichier de configuration du jeu, puis régénérer." if sugg else None)

    counts = np.array([summary["fraud_counts"][s] for s in SCEN_LABELS], dtype=float)
    if counts.sum() > 0:
        shares = counts / counts.sum()
        metrics["scenario_shares"] = dict(zip(SCEN_LABELS, shares.tolist()))
        missing = [s for s, c in zip(SCEN_LABELS, counts) if c == 0]
        if missing:
            add("bloquant", "Scénario absent du jeu", "Aucune transaction pour : " + ", ".join(missing) + ".",
                "Vérifier calibrated_probas.json et fraudScenariosConfig.json.")
        off = [f"{s} {v:.0%}" for s, v in zip(SCEN_LABELS, shares) if s != "FAKE_CRED" and abs(v - 0.2) > 0.05]
        if off:
            add("attention", "Répartition entre scénarios éloignée de l'équirépartition",
                "Parts de la fraude (cible 20 % chacun) : " + ", ".join(off) + ".")
        if shares[2] < 0.15:
            add("info", "FAKE_CRED sous sa part égale",
                f"{shares[2]:.1%} de la fraude : plafond structurel du réservoir de comptes dormants "
                f"(un nouveau compte par pas au plus, 200 comptes).")

    fraud = np.array(summary["fraud_by_step"], dtype=float).sum(axis=0)
    legit = np.array(summary["legit_by_step"], dtype=float)
    n_days = len(fraud) // 24
    if n_days:
        f_d = fraud[:n_days * 24].reshape(n_days, 24).sum(axis=1)
        l_d = legit[:n_days * 24].reshape(n_days, 24).sum(axis=1)
        daily = np.divide(f_d, f_d + l_d, out=np.zeros_like(f_d), where=(f_d + l_d) > 0)
        inside = int(((daily >= lo_t) & (daily <= hi_t)).sum())
        metrics["daily_fraud_rate"] = daily.tolist()
        metrics["days_in_range"] = inside
        if inside < 0.5 * n_days:
            add("attention", "Taux de fraude très variable d'un jour à l'autre",
                f"Taux journalier de {daily.min():.0%} à {daily.max():.0%} ; {inside}/{n_days} jours "
                f"dans la fourchette. Le volume légitime suit le profil horaire de MoMTSim alors que "
                f"le nombre de tirages d'injection est constant.",
                None if cfg.get("volume_follow") else
                "Option volume_follow = true (injection proportionnelle au volume du pas) : choix "
                "méthodologique à appliquer aussi à la calibration et à décrire dans le mémoire.")

    sim = np.array(summary["legit_model_by_action"], dtype=float)
    ref = np.array(summary["reference_by_action"], dtype=float)
    T = sim.shape[1]
    if T:
        n_cycles = int(np.ceil(T / 720))
        folded = np.zeros((sim.shape[0], 720))
        cover = np.zeros(720)
        for c in range(n_cycles):
            seg = sim[:, c * 720:(c + 1) * 720]
            folded[:, :seg.shape[1]] += seg
            cover[:seg.shape[1]] += 1
        folded = folded / np.maximum(cover, 1)
        used = cover > 0
        fid = {}
        for j, a in enumerate(ACTIONS):
            r, s = ref[j, used], folded[j, used]
            if r.sum() <= 0:
                continue
            sse = float(((r - s) ** 2).sum())
            nrmse = float(np.sqrt(((r - s) ** 2).mean()) / max(r.mean(), 1e-9))
            fid[a] = {"sse": sse, "nrmse": nrmse, "volume_ratio": float(s.sum() / r.sum())}
        metrics["legit_fidelity"] = fid
        ratio = float(folded[:, used].sum() / max(ref[:, used].sum(), 1e-9))
        metrics["legit_volume_ratio"] = ratio
        worst = sorted(fid.items(), key=lambda kv: -kv[1]["nrmse"])[:3]
        detail = (f"Volume légitime simulé / profil de référence : {ratio:.0%}. NRMSE par action "
                  "(profil horaire moyen par cycle de 720 pas) : "
                  + ", ".join(f"{a} {v['nrmse']:.2f}" for a, v in fid.items()) + ".")
        level = "attention" if worst and worst[0][1]["nrmse"] > 0.5 else "info"
        add(level, "Fidélité du volume légitime au profil MoMTSim", detail,
            "Les écarts viennent des transactions refusées faute de solde et du plafond max_slots ; "
            "à examiner si une action s'écarte fortement (seuil de travail NRMSE 0,5)."
            if level == "attention" else None)

    n_c = cfg["n_clients"]
    pm, pu = cfg["n_merchants"] / n_c, cfg["n_mules"] / n_c
    metrics["merchant_ratio"], metrics["mule_ratio"] = pm, pu
    if abs(pm - 0.024) > 0.002 or abs(pu - 0.0042) > 0.0004:
        add("info", "Proportions du régime différentes du mémoire",
            f"Marchands {pm:.2%} et mules {pu:.2%} des clients (mémoire : 2,4 % et 0,42 %).")

    levels = [c["level"] for c in checks]
    verdict = "A REFAIRE" if "bloquant" in levels else ("ACCEPTABLE" if "attention" in levels else "OK")
    return {"verdict": verdict, "checks": checks, "metrics": metrics}


def format_validation(report: dict, name: str = "", width: int = 78) -> str:
    import textwrap
    tag = {"bloquant": "[BLOQUANT]", "attention": "[ATTENTION]", "info": "[INFO]", "ok": "[OK]"}
    m = report["metrics"]
    lines = ["=" * width, f" JEU {name} : {report['verdict']}".rstrip(), "=" * width,
             f"  Transactions     {m['n_transactions']:,}".replace(",", " "),
             f"  Frauduleuses     {m['n_fraud']:,}  ({m['fraud_rate']:.2%})".replace(",", " ")]
    if m.get("scenario_shares"):
        lines.append("  Parts : " + ", ".join(f"{k} {v:.0%}" for k, v in m["scenario_shares"].items()))
    lines.append("")
    for c in report["checks"]:
        lines += textwrap.wrap(f"{tag[c['level']]} {c['title']}", width)
        lines += textwrap.wrap(c["detail"], width, initial_indent="    ", subsequent_indent="    ")
        if c.get("action"):
            lines += textwrap.wrap("-> " + c["action"], width, initial_indent="    ",
                                   subsequent_indent="       ")
    return "\n".join(lines)


def save_report(summary: dict, report: dict, path: Path) -> None:
    data = {k: v for k, v in summary.items() if k != "injector"}
    data["validation"] = report
    data["created_at"] = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
