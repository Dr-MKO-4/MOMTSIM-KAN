#!/usr/bin/env bash
# run_mac.sh  Lance le backend FastAPI de MOMTSIM sur Mac Apple Silicon (M4/M6).
#
# MOMTSIM_DEVICE contrôle le device torch utilisé par src/momtsim_torch.py
# (cpu ou mps). Par défaut "cpu" : lance d'abord bench_mac.py sur ta machine
# pour savoir si mps est vraiment plus rapide sur ce moteur avant de le forcer.
set -euo pipefail

cd "$(dirname "$0")/.."

export MOMTSIM_DEVICE="${MOMTSIM_DEVICE:-cpu}"
export PYTORCH_ENABLE_MPS_FALLBACK=1

echo "MOMTSIM_DEVICE=$MOMTSIM_DEVICE"
python3 run_server.py
