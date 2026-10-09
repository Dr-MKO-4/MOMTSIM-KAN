"""
run_live.py  Point d'entrée du flux live MoMTSim (Kafka + REST).

    python run_live.py                        # profil validé : 20 000 clients
    python run_live.py --tick 0.25            # 4 steps par seconde
    python run_live.py --no-kafka             # canal REST seul
    python run_live.py --warmup-steps 0       # sans échauffement (déconseillé)

Population, volume et débit se règlent ICI : le dashboard est un pur consommateur.
Le taux de fraude dépend de --n-mules et --volume-scale (pas du nombre de clients).
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from live.producer import (  # noqa: E402
    LiveProducer, DEFAULT_CLIENTS, DEFAULT_VOLUME_SCALE, DEFAULT_MULES, DEFAULT_WARMUP_STEPS,
)
from live.server import build_app  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Flux live MoMTSim (Kafka + REST)")
    parser.add_argument("--n-clients", type=int, default=DEFAULT_CLIENTS,
                        help=f"taille de la population (défaut {DEFAULT_CLIENTS})")
    parser.add_argument("--volume-scale", type=float, default=DEFAULT_VOLUME_SCALE,
                        help="facteur du volume de transactions légitimes "
                             f"(défaut {DEFAULT_VOLUME_SCALE})")
    parser.add_argument("--n-mules", type=int, default=DEFAULT_MULES,
                        help=f"nombre de mules, levier du taux de fraude (défaut {DEFAULT_MULES})")
    parser.add_argument("--warmup-steps", type=int, default=DEFAULT_WARMUP_STEPS,
                        help="steps d'historique rejoués avant le direct "
                             f"(défaut {DEFAULT_WARMUP_STEPS})")
    parser.add_argument("--tick", type=float, default=0.5,
                        help="secondes entre deux steps en direct (défaut 0.5)")
    parser.add_argument("--port", type=int, default=8766,
                        help="port du canal REST (défaut 8766)")
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--no-kafka", action="store_true",
                        help="désactive la publication Kafka (canal REST seul)")
    args = parser.parse_args()

    producer = LiveProducer(n_clients=args.n_clients, tick_seconds=args.tick,
                            seed=args.seed, kafka_enabled=not args.no_kafka,
                            volume_scale=args.volume_scale, n_mules=args.n_mules,
                            warmup_steps=args.warmup_steps)

    thread = threading.Thread(target=producer.run, daemon=True)
    thread.start()

    print(f"\n{'=' * 55}\n Flux live MoMTSim\n"
          f" REST  : http://127.0.0.1:{args.port}/live/transactions\n"
          f" Kafka : {'désactivé' if args.no_kafka else 'mm.transactions.momtsim'}\n"
          f"{'=' * 55}\n", flush=True)

    import uvicorn
    try:
        uvicorn.run(build_app(producer), host="127.0.0.1", port=args.port,
                    log_level="warning")
    finally:
        producer.stop()


if __name__ == "__main__":
    main()
