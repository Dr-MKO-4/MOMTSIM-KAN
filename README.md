# MoMTSim-KAN — Simulation de fraude Mobile Money & détection par KAN

> Mémoire de Master 2 · Contexte CEMAC / Cameroun · 2025  
> Chapitres 3 (simulation + features) et 4 (validation topologique KAN)

---

## Vue d'ensemble

Ce dépôt contient l'implémentation complète du pipeline **MoMTSim-KAN** :

1. **Simulation multi-agents** d'un réseau Mobile Money (clients, marchands, banques, mules) avec injection de 5 scénarios de fraude calibrés sur données réelles CEMAC.
2. **Ingénierie de 12 features** dérivées formellement dans le mémoire (éqs. 3.8–3.19).
3. **Calibration SSE/SPSA** des probabilités de fraude (section 3.1.3).
4. **Validation topologique KAN** via la *Quick Decision Rule* (éqs. 4.1–4.7 : VE₂, J\_Fisher, D\_KS, ρ\_coverage).
5. **Dashboard interactif** FastAPI + React pour piloter le pipeline sans toucher au code.

---

## Scénarios de fraude simulés

| Code | Scénario | Section |
|---|---|---|
| `ATO` | Account Takeover — vide le compte en fragments | 3.2.1 |
| `REFUND` | Refund Fraud — remboursement différé Δt ∼ U(1h, 48h) | 3.2.2 |
| `FAKE_CRED` | Fake Credentials — dormance puis exploitation rapide | 3.2.3 |
| `SPLIT_DEP` | Split Deposit — fragmentation sous seuil tarifaire | 3.2.4 |
| `SMURFING` | Smurfing — réseau de mules (Zhdanova et al.) | 3.2.5 |

---

## Architecture du projet

```
MOMTSIM/
│
├── momtsim_torch.py          # Moteur vectorisé PyTorch (TorchParameters, TorchMoMTSimEngine, TorchFraudInjector)
├── features.py               # FeatureEngineer — 12 features vectorisées (O(n log n))
├── calibration_sse.py        # SSEFraudCalibrator — SPSA sur SSE(Dr, Ds)
├── viz.py                    # TopologyValidator + MoMTSimVisualizer (Plotly dark)
├── main.py                   # CLI orchestrateur : --calibrate / --probas / --no-features
├── start_backend.py          # Lance uvicorn sur le backend FastAPI
│
├── paramFiles/               # 6 CSV de paramètres (population, balances, profils clients…)
│   ├── aggregatedTransactions.csv
│   ├── clientsProfiles.csv
│   ├── initialBalancesDistribution.csv
│   ├── maxOccurrencesPerClient.csv
│   ├── overdraftLimits.csv
│   └── transactionsTypes.csv
│
├── fraudScenariosConfig.json # Config des 5 scénarios (éditable via dashboard)
├── calibrated_probas.json    # Résultat de la calibration SPSA (θ*)
│
├── backend/                  # API FastAPI
│   ├── api.py                # 11 endpoints REST + CORS
│   ├── schemas.py            # Modèles Pydantic (FraudConfig, SimulationParams…)
│   ├── config_manager.py     # R/W/backup/restore fraudScenariosConfig.json
│   └── pipeline_runner.py    # Jobs async (threads) + store in-memory
│
├── frontend/                 # Dashboard React + Vite + TypeScript + Tailwind
│   └── src/
│       ├── pages/            # Dashboard, Config, Simulation, Features, KAN, Calibration
│       ├── components/       # Layout, Sidebar, TopBar, JobTracker, PlotlyEmbed, StatCard
│       ├── api/client.ts     # Toutes les requêtes + pollJob()
│       └── types/api.ts      # Types TS miroirs des schémas Pydantic
│
├── momtsim_kan_pipeline.ipynb  # Notebook complet (exploration + prototypage)
└── mémoire.tex                 # Source LaTeX du mémoire
```

---

## Démarrage rapide

### Prérequis

- Python ≥ 3.11 avec PyTorch, pandas, numpy, plotly, fastapi, uvicorn
- Node.js ≥ 18 (pour le frontend)

### Installation

```bash
# Backend
pip install -r backend/requirements.txt

# Frontend
cd frontend
npm install
```

### Lancer le pipeline en ligne de commande

```bash
# Simulation complète (probas calibrées chargées automatiquement)
python main.py

# Calibration SSE/SPSA puis simulation
python main.py --calibrate

# Simulation avec un fichier de probas spécifique
python main.py --probas calibrated_probas.json

# Simulation sans feature engineering
python main.py --no-features
```

### Lancer le dashboard interactif

```bash
# Terminal 1 — API
python start_backend.py
# → http://127.0.0.1:8000/docs  (Swagger UI)

# Terminal 2 — UI
cd frontend && npm run dev
# → http://localhost:5173
```

---

## Paramètres de simulation par défaut

| Paramètre | Valeur |
|---|---|
| N\_clients | 2 000 |
| N\_marchands | 300 |
| N\_banques | 20 |
| N\_mules | 60 |
| N\_steps | 720 (= 30 jours × 24h) |
| Taux de fraude cible | 20 – 26 % |
| Seed | 1 000 |

---

## Features calculées (section 3.2.6)

| Feature | Équation | Description |
|---|---|---|
| `delta_B_orig` | 3.8 | Variation solde émetteur |
| `delta_B_dest` | 3.9 | Variation solde destinataire |
| `r1` | 3.10 | Montant / solde initial |
| `r2` | 3.11 | Montant / solde final |
| `flag_anomalie` | 3.12 | Anomalie fenêtre 10 tx glissant |
| `delta_commission_ratio` | 3.13 | Commission mule Smurfing |
| `var_agent_split` | 3.14 | Variance intra-agent Split Deposit (ddof=0) |
| `rho_rupture` | 3.15 | Rupture de comportement Fake Credentials |
| `rho_refund` | 3.16 | Ratio remboursements / paiements |
| `v1h` | 3.17 | Vélocité sur 1 heure |
| `flag_nuit` | 3.18 | Transaction nocturne (22h–6h) |
| `rho_nouveau` | 3.19 | Ratio destinataires inconnus (fenêtre 30j) |

---

## Calibration SSE/SPSA

Minimise θ\* = argmin Σ\_c Σ\_t (Dr(c,t) − Ds(c,t ; θ))² par l'algorithme SPSA
(2 évaluations par itération, adapté aux simulations bruitées non différentiables).

Les probabilités optimales sont sauvegardées dans `calibrated_probas.json` et
chargées automatiquement par la simulation et le dashboard.

---

## Validation topologique KAN (section 4.1)

La *Quick Decision Rule* (éq. 4.7) combine 4 critères :

| Critère | Seuil | Équation |
|---|---|---|
| VE₂ (variance expliquée PCA 2D) | ≥ 0.40 | 4.2–4.3 |
| J\_Fisher (séparabilité LDA) | > 1 | 4.4 |
| D̄\_KS (régularité distributions) | < 0.15 | 4.5 |
| ρ\_coverage (couverture grille) | ∈ [0.8, 1.0] | 4.6 |

**Décision :** KAN valide / Transformations requises / Architecture alternative.

---

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/config` | Lire `fraudScenariosConfig.json` |
| PUT | `/api/config` | Écrire + backup automatique |
| GET | `/api/config/backups` | Liste des backups horodatés |
| POST | `/api/config/restore/{name}` | Restaurer un backup |
| GET | `/api/probas` | Probas calibrées courantes |
| POST | `/api/simulate` | Lancer une simulation (job async) |
| POST | `/api/features` | Lancer le feature engineering |
| POST | `/api/kan/validate` | Lancer la validation KAN |
| POST | `/api/calibrate` | Lancer la calibration SPSA |
| GET | `/api/jobs/{job_id}` | Statut + résultat d'un job |
| GET | `/api/health` | État des fichiers du pipeline |

---

## Contexte réglementaire

Le seuil de déclaration COBAC/BEAC pour les transactions suspectes est fixé à
**500 000 FCFA** (`S_seuil` dans la config Smurfing). Ce paramètre est modifiable
directement depuis le dashboard.

---

## Fichiers ignorés par git

- `MoMTSim_old/` — ancienne version non-torch (conservée localement)
- `rawLog_torch.csv`, `featuresLog.csv` — sorties générées (reproductibles)
- `viz_*.html` — figures Plotly exportées
- `config_backups/` — backups locaux de configuration
- `frontend/node_modules/`, `__pycache__/` — dépendances installées
