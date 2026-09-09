# MOMTSIM sur Mac (Apple Silicon M4/M6)

Ce dossier ne duplique pas le code : il fournit la config et les scripts pour
lancer le backend Python de MOMTSIM (FastAPI + moteur torch) sur Mac, avec
détection automatique du GPU Apple Silicon (MPS) en plus de CPU/CUDA.

Le frontend React et le serveur FastAPI sont lancés séparément par toi sur le
Mac (pas via Electron) — ce dossier ne concerne que le backend Python.

## Installation

```bash
cd MOMTSIM
python3 -m venv .venv
source .venv/bin/activate
pip install -r momtsimmac/requirements-mac.txt
```

Aucun build spécial de torch n'est nécessaire : le paquet `torch` officiel
PyPI inclut déjà le support MPS pour macOS arm64.

## 1. Mesurer CPU vs MPS avant de choisir

Le moteur (`src/momtsim_torch.py`) exécute une boucle séquentielle de 720 steps
avec beaucoup de petites opérations tensorielles par step. Le GPU MPS a un coût
de lancement de kernel par opération qui peut annuler son avantage sur des
tenseurs de cette taille — donc ne pas supposer que MPS est plus rapide,
le mesurer :

```bash
python momtsimmac/bench_mac.py
```

Ça lance la simulation (taille réelle par défaut : 2000 clients, 200 steps
chronométrés) une fois en CPU et une fois en MPS, dans deux sous-process
séparés, et affiche lequel est le plus rapide sur ta machine.

Pour tester à l'échelle réelle (720 steps) :

```bash
python momtsimmac/bench_mac.py --steps 720
```

## 2. Lancer le backend

```bash
MOMTSIM_DEVICE=cpu ./momtsimmac/run_mac.sh    # ou MOMTSIM_DEVICE=mps selon le résultat du bench
```

`MOMTSIM_DEVICE` force le device sans dépendre de la détection automatique
(`cuda > mps > cpu`) codée dans `src/momtsim_torch.py`. Par défaut le script
utilise `cpu` tant que le bench n'a pas confirmé que `mps` est plus rapide.

## 3. Lancer le frontend

Comme sur les autres plateformes, dans un terminal séparé :

```bash
cd frontend
npm install
npm run dev
```

## Limites connues

- Certaines opérations utilisées par le moteur (`torch.isin`,
  `torch.multinomial` avec `generator`, `torch.distributions.Binomial`) n'ont
  pas toutes un support MPS natif complet selon la version de PyTorch. Avec
  `PYTORCH_ENABLE_MPS_FALLBACK=1` (déjà activé par `run_mac.sh`), ces
  opérations basculent silencieusement sur CPU — ce qui coûte un aller-retour
  mémoire GPU↔CPU sans erreur visible. C'est une des raisons pour lesquelles
  le bench mesure le temps de bout en bout plutôt que de supposer un gain.
- Ce dossier ne construit pas d'app `.app` empaquetée (Electron) — build mac
  d'Electron non testé depuis cet environnement Windows, à faire séparément
  si besoin.
