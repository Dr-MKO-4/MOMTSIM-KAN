"""
generer_derive.py -- Jeu derive de l'experience S3 (Grid Extension et derive), specification du 03/11.

Meme regime et meme graine de population que le jeu de test (relus dans data/test_features.rapport.json,
graine 1002) ; seul le Split Deposit change, en fragments plus irreguliers :
    split_deposit.epsilon_max      5 000 -> 20 000
    split_deposit.T_split_max_sec    120 ->    600
La configuration modifiee est une copie (config/fraudScenariosConfig_derive.json) : le fichier d'origine,
les probabilites calibrees et le code ne changent pas.

Sorties : data/derive_raw.parquet, data/derive_features.parquet et leurs .rapport.json.
Reprise : relancer la meme commande reprend la simulation au dernier point de sauvegarde.

Depuis le dossier MOMTSIM :
    python generer_derive.py
Puis envoyer data/derive_features.parquet sur l'instance (commande affichee a la fin).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import generation as gen  # noqa: E402

CHANGEMENTS = {"epsilon_max": 20_000, "T_split_max_sec": 600}
CONFIG_DERIVE = ROOT / "config" / "fraudScenariosConfig_derive.json"


def ecrire_config() -> Path:
    cfg = json.loads(gen.FRAUD_CONFIG_PATH.read_text(encoding="utf-8"))
    avant = {k: cfg["split_deposit"][k] for k in CHANGEMENTS}
    if avant != {"epsilon_max": 5000, "T_split_max_sec": 120}:
        sys.exit(f"Valeurs de depart inattendues {avant} : la specification suppose 5 000 et 120.")
    cfg["split_deposit"].update(CHANGEMENTS)
    CONFIG_DERIVE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Configuration derivee : {CONFIG_DERIVE} ({avant} -> {CHANGEMENTS})")
    return CONFIG_DERIVE


def main():
    # Regime exact du jeu de test, relu dans son rapport (et non dans les valeurs par defaut du code)
    rapport_test = gen.resolve_path("data/test_features.rapport.json")
    cfg = gen.resolve_config(json.loads(rapport_test.read_text(encoding="utf-8"))["config"])
    if cfg["seed"] != 1002:
        sys.exit(f"Graine du jeu de test inattendue : {cfg['seed']}")
    cfg["raw_output"], cfg["output"] = "data/derive_raw.parquet", "data/derive_features.parquet"
    raw, feat = gen.resolve_path(cfg["raw_output"]), gen.resolve_path(cfg["output"])
    probas = gen.load_probas()
    if probas is None:
        sys.exit("calibrated_probas.json introuvable.")
    fraude = ecrire_config()
    print(f"Regime : {cfg}")

    if not raw.with_suffix(".rapport.json").exists() or not raw.exists():
        def suivi(step, n, n_tx, n_f):
            if step % 50 == 0 or step == n:
                print(f"  pas {step}/{n}  {n_tx:,} tx  fraude {n_f / max(n_tx, 1):.1%}", flush=True)
        resume = gen.simulate_to_parquet(cfg, probas, raw, progress=suivi, fraud_config_path=fraude,
                                         resume=True, checkpoint_every=100)
        resume.pop("injector", None)
        resume["config"] = cfg
        resume["fraud_config"] = str(fraude)
        gen.save_report(resume, gen.validate_simulation(resume), raw.with_suffix(".rapport.json"))
    else:
        resume = json.loads(raw.with_suffix(".rapport.json").read_text(encoding="utf-8"))
        print("Journal brut deja present : calcul des features seulement.")
    rapport = gen.validate_simulation(resume)
    resume["n_feature_rows"] = gen.compute_features(raw, feat)
    resume["features_path"] = str(feat)
    gen.save_report(resume, rapport, feat.with_suffix(".rapport.json"))
    print(gen.format_validation(rapport, "derive"))
    print("\nEnvoi sur l'instance MKAN (IP du moment) :\n"
          f"  scp -i ~/.ssh/aws-key.pem \"{feat}\" ubuntu@<IP>:Modelisation/data/derive_features.parquet")


if __name__ == "__main__":
    main()
