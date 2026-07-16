# MoMTSim-KAN — Simulation de fraude Mobile Money & détection par KAN

> Mémoire de Master 2 · Contexte CEMAC / Cameroun · 2025  
> Chapitres 3 (simulation + features) et 4 (validation topologique KAN)

---

## Télécharger et installer (aucune connaissance technique requise)

**Windows 10 / 11 (64 bits) uniquement.**

1. Allez dans l'onglet [**Releases**](../../releases) de ce dépôt GitHub
2. Dans la dernière release, téléchargez le fichier **`MoMTSim-Setup-x64.exe`**
3. Double-cliquez sur l'installeur, suivez les étapes (Suivant → Installer → Terminer)
4. Lancez **MoMTSim** depuis le Bureau ou le menu Démarrer

Une fenêtre s'ouvre directement — aucun navigateur, aucun serveur à démarrer.

> **Note :** au premier lancement, Windows Defender peut afficher un avertissement  
> « Application inconnue ». Cliquez sur **« Informations complémentaires »** puis  
> **« Exécuter quand même »** — le logiciel n'est simplement pas encore signé numériquement.

---

## Utilisation de l'interface

| Page | À quoi ça sert |
|---|---|
| **Tableau de bord** | Vue d'ensemble de l'état du pipeline |
| **Configuration** | Régler les paramètres des scénarios de fraude |
| **Simulation** | Générer les transactions synthétiques (rawLog) |
| **Features** | Calculer les 12 indicateurs de détection de fraude |
| **Validation KAN** | Tester si le réseau neuronal KAN est applicable |
| **Calibration** | Ajuster automatiquement les taux de fraude |
| **Historique** | Revoir les résultats des simulations précédentes |

---

## Installation depuis les sources (développeurs)

### Prérequis

| Outil | Version minimale | Téléchargement |
|---|---|---|
| Python | 3.10 | [python.org](https://www.python.org/downloads/) |
| Node.js | 18 | [nodejs.org](https://nodejs.org/) |
| Git | — | [git-scm.com](https://git-scm.com/) |

### 1. Cloner le dépôt

```bash
git clone https://github.com/Dr-MKO-4/MOMTSIM-KAN.git
cd MOMTSIM-KAN
```

### 2. Backend Python

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r backend/requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
cd ..
```

### 4. Lancer en mode développement

**Terminal 1 — API (port 8000)**
```bash
.venv\Scripts\activate
python start_backend.py
```

**Terminal 2 — UI (port 5173)**
```bash
cd frontend && npm run dev
```

L'interface s'ouvre sur `http://localhost:5173`.

---

## Construire l'installeur Windows

Prérequis supplémentaires :
```bash
pip install pyinstaller
cd electron && npm install && cd ..
```

Build complet (~ 10–20 min selon la taille de PyTorch) :
```powershell
.\build.ps1
```

Flags disponibles :
```powershell
.\build.ps1 -SkipFrontend      # si frontend/dist/ est déjà à jour
.\build.ps1 -SkipPyInstaller   # si dist/momtsim_server/ est déjà à jour
```

L'installeur `.exe` est généré dans `dist-electron\`.

---

## Paramètres de simulation par défaut

| Paramètre | Valeur par défaut |
|---|---|
| Clients | 2 000 |
| Marchands | 300 |
| Banques | 20 |
| Mules | 60 |
| Steps | 720 (= 30 jours × 24 h) |
| Taux de fraude cible | 20 – 26 % |
| Seed | 1 000 |

---

## Scénarios de fraude simulés

| Code | Scénario | Section mémoire |
|---|---|---|
| `ATO` | Account Takeover — vide le compte en fragments via des mules | 3.2.1 |
| `REFUND` | Refund Fraud — remboursement différé Δt ∼ U(1h, 48h) | 3.2.2 |
| `FAKE_CRED` | Fake Credentials — dormance puis exploitation rapide | 3.2.3 |
| `SPLIT_DEP` | Split Deposit — fragmentation sous seuil tarifaire | 3.2.4 |
| `SMURFING` | Smurfing — réseau de mules (Zhdanova et al.) | 3.2.5 |

---

## Features calculées (section 3.2.6 — éqs. 3.8–3.19)

| Feature | Description |
|---|---|
| `delta_B_orig` | Variation de solde côté émetteur |
| `delta_B_dest` | Variation de solde côté destinataire |
| `r1` | Montant / solde initial |
| `r2` | Montant / solde final |
| `flag_anomalie` | Anomalie sur fenêtre glissante de 10 transactions |
| `delta_commission_ratio` | Commission mule Smurfing |
| `var_agent_split` | Variance intra-agent Split Deposit |
| `rho_rupture` | Rupture de comportement Fake Credentials |
| `rho_refund` | Ratio remboursements / paiements |
| `v1h` | Vélocité sur 1 heure |
| `flag_nuit` | Transaction nocturne (22h–6h) |
| `rho_nouveau` | Ratio destinataires inconnus (fenêtre 30 j) |

---

## Validation topologique KAN (section 4.1 — Quick Decision Rule)

| Critère | Seuil | Équation |
|---|---|---|
| VE₂ (variance expliquée PCA 2D) | ≥ 0.40 | 4.2–4.3 |
| J\_Fisher (séparabilité LDA) | > 1 | 4.4 |
| D̄\_KS (régularité des distributions) | < 0.15 | 4.5 |
| ρ\_coverage (couverture grille KAN) | ∈ [0.8, 1.0] | 4.6 |

---

## Architecture du projet

```
MOMTSIM-KAN/
├── backend/                  # API FastAPI
│   ├── api.py                # Endpoints REST
│   ├── pipeline_runner.py    # Jobs asynchrones
│   ├── schemas.py            # Modèles Pydantic
│   ├── config_manager.py     # Gestion config fraude
│   ├── run_registry.py       # Historique SQLite
│   └── requirements.txt
├── frontend/                 # Interface React + Tailwind
│   └── src/
│       ├── pages/
│       ├── components/
│       ├── api/client.ts
│       └── types/api.ts
├── electron/                 # Packaging application desktop
│   ├── main.js
│   └── package.json
├── paramFiles/               # Données de calibration CEMAC
├── momtsim_torch.py          # Moteur de simulation (PyTorch)
├── features.py               # Feature engineering
├── viz.py                    # Visualisations Plotly
├── calibration_sse.py        # Calibration SPSA
├── run_server.py             # Point d'entrée production
├── momtsim.spec              # Spec PyInstaller
└── build.ps1                 # Script de build installeur
```

---

## Contexte réglementaire

Le seuil de déclaration COBAC/BEAC pour les transactions suspectes est fixé à **500 000 FCFA** (`S_seuil` dans la config Smurfing). Ce paramètre est modifiable directement depuis la page Configuration du dashboard.

---

## Licence

Usage académique — Mémoire de M2, 2025.
