"""
bench_mac.py  Compare CPU vs MPS pour le moteur MoMTSim vectorisé, sur Mac
Apple Silicon (M4/M6).

Le moteur (src/momtsim_torch.py) fait beaucoup de petites opérations tensorielles
par step ; le GPU MPS a un coût de lancement de kernel qui peut annuler son
avantage pour des tenseurs de cette taille. Ce script mesure les deux pour
décider objectivement quel device utiliser par défaut sur cette machine,
plutôt que de le supposer.

Usage :
    python bench_mac.py                    # compare cpu et mps, steps/n_clients par défaut
    python bench_mac.py --device mps        # une seule mesure (utilisé en interne)
    python bench_mac.py --steps 720 --n-clients 2000   # taille réelle d'une simulation complète
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _run_single(device: str, steps: int, n_clients: int) -> float:
    """Exécute la boucle de simulation pour `device` et retourne le temps en secondes.

    Le device est fixé via la variable d'env MOMTSIM_DEVICE *avant* l'import de
    src.momtsim_torch, car DEVICE y est une constante de module calculée à l'import.
    """
    import os
    os.environ["MOMTSIM_DEVICE"] = device
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    sys.path.insert(0, str(_ROOT))
    from src.momtsim_torch import (  # noqa: E402
        TorchParameters, TorchMoMTSimEngine, TorchFraudInjector, DEVICE,
    )
    import torch  # noqa: E402

    if str(DEVICE) != device:
        raise RuntimeError(
            f"Device demandé '{device}' indisponible sur cette machine "
            f"(obtenu '{DEVICE}'). Vérifie torch.backends.mps.is_available()."
        )

    params = TorchParameters(
        str(_ROOT / "config" / "paramFiles"),
        str(_ROOT / "config" / "fraudScenariosConfig.json"),
        n_clients=n_clients, seed=1000)
    engine = TorchMoMTSimEngine(params, n_clients=n_clients, n_merchants=300, n_banks=20,
                                 n_mules=60, max_slots_per_step=6, seed=1000)

    fraud_probas = None
    _probas_path = _ROOT / "config" / "calibrated_probas.json"
    if _probas_path.exists():
        with open(_probas_path, "r", encoding="utf-8") as f:
            fraud_probas = json.load(f)

    injector = TorchFraudInjector(engine, params, fraud_probas=fraud_probas, seed=1000)

    # Warm-up (compile/allocation lazy MPS, pas comptabilisé dans la mesure)
    warm_steps = min(10, steps)
    for step in range(warm_steps):
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

    if device == "mps":
        torch.mps.synchronize()

    t0 = time.perf_counter()
    for step in range(warm_steps, steps):
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

    if device == "mps":
        torch.mps.synchronize()

    return time.perf_counter() - t0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["cpu", "mps"], default=None,
                         help="Ne mesurer qu'un seul device (utilisé en interne par les sous-process)")
    parser.add_argument("--steps", type=int, default=200,
                         help="Nombre de steps de simulation à chronométrer (défaut 200, réel = 720)")
    parser.add_argument("--n-clients", type=int, default=2000,
                         help="Taille du problème (défaut 2000, comme la config réelle)")
    args = parser.parse_args()

    if args.device is not None:
        elapsed = _run_single(args.device, args.steps, args.n_clients)
        print(f"RESULT device={args.device} elapsed_s={elapsed:.4f}")
        return

    print(f"Benchmark MoMTSim CPU vs MPS  ({args.steps} steps, {args.n_clients} clients)\n")

    results: dict[str, float] = {}
    for device in ("cpu", "mps"):
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()),
             "--device", device, "--steps", str(args.steps), "--n-clients", str(args.n_clients)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            print(f"  {device:>4} : échec\n{proc.stderr.strip()}\n")
            continue
        line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT")), None)
        if line is None:
            print(f"  {device:>4} : sortie inattendue\n{proc.stdout}\n{proc.stderr}\n")
            continue
        elapsed = float(line.split("elapsed_s=")[1])
        results[device] = elapsed
        print(f"  {device:>4} : {elapsed:.3f} s")

    if "cpu" in results and "mps" in results:
        ratio = results["cpu"] / results["mps"]
        faster = "mps" if ratio > 1 else "cpu"
        print(f"\n→ {faster} est {max(ratio, 1/ratio):.2f}x plus rapide sur cette machine.")
        print("  Fixe MOMTSIM_DEVICE en conséquence dans run_mac.sh si tu veux forcer ce choix.")


if __name__ == "__main__":
    main()
