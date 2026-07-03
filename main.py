"""
main.py — Orchestrateur du pipeline MoMTSim-KAN (version torch).
Équivalent script de la cellule 7 du notebook momtsim_kan_pipeline.ipynb.

Usage :
    python main.py                          # simulation complète (probas par défaut)
    python main.py --calibrate              # calibration SSE/SPSA puis simulation
    python main.py --probas calibrated_probas.json  # simulation avec probas calibrées
"""

import argparse
import json
import os

import numpy as np
import pandas as pd
import torch

from momtsim_torch import TorchParameters, TorchMoMTSimEngine, TorchFraudInjector
from features import FeatureEngineer

PARAM_DIR = "./paramFiles"
FRAUD_CONFIG_PATH = "./fraudScenariosConfig.json"
SEED = 1000
N_CLIENTS = 2000
N_MERCHANTS = 300
N_BANKS = 20
N_MULES = 60
N_STEPS = 720
MAX_SLOTS = 6


# ---------------------------------------------------------------------------
def run_simulation(fraud_probas: dict | None = None, verbose: bool = True) -> pd.DataFrame:
    """Lance la simulation complète et retourne le DataFrame brut."""
    params = TorchParameters(PARAM_DIR, FRAUD_CONFIG_PATH, n_clients=N_CLIENTS, seed=SEED)
    engine = TorchMoMTSimEngine(
        params, n_clients=N_CLIENTS, n_merchants=N_MERCHANTS,
        n_banks=N_BANKS, n_mules=N_MULES, max_slots_per_step=MAX_SLOTS, seed=SEED)
    injector = TorchFraudInjector(engine, params, fraud_probas=fraud_probas, seed=SEED)

    for step in range(N_STEPS):
        n_tx_target = params.step_target_count[step]
        n_tx_per_client = torch.distributions.Binomial(
            total_count=n_tx_target.clamp(min=0),
            probs=params.client_weight.clamp(0, 1)
        ).sample()
        n_tx_per_client = torch.clamp(n_tx_per_client, max=engine.max_slots).long()

        for slot in range(engine.max_slots):
            slot_mask = n_tx_per_client > slot
            if slot_mask.any():
                engine._run_step_slot(step, slot_mask)

        injector.inject(step)

        if verbose and step % 50 == 0:
            print(f"step {step}/{N_STEPS} — {len(engine.log_step)} tx cumulées "
                  f"({sum(engine.log_is_fraud)} frauduleuses)", flush=True)

    return engine.to_dataframe()


# ---------------------------------------------------------------------------
def run_calibration() -> dict:
    """Lance la calibration SSE/SPSA (population réduite pour la vitesse)."""
    from calibration_sse import SSEFraudCalibrator

    calib = SSEFraudCalibrator(
        param_dir=PARAM_DIR, fraud_config_path=FRAUD_CONFIG_PATH,
        seed=SEED, n_clients=500, n_merchants=100, n_banks=10, n_mules=30,
        target_mid=0.23, n_steps=N_STEPS, n_bins=30, n_seeds_per_eval=3)

    result = calib.calibrate(maxiter=25)
    print("\nProbas calibrées :", result["probas"])
    print("SSE final :", result["sse_final"])

    with open("calibrated_probas.json", "w", encoding="utf-8") as f:
        json.dump(result["probas"], f, indent=2)
    print("Sauvegardé dans calibrated_probas.json")
    return result["probas"]


# ---------------------------------------------------------------------------
def run_feature_engineering(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Calcule les 12 features (section 3.2.6) sur le rawLog."""
    engineer = FeatureEngineer(df_raw)
    return engineer.compute_all()


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Pipeline MoMTSim-KAN")
    parser.add_argument("--calibrate", action="store_true",
                        help="Lance la calibration SSE/SPSA avant la simulation")
    parser.add_argument("--probas", type=str, default=None,
                        help="Chemin vers un fichier JSON de probas calibrées")
    parser.add_argument("--no-features", action="store_true",
                        help="Ne pas calculer les features après la simulation")
    args = parser.parse_args()

    # --- Chargement des probas ---
    fraud_probas = None
    if args.calibrate:
        fraud_probas = run_calibration()
    elif args.probas and os.path.exists(args.probas):
        with open(args.probas, "r", encoding="utf-8") as f:
            fraud_probas = json.load(f)
        print(f"Probas chargées depuis {args.probas} : {fraud_probas}")
    elif os.path.exists("calibrated_probas.json"):
        with open("calibrated_probas.json", "r", encoding="utf-8") as f:
            fraud_probas = json.load(f)
        print(f"Probas calibrées trouvées : {fraud_probas}")

    # --- Simulation ---
    print("\n=== Simulation complète ===")
    df_raw = run_simulation(fraud_probas=fraud_probas, verbose=True)
    df_raw.to_csv("rawLog_torch.csv", index=False)

    fraud_rate = df_raw["isFraud"].mean()
    print(f"\nTerminé — {len(df_raw)} transactions")
    print(f"Taux de fraude global : {fraud_rate:.3f}")
    if df_raw["isFraud"].any():
        print(df_raw.loc[df_raw["isFraud"], "fraudScenario"].value_counts(normalize=True))

    # --- Feature engineering ---
    if not args.no_features:
        print("\n=== Feature engineering ===")
        df_features = run_feature_engineering(df_raw)
        df_features.to_csv("featuresLog.csv", index=False)
        print(f"featuresLog.csv sauvegardé — {len(df_features)} lignes, "
              f"{len(df_features.columns)} colonnes")


if __name__ == "__main__":
    main()
