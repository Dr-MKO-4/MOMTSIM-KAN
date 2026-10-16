"""
momtsim_cli.py  Pipeline MoMTSim sans l'interface web.

Depuis le dossier MOMTSIM :
    python momtsim_cli.py etat                       ce qui existe et quoi faire ensuite
    python momtsim_cli.py calibrer                   calibration SSE/SPSA (calib_config.json)
    python momtsim_cli.py verdict                    faut-il relancer la calibration ?
    python momtsim_cli.py simuler --jeu validation   journal brut seul + contrôles
    python momtsim_cli.py generer --jeu tous         jeux entraînement/validation/test + features
    python momtsim_cli.py valider --jeu validation   relit le rapport d'un jeu généré
    python momtsim_cli.py test-rapide                vérification courte du moteur (1 à 2 min)

Aide détaillée : python momtsim_cli.py <commande> --help
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
# Mêmes dossiers que le serveur de l'interface : l'historique est partagé
os.environ.setdefault("MOMTSIM_DATA_DIR", str(ROOT / "config"))
os.environ.setdefault("MOMTSIM_BUNDLE_DIR", str(ROOT / "config"))

from progress import ConsoleProgress, setup_console, fmt_duration  # noqa: E402

CONFIG_DIR = ROOT / "config"
CALIB_CONFIG = CONFIG_DIR / "calib_config.json"
CALIB_REPORT = CONFIG_DIR / "calibration_report.json"
CALIB_CHECKPOINT = CONFIG_DIR / "calibration_checkpoint.json"
PROBAS_PATH = CONFIG_DIR / "calibrated_probas.json"
FRAUD_CONFIG = CONFIG_DIR / "fraudScenariosConfig.json"
PARAM_DIR = CONFIG_DIR / "paramFiles"
BACKUP_DIR = CONFIG_DIR / "config_backups"

# Régime de calibration du mémoire (section 3.1.2)
CALIB_DEFAULTS = {
    "n_clients": 2000, "n_merchants": 200, "n_banks": 8, "n_mules": 800, "max_slots": 50,
    "target_mid": 0.23, "n_steps": 720, "n_bins": 30, "n_seeds_per_eval": 3,
    "maxiter": 30, "lr": 0.05, "spsa_c": 0.02,
    "volume_scale": 1.0, "volume_follow": False, "gain_schedule": "constant", "n_workers": 0,
}


def _title(text: str):
    print("\n" + "=" * 78 + f"\n {text}\n" + "=" * 78)


def _load_calib_config(path: Path) -> dict:
    cfg = dict(CALIB_DEFAULTS)
    if path.exists():
        cfg.update(json.loads(path.read_text(encoding="utf-8")))
    return cfg


def _register(run_type: str, result: dict) -> str | None:
    try:
        from backend import run_registry as rr
        return rr.register_run(f"cli-{datetime.now():%Y%m%d%H%M%S}", run_type, result)
    except Exception as exc:
        print(f"[WARN] run non inscrit dans l'historique de l'interface : {exc}")
        return None


# ── calibrer ─────────────────────────────────────────────────────────────────

def cmd_calibrer(args):
    from calibration_sse import SSEFraudCalibrator, default_workers
    from calibration_report import format_report

    cfg = _load_calib_config(Path(args.config) if args.config else CALIB_CONFIG)
    for key, val in (("maxiter", args.maxiter), ("lr", args.lr), ("n_mules", args.n_mules),
                     ("n_workers", args.workers), ("gain_schedule", args.gains)):
        if val is not None:
            cfg[key] = val
    if args.volume_follow:
        cfg["volume_follow"] = True

    x0 = None
    if args.depuis_theta_etoile:
        if not PROBAS_PATH.exists():
            sys.exit("calibrated_probas.json introuvable : --depuis-theta-etoile impossible.")
        p = json.loads(PROBAS_PATH.read_text(encoding="utf-8"))
        x0 = [p["ato"], p["refund"], p["fake_credentials"], p["split_deposit"], p["smurfing_freq_mult"]]

    calib = SSEFraudCalibrator(
        param_dir=str(PARAM_DIR), fraud_config_path=str(FRAUD_CONFIG), seed=args.graine,
        n_clients=cfg["n_clients"], n_merchants=cfg["n_merchants"], n_banks=cfg["n_banks"],
        n_mules=cfg["n_mules"], target_mid=cfg["target_mid"], n_steps=cfg["n_steps"],
        n_bins=cfg["n_bins"], n_seeds_per_eval=cfg["n_seeds_per_eval"],
        max_slots_per_step=cfg["max_slots"], volume_scale=cfg.get("volume_scale", 1.0),
        volume_follow=cfg.get("volume_follow", False),
        n_workers=cfg.get("n_workers") or default_workers())

    n_sims = 3 * cfg["n_seeds_per_eval"] * cfg["maxiter"] + cfg["n_seeds_per_eval"]
    _title("Calibration SSE/SPSA des scénarios de fraude (section 3.1.6)")
    print(f"  Régime : {cfg['n_clients']} clients, {cfg['n_merchants']} marchands, {cfg['n_banks']} "
          f"banques, {cfg['n_mules']} mules, {cfg['n_steps']} pas, max_slots {cfg['max_slots']}")
    print(f"  SPSA   : K_max={cfg['maxiter']}, a={cfg['lr']}, c={cfg['spsa_c']}, gains "
          f"{cfg['gain_schedule']}, K={cfg['n_seeds_per_eval']} réplications, "
          f"volume_follow={cfg['volume_follow']}")
    print(f"  Calcul : {n_sims} simulations, {calib.n_workers} processus en parallèle")
    if CALIB_CHECKPOINT.exists() and not args.recommencer:
        print("  Un point de reprise existe : la calibration continue là où elle s'était arrêtée "
              "si la configuration est identique (--recommencer pour repartir de zéro).")
    print("  En cas d'arrêt (Ctrl+C, plantage, coupure), relancer la même commande pour reprendre.\n")

    bar = ConsoleProgress(1.0, label="Calibration")
    last_iter = {"txt": ""}

    def on_progress(frac, label, info):
        bar.update(frac, info=f"{label}{last_iter['txt']}", eta=info.get("eta_s"))

    def on_iteration(entry):
        last_iter["txt"] = f" | dernière SSE {entry['sse']:.5f}, meilleure {entry['best_sse']:.5f}"

    try:
        result = calib.calibrate(
            x0=x0, maxiter=cfg["maxiter"], lr=cfg["lr"], spsa_c=cfg["spsa_c"], verbose=False,
            progress_cb=on_progress, iteration_cb=on_iteration,
            gain_schedule=cfg["gain_schedule"], checkpoint_path=str(CALIB_CHECKPOINT),
            resume=not args.recommencer)
    except KeyboardInterrupt:
        bar.close(complete=False)
        print("\nInterrompu. Relancer la même commande reprend à la dernière itération terminée.")
        return 1
    except Exception:
        bar.close(complete=False)
        import traceback
        traceback.print_exc()
        print("\nErreur pendant la calibration. Le point de reprise est conservé : relancer la "
              "même commande reprend à la dernière itération terminée.")
        return 1
    bar.close(f"Terminé en {fmt_duration(result['elapsed_s'])}.")

    if result["cancelled"]:
        print("Calibration interrompue : rien n'est sauvegardé.")
        return 1
    if not args.ne_pas_sauver:
        if PROBAS_PATH.exists():
            BACKUP_DIR.mkdir(exist_ok=True)
            shutil.copy2(PROBAS_PATH, BACKUP_DIR / f"calibrated_probas_{datetime.now():%Y%m%d_%H%M%S}.json")
        PROBAS_PATH.write_text(json.dumps(result["probas"], indent=2), encoding="utf-8")
        CALIB_REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=float),
                                encoding="utf-8")
        CALIB_CHECKPOINT.unlink(missing_ok=True)
        folder = _register("calibration", result)
        print(f"theta* sauvegardé : {PROBAS_PATH}")
        print(f"Rapport complet   : {CALIB_REPORT}")
        if folder:
            print(f"Historique        : {folder}")
    print()
    print(format_report(result["verdict"], result))
    return 0


# ── verdict ──────────────────────────────────────────────────────────────────

def _load_result(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def cmd_verdict(args):
    from calibration_report import interpret_calibration, format_report
    path = Path(args.fichier) if args.fichier else CALIB_REPORT
    if not path.exists():
        print(f"Aucun rapport de calibration ({path}).")
        if PROBAS_PATH.exists():
            print("calibrated_probas.json existe mais vient d'une calibration antérieure à ce "
                  "rapport : impossible de l'évaluer. Relancer : python momtsim_cli.py calibrer")
        else:
            print("Lancer : python momtsim_cli.py calibrer")
        return 1
    result = _load_result(path)
    if "probas" not in result:
        sys.exit(f"{path} n'est pas un rapport de calibration.")
    report = interpret_calibration(result, fraud_config_path=str(FRAUD_CONFIG))
    if PROBAS_PATH.exists():
        current = json.loads(PROBAS_PATH.read_text(encoding="utf-8"))
        if any(abs(current.get(k, 0) - v) > 1e-9 for k, v in result["probas"].items()):
            report["checks"].insert(0, {
                "level": "attention", "title": "calibrated_probas.json différent de ce rapport",
                "detail": "Les probabilités utilisées par la génération ne sont pas celles de ce rapport.",
                "action": None})
    print(format_report(report, result))
    return 0 if report["verdict"] != "RELANCER" else 2


# ── simuler / generer ────────────────────────────────────────────────────────

def _run_dataset(name: str, with_features: bool, args) -> dict:
    import generation as gen
    label, cfg = gen.load_dataset_config(name)
    if args.steps:
        cfg["n_steps"] = args.steps
    if args.graine is not None:
        cfg["seed"] = args.graine
    raw_path = gen.resolve_path(args.sortie_brut or cfg.get("raw_output", f"data/{label}_raw.parquet"))
    feat_path = gen.resolve_path(cfg.get("output", f"data/{label}_features.parquet"))
    probas = gen.load_probas()
    sig = gen.run_signature(cfg, probas)
    raw_report_path = raw_path.with_suffix(".rapport.json")
    final_report_path = (feat_path if with_features else raw_path).with_suffix(".rapport.json")
    archive = not args.sans_archive
    refaire = getattr(args, "refaire", False)

    _title(f"Jeu {label} : {cfg['n_clients']} clients, {cfg['n_merchants']} marchands, "
           f"{cfg['n_banks']} banques, {cfg['n_mules']} mules, {cfg['n_steps']} pas, graine {cfg['seed']}")
    print(f"  volume x{cfg['volume_scale']:.3f} (n_clients / 500 000), max_slots {cfg['max_slots']}, "
          f"volume_follow={cfg['volume_follow']}")
    print(f"  probabilités : {probas if probas else 'PAR DÉFAUT (aucune calibration)'}")
    print(f"  journal brut : {raw_path}")
    if with_features:
        print(f"  features     : {feat_path}")

    # 1. Jeu déjà complet et à jour : rien à refaire (generer uniquement)
    if with_features and not refaire:
        done = gen.load_report(final_report_path)
        if done and done.get("signature") == sig and feat_path.exists():
            print(f"\n  Déjà généré le {done.get('created_at', '?')} avec ces paramètres : ignoré "
                  f"(--refaire pour régénérer).")
            report = gen.validate_simulation(done)
            print(gen.format_validation(report, label))
            return report

    # 2. Journal brut déjà complet (par exemple plantage pendant les features)
    summary = None
    if with_features and not refaire:
        raw_done = gen.load_report(raw_report_path)
        if raw_done and raw_done.get("signature") == sig and raw_path.exists():
            print(f"\n  Journal brut déjà complet ({raw_done.get('created_at', '?')}) : "
                  f"simulation sautée, calcul des features seulement.")
            summary = raw_done

    # 3. Simulation, avec reprise automatique au dernier point de sauvegarde
    if summary is None:
        resume = not args.recommencer
        work = gen.work_dir_for(raw_path)
        if resume and (work / "etat.pt").exists():
            print("\n  Une simulation interrompue de ce jeu existe : tentative de reprise "
                  "(--recommencer pour repartir de zéro).")
        bar = ConsoleProgress(cfg["n_steps"], label="Simulation")
        t0 = time.time()
        first = {"step": None}

        def on_step(step, n_steps, n_tx, n_fraud):
            if first["step"] is None:
                first["step"] = step - 1
            rate = n_fraud / n_tx if n_tx else 0.0
            speed = (step - first["step"]) / max(time.time() - t0, 1e-9)
            bar.update(step, info=f"pas {step}/{n_steps}  {n_tx:,} tx  fraude {rate:.1%}  "
                                   f"{speed:.1f} pas/s".replace(",", " "))

        try:
            summary = gen.simulate_to_parquet(cfg, probas, raw_path, progress=on_step,
                                              resume=resume, checkpoint_every=args.sauvegarde,
                                              archive=archive, log=print)
        except KeyboardInterrupt:
            bar.close(complete=False)
            print("\nInterrompu. Relancer la même commande pour reprendre au dernier point de "
                  f"sauvegarde (tous les {args.sauvegarde} pas).")
            raise
        except Exception:
            bar.close(complete=False)
            import traceback
            traceback.print_exc()
            print("\nErreur pendant la simulation. Relancer la même commande reprend au dernier "
                  "point de sauvegarde.")
            raise
        bar.close(f"Simulation terminée en {fmt_duration(summary['elapsed_s'])}"
                  + (f" (reprise au pas {summary['resumed_from']})." if summary["resumed_from"] else "."))
        summary.pop("injector", None)
        # Rapport intermédiaire : si les features plantent, la simulation n'est pas à refaire
        gen.save_report(summary, gen.validate_simulation(summary), raw_report_path)

    report = gen.validate_simulation(summary)
    if with_features:
        _title("Calcul des caractéristiques (section 3.4)")
        try:
            summary["n_feature_rows"] = gen.compute_features(raw_path, feat_path, archive=archive)
        except Exception:
            import traceback
            traceback.print_exc()
            print("\nErreur pendant le calcul des features. Le journal brut est conservé : "
                  "relancer la même commande ne refait que ce calcul.")
            raise
        summary["features_path"] = str(feat_path)
    summary["signature"] = sig
    gen.save_report(summary, report, final_report_path)
    print()
    print(gen.format_validation(report, label))
    print(f"\nRapport : {final_report_path}")
    _register("simulation", {
        "n_transactions": summary["n_transactions"], "fraud_rate": summary["fraud_rate"],
        "fraud_by_scenario": report["metrics"].get("scenario_shares", {}),
        # pas de clé parquet_path : le registre copierait le journal (plusieurs Go)
        "steps_run": summary["steps_run"], "raw_path": str(raw_path),
        "sim_params": cfg, "validation": report,
    })
    return report


def _datasets(jeu: str) -> list[str]:
    return ["entrainement", "validation", "test"] if jeu == "tous" else [jeu]


def cmd_simuler(args):
    if args.config:
        names = [args.config]
    else:
        names = _datasets(args.jeu)
    verdicts = [_run_dataset(n, with_features=False, args=args)["verdict"] for n in names]
    return 0 if all(v != "A REFAIRE" for v in verdicts) else 2


def cmd_generer(args):
    names = [args.config] if args.config else _datasets(args.jeu)
    import generation as gen
    if gen.load_probas() is None and not args.force:
        sys.exit("calibrated_probas.json introuvable : lancer d'abord la calibration "
                 "(ou --force pour générer avec les probabilités par défaut).")
    verdicts = {}
    for n in names:
        verdicts[n] = _run_dataset(n, with_features=not args.sans_features, args=args)["verdict"]
    if len(verdicts) > 1:
        _title("Bilan")
        for n, v in verdicts.items():
            print(f"  {n:<14} {v}")
    return 0 if all(v != "A REFAIRE" for v in verdicts.values()) else 2


def cmd_valider(args):
    import generation as gen
    if args.rapport:
        path = Path(args.rapport)
    else:
        _, cfg = gen.load_dataset_config(args.jeu)
        feat = gen.resolve_path(cfg["output"]).with_suffix(".rapport.json")
        raw = gen.resolve_path(cfg["raw_output"]).with_suffix(".rapport.json")
        path = feat if feat.exists() else raw
    if not path.exists():
        sys.exit(f"Aucun rapport : {path}. Générer le jeu d'abord.")
    data = json.loads(path.read_text(encoding="utf-8"))
    report = gen.validate_simulation(data)   # recalcul avec la fourchette actuelle
    print(gen.format_validation(report, path.stem.replace(".rapport", "")))
    print(f"\nGénéré le {data.get('created_at', '?')} avec {data.get('fraud_probas')}")
    if data.get("fraud_probas") and PROBAS_PATH.exists():
        cur = json.loads(PROBAS_PATH.read_text(encoding="utf-8"))
        if cur != data["fraud_probas"]:
            print("[ATTENTION] calibrated_probas.json a changé depuis : ce jeu est à régénérer.")
    return 0


# ── etat ─────────────────────────────────────────────────────────────────────

def cmd_etat(args):
    import generation as gen
    from calibration_report import interpret_calibration
    _title("État du pipeline MoMTSim")
    todo = []
    if CALIB_REPORT.exists():
        res = json.loads(CALIB_REPORT.read_text(encoding="utf-8"))
        rep = interpret_calibration(res, fraud_config_path=str(FRAUD_CONFIG))
        date = datetime.fromtimestamp(CALIB_REPORT.stat().st_mtime)
        print(f"  Calibration   : {date:%Y-%m-%d %H:%M}, verdict {rep['verdict']}")
        if rep["verdict"] == "RELANCER":
            todo.append("python momtsim_cli.py verdict      (détail)  puis  python momtsim_cli.py calibrer")
    elif PROBAS_PATH.exists():
        print("  Calibration   : calibrated_probas.json présent, sans rapport (ancienne version).")
        todo.append("python momtsim_cli.py calibrer")
    else:
        print("  Calibration   : aucune")
        todo.append("python momtsim_cli.py calibrer")
    if CALIB_CHECKPOINT.exists():
        print("  Reprise       : un point de reprise existe (python momtsim_cli.py calibrer --reprendre)")

    probas = gen.load_probas()
    for name in ("entrainement", "validation", "test"):
        _, cfg = gen.load_dataset_config(name)
        feat = gen.resolve_path(cfg["output"])
        rep_path = feat.with_suffix(".rapport.json")
        work = gen.work_dir_for(gen.resolve_path(cfg["raw_output"]))
        if (work / "etat.pt").exists():
            print(f"  Jeu {name:<12}: simulation interrompue, reprise possible au dernier point de sauvegarde")
            todo.append(f"python momtsim_cli.py generer --jeu {name}")
            continue
        if not feat.exists():
            print(f"  Jeu {name:<12}: absent")
            todo.append(f"python momtsim_cli.py generer --jeu {name}")
            continue
        if rep_path.exists():
            data = json.loads(rep_path.read_text(encoding="utf-8"))
            stale = probas is not None and data.get("fraud_probas") != probas
            v = gen.validate_simulation(data)["verdict"]
            n_tx = f"{data['n_transactions']:,}".replace(",", " ")
            print(f"  Jeu {name:<12}: {n_tx} tx, fraude {data['fraud_rate']:.1%}, "
                  f"{v}{', PROBAS CHANGÉES DEPUIS' if stale else ''}")
            if stale or v == "A REFAIRE":
                todo.append(f"python momtsim_cli.py generer --jeu {name}")
        else:
            print(f"  Jeu {name:<12}: présent, sans rapport (généré par une ancienne version)")
            todo.append(f"python momtsim_cli.py generer --jeu {name}")
    print("\nÀ faire :" if todo else "\nRien à faire : calibration et jeux à jour.")
    for t in dict.fromkeys(todo):
        print(f"  {t}")
    return 0


# ── test-rapide ──────────────────────────────────────────────────────────────

def cmd_test_rapide(args):
    """Vérifie le moteur sur un petit régime : invariants du journal, identité des
    compteurs entre mode journal complet et mode compteurs, débit."""
    import numpy as np
    from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector, DEVICE
    import generation as gen
    probas = gen.load_probas()
    n_c, n_steps = 2000, 96
    print(f"Moteur sur {DEVICE} : {n_c} clients, 200 marchands, 8 banques, 800 mules, {n_steps} pas")
    params = TorchParameters(str(PARAM_DIR), str(FRAUD_CONFIG), n_clients=n_c, seed=1000)
    counts = {}
    df = None
    for keep in (True, False):
        eng = TorchMoMTSimEngine(params, n_c, 200, 8, 800, max_slots_per_step=50, seed=7, keep_log=keep)
        inj = TorchFraudInjector(eng, params, fraud_probas=probas, seed=7)
        bar = ConsoleProgress(n_steps, label="journal" if keep else "compteurs")
        t0 = time.time()
        for s in range(n_steps):
            eng.simulate_step(s, inj)
            bar.update(s + 1, info=f"{eng.n_logged} tx")
        bar.close(f"  {time.time() - t0:.1f} s, {eng.n_logged} tx dont {eng.n_fraud_logged} frauduleuses")
        counts[keep] = eng.fraud_counts_by_step(n_steps)
        if keep:
            df = eng.to_dataframe()
            bal_clients = eng.host_balance()[:n_c]

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  [OK]     " if cond else "  [ECHEC]  ") + msg)
        ok &= bool(cond)

    check(int(df["isFraud"].sum()) == int(counts[True].sum()),
          "transactions frauduleuses du journal = compteurs par scénario")
    check(np.array_equal(counts[True], counts[False]),
          "mode compteurs (calibration) identique au mode journal à graine égale")
    check(df["fraudScenario"].dropna().isin(gen.SCEN_LABELS).all(), "scénarios valides")
    check(bool((bal_clients >= -1e-2).all()), "soldes clients >= 0 (règle CEMAC)")
    ok_rows = df[df["isSuccessful"] & ~df["action"].isin(["CASH_IN", "DEPOSIT"])]
    check(bool(((ok_rows["oldBalanceOrig"] - ok_rows["newBalanceOrig"]) >= -1e-2).all()),
          "les transactions sortantes réussies débitent l'émetteur")
    check(df["step"].is_monotonic_increasing, "journal ordonné par pas")
    # Reprise : sauvegarde à mi-parcours, rechargement, fin identique à l'original
    import io
    import torch
    eng = TorchMoMTSimEngine(params, n_c, 200, 8, 800, max_slots_per_step=50, seed=11, keep_log=False)
    inj = TorchFraudInjector(eng, params, fraud_probas=probas, seed=11)
    half = n_steps // 2
    for s in range(half):
        eng.simulate_step(s, inj)
    buf = io.BytesIO()
    torch.save({"engine": eng, "injector": inj}, buf)
    buf.seek(0)
    restored = torch.load(buf, weights_only=False)
    eng2, inj2 = restored["engine"], restored["injector"]
    for s in range(half, n_steps):
        eng.simulate_step(s, inj)
        eng2.simulate_step(s, inj2)
    check(np.array_equal(eng.fraud_counts_by_step(n_steps), eng2.fraud_counts_by_step(n_steps))
          and eng.n_logged == eng2.n_logged
          and np.array_equal(eng.host_balance(), eng2.host_balance()),
          "reprise après sauvegarde identique à une exécution sans interruption")

    present = set(df.loc[df["isFraud"], "fraudScenario"].unique())
    print(f"  scénarios présents sur {n_steps} pas : {sorted(present)}")
    print("\nMoteur OK." if ok else "\nAu moins un contrôle a échoué.")
    return 0 if ok else 1


# ─────────────────────────────────────────────────────────────────────────────

def main(argv=None):
    setup_console()
    p = argparse.ArgumentParser(description="Pipeline MoMTSim sans interface.",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrer", help="calibration SSE/SPSA")
    c.add_argument("--config", help="fichier de configuration (défaut config/calib_config.json)")
    c.add_argument("--workers", type=int, help="processus en parallèle (défaut : coeurs - 1, max 9)")
    c.add_argument("--maxiter", type=int, help="nombre d'itérations K_max")
    c.add_argument("--lr", type=float, help="pas a de SPSA")
    c.add_argument("--gains", choices=["constant", "spall"], help="gains constants (mémoire) ou décroissants")
    c.add_argument("--n-mules", type=int, help="nombre de mules du régime de calibration")
    c.add_argument("--volume-follow", action="store_true", help="injection proportionnelle au volume du pas")
    c.add_argument("--depuis-theta-etoile", action="store_true", help="partir de calibrated_probas.json")
    c.add_argument("--reprendre", action="store_true",
                   help="(par défaut) reprendre au dernier point de reprise compatible")
    c.add_argument("--recommencer", action="store_true", help="ignorer le point de reprise")
    c.add_argument("--graine", type=int, default=1000)
    c.add_argument("--ne-pas-sauver", action="store_true", help="ne pas écrire calibrated_probas.json")
    c.set_defaults(func=cmd_calibrer)

    v = sub.add_parser("verdict", help="interprète la dernière calibration")
    v.add_argument("--fichier", help="rapport à lire (défaut config/calibration_report.json)")
    v.set_defaults(func=cmd_verdict)

    for name, func, helptext in (("simuler", cmd_simuler, "journal brut + contrôles"),
                                 ("generer", cmd_generer, "journal brut + features + contrôles")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--jeu", default="validation", choices=["entrainement", "validation", "test", "tous"])
        s.add_argument("--config", help="fichier JSON de régime (remplace --jeu)")
        s.add_argument("--steps", type=int, help="nombre de pas (remplace la configuration)")
        s.add_argument("--graine", type=int)
        s.add_argument("--sortie-brut", help="chemin du journal brut")
        s.add_argument("--sans-archive", action="store_true", help="écraser sans archiver l'ancien fichier")
        s.add_argument("--recommencer", action="store_true",
                       help="ignorer la sauvegarde d'une simulation interrompue")
        s.add_argument("--sauvegarde", type=int, default=100,
                       help="pas entre deux sauvegardes de l'état (défaut 100)")
        if name == "generer":
            s.add_argument("--sans-features", action="store_true")
            s.add_argument("--force", action="store_true", help="autoriser l'absence de calibration")
            s.add_argument("--refaire", action="store_true",
                           help="régénérer même un jeu déjà complet et à jour")
        s.set_defaults(func=func)

    va = sub.add_parser("valider", help="relit le rapport d'un jeu généré")
    va.add_argument("--jeu", default="validation", choices=["entrainement", "validation", "test"])
    va.add_argument("--rapport", help="chemin d'un fichier .rapport.json")
    va.set_defaults(func=cmd_valider)

    sub.add_parser("etat", help="état du pipeline").set_defaults(func=cmd_etat)
    sub.add_parser("test-rapide", help="vérification courte du moteur").set_defaults(func=cmd_test_rapide)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
