# Rapport Phase 0 & Phase 1 — Projet MoMTSim-KAN
## Détection de fraude Mobile Money par réseaux KAN (contexte CEMAC/Cameroun)

---

## 1. Présentation générale du pipeline

Le projet est structuré en deux phases consécutives, couvrant la production des données simulées (Phase 0) et l'ingénierie des caractéristiques suivie de la validation topologique du réseau neuronal KAN (Phase 1). Le pipeline complet s'exécute via une interface web (React/Vite en frontend, FastAPI en backend) qui orchestre les étapes de manière asynchrone.

---

## 2. Fichiers du projet — rôle et structure

### 2.1 `fraudScenariosConfig.json`

Ce fichier de configuration JSON centralise tous les paramètres numériques des cinq scénarios de fraude injectés dans le simulateur. Il est lu une seule fois au démarrage de `TorchParameters` et distribué à `TorchFraudInjector`. Il contient :

- **`global`** : les bornes du taux de fraude cible (20–26 %) et l'équipartition entre scénarios.
- **`ato`** : seuil de solde minimum de la victime, nombre de mules, fourchettes de fragmentation.
- **`refund`** : délai de remboursement, nombre de cycles par marchand, proportion de transactions de camouflage.
- **`fake_credentials`** : durée de dormance, nombre de transactions légitimes de façade, montant à l'activation.
- **`split_deposit`** : tolérance sur les fragments, délai de dépôt (en secondes, sans effet direct puisque le simulateur est horaire), grille tarifaire.
- **`smurfing`** : nombre de mules, proportions conscientes/inconscientes, seuil S_seuil, commission delta, délai mule (delay_mule_min_hours / delay_mule_max_hours), fréquence d'opération.

Ce fichier est la seule source de vérité pour les paramètres de fraude : toute modification de la physique des scénarios doit passer par lui, sans toucher au code Python.

---

### 2.2 `momtsim_torch.py`

Moteur de simulation vectorisé PyTorch. Il contient trois classes :

#### `TorchParameters`
**Rôle :** Charge les 6 fichiers CSV de paramètres (profils clients, transactions agrégées, soldes initiaux, découverts, occurrences maximales) ainsi que `fraudScenariosConfig.json`, puis précalcule des tenseurs PyTorch utilisables directement par le moteur.

**Entrées :** chemin du répertoire `paramFiles/`, chemin du JSON de config fraude, nombre de clients, graine aléatoire.

**Produit :** tenseurs `mean_amount_tensor`, `std_amount_tensor`, `action_available` (profils de transaction par client × action), `initial_balance` (soldes initiaux échantillonnés empiriquement), `overdraft_limit`, `equilibrium` (solde d'équilibre du modèle ressort), `step_target_count` (volume horaire cible), `step_avg` / `step_std` (profils horaires par action). Ces tenseurs sont tous transférés sur GPU si disponible.

**Section mémoire :** Correspond à la construction des profils comportementaux de la section 3.3 (modèle ressort) et à l'initialisation des paramètres décrite en section 3.1.

#### `TorchMoMTSimEngine`
**Rôle :** Exécute la simulation transactionnelle légitime sur 720 steps (= 30 jours à granularité horaire). Tous les acteurs — clients, marchands, banques, mules — sont indexés dans un unique tenseur de soldes `balance`, permettant des opérations de mise à jour vectorisées (`index_add_`).

**Entrées :** une instance `TorchParameters`, les effectifs (n_clients, n_merchants, n_banks, n_mules), le nombre de slots de transaction par step, une graine.

**Produit :** un journal de transactions (listes Python converties en DataFrame via `to_dataframe()`).

**Méthodes principales :**

- `_spring_probabilities()` : calcule pour chaque client la probabilité d'effectuer une action entrante ou sortante selon le modèle ressort (éq. 3.3 — force proportionnelle à l'écart entre solde courant et solde d'équilibre).
- `_draw_action_indices()` : sélectionne l'action de chaque client actif par multinomiale pondérée par disponibilité et probabilité entrante/sortante.
- `_draw_amounts()` : tire le montant selon un mélange gaussien (profil client × profil horaire du step).
- `_draw_counterparties()` : implémente la stickiness 90/10 — 90 % de probabilité de choisir un partenaire déjà connu (buffer circulaire de 100 contacts), 10 % d'aléatoire.
- `_run_step_slot(step, slot_mask)` : exécute un slot complet pour tous les clients actifs, met à jour les soldes et journalise.
- `run(n_steps)` : boucle principale (720 steps × max_slots slots).
- `to_dataframe()` : convertit les listes de log en DataFrame au format rawLog (colonnes step, action, amount, nameOrig, nameDest, oldBalance*, newBalance*, isFraud, fraudScenario).
- `log_transaction()` : point d'entrée unique utilisé par le fraudeur pour journaliser une transaction hors flux légitime.
- `transfer()` : effectue un virement entre deux acteurs sur le tenseur `balance` partagé et retourne les soldes avant/après.

#### `TorchFraudInjector`
**Rôle :** Injecte les cinq scénarios de fraude à chaque step, en exploitant directement le tenseur `balance` du moteur.

**Entrées :** une instance `TorchMoMTSimEngine`, les paramètres, des probabilités d'activation par scénario, une graine.

**Méthodes principales :**

- `inject(step)` : appelée à chaque step par la boucle principale — déclenche `_flush_pending()` puis chaque scénario selon sa probabilité.
- `_flush_pending(current_step)` : exécute les transactions différées planifiées (remboursements REFUND, virements mule→récepteur SMURFING).
- `_run_ato(step)` : scénario Account Takeover (section 3.2.1) — vide partiellement le solde d'une victime vers des mules par fragments aléatoires.
- `_run_refund(step)` : scénario Refund Fraud (section 3.2.2) — PAYMENT immédiat fraudeur→marchand vulnérable suivi d'un REFUND différé de Δt ~ U(1h, 48h).
- `_fake_credentials_step(step, allow_new)` : scénario Fake Credentials (section 3.2.3) — période de dormance avec transactions légitimes de façade, puis TRANSFER massif à l'activation.
- `_optimal_fragmentation(total)` : calcule le découpage optimal pour le Split Deposit en maximisant la commission totale sur la grille tarifaire, puis ajoute une perturbation ε_j par fragment (section 3.2.4).
- `_run_split_deposit(step)` : scénario Split Deposit (section 3.2.4) — fragmente un dépôt total en plusieurs CASH_IN vers un client.
- `_run_smurfing(step)` : scénario Smurfing / structuration (section 3.2.5, Zhdanova et al.) — émetteur→mules (immédiat), mules→récepteur différé de Δt_mule ~ U(2h, 24h), commission retenue δ ~ U(1 %, 10 %).

---

### 2.3 `features.py`

Module d'ingénierie des caractéristiques. Il transforme le rawLog brut en un tableau de 12 features par transaction, conformément à la section 3.2.6 du mémoire.

#### `FeatureEngineer`
**Rôle :** Calcule l'ensemble des features dérivées à partir du rawLog CSV.

**Entrées :** un DataFrame rawLog (colonnes : step, action, amount, nameOrig, nameDest, oldBalance*, newBalance*, isFraud…), une tolérance numérique `eps` (défaut 1e-6), une tolérance temporelle `mule_tolerance_steps` (défaut 48 steps).

**Produit :** le même DataFrame enrichi de 12 colonnes de features supplémentaires.

**Méthodes de calcul :**

- `_delta_balances()` : calcule ΔBorig = oldBalanceOrig − newBalanceOrig et ΔBdest = newBalanceDest − oldBalanceDest (éq. 3.8 / 3.9). Mesure le débit net de chaque compte sur la transaction.
- `_ratios_r1_r2()` : r1 = montant / solde initial (éq. 3.10), r2 = montant / solde résiduel (éq. 3.11). Ces deux ratios caractérisent les transactions ATO (comptes vidés d'un coup).
- `_flag_anomalie()` : indicatrice binaire signalant un montant supérieur à μ + 2σ calculés sur les 10 dernières transactions du même compte et du même type (éq. 3.12, fenêtre glissante avec shift pour éviter la fuite d'information).
- `_flag_nuit()` : indicatrice binaire — vrai si le step correspond à la tranche 22h–5h (éq. 3.18, heure extraite par modulo 24).
- `_velocity_1h()` : V1h = nombre de transactions du même compte émetteur au même step (éq. 3.17 — granularité horaire du simulateur impose une approximation : 1 step = 1 fenêtre).
- `_delta_commission_smurfing()` : feature Smurfing (éq. 3.13). Pour chaque compte, apparie la dernière transaction TRANSFER entrante avec la transaction TRANSFER sortante la plus proche, via `pd.merge_asof` avec `direction="backward"` et `tolerance=mule_tolerance_steps`. Calcule delta_commission_ratio = (montant_reçu − montant_envoyé) / montant_reçu. Un compte est marqué `is_mule_candidate=True` si ce ratio est dans (0, 10 %] — critère 1 de Zhdanova et al. (section 1.4.4 / 3.2.6). La tolérance temporelle garantit que seules les paires séparées d'au plus 48 steps sont considérées.
- `_var_agent_split_deposit()` : feature Split Deposit (éq. 3.14). Pour chaque triplet (agent, client, step), calcule la variance population (ddof=0) des montants de CASH_IN et le nombre de fragments. Un agent qui fragmente envoie plusieurs CASH_IN au même step, produisant une variance non nulle.
- `_rho_rupture_fake_cred()` : feature Fake Credentials (éq. 3.15). Calcule la moyenne historique des 30 derniers jours (720 steps) par compte émetteur via fenêtre glissante vectorisée (cumsum + searchsorted), puis rho_rupture = montant / moyenne_historique. Une rupture brutale (valeur >> 1) signale un changement de comportement caractéristique d'une usurpation.
- `_rho_refund()` : feature Refund Fraud (éq. 3.16). Ratio REFUND / PAYMENT dans une fenêtre glissante de 30 jours par compte émetteur.
- `_rho_nouveau()` : feature comportementale (éq. 3.19). Proportion de destinataires "nouveaux" (jamais contactés dans les 90 jours précédents) sur les 30 derniers jours. Élevé pour les fraudeurs qui sondent de nombreux comptes.
- `_windowed_sum_by_group()` (méthode statique) : primitive vectorisée O(n log n) pour les sommes/comptes sur fenêtre glissante par groupe, via cumsum et searchsorted. Utilisée par _rho_rupture, _rho_refund, _rho_nouveau.
- `compute_all()` : orchestre l'appel de toutes les méthodes dans l'ordre et retourne le DataFrame final.

---

### 2.4 `viz.py`

Module de visualisation et de validation topologique. Il contient deux classes principales.

#### Constantes de module

- `FEATURES_12` : liste ordonnée des 12 noms de features transmises au pipeline KAN.
- `BINARY_FEATURES` : sous-liste `["flag_nuit", "flag_anomalie"]` — indicatrices exclues du test KS et du calcul de couverture de grille (voir section 4 ci-dessous).

#### `TopologyValidator`
**Rôle :** Vérifie que les 12 features satisfont les critères topologiques nécessaires à une bonne approximation par B-splines dans un réseau KAN (section 4.1 du mémoire).

**Entrées :** le DataFrame de features enrichi, la liste des features à valider, une tolérance numérique.

**Produit :** un dictionnaire `report` contenant tous les indicateurs calculés et la décision finale.

**Méthodes :**

- `normalize()` : standardisation z-score centrée-réduite (éq. 4.1) — soustrait la moyenne, divise par l'écart-type. Produit `X_norm` (matrice n×12).
- `pca()` : décomposition en valeurs singulières (éq. 4.2 / 4.3) — calcule la variance expliquée à 2 composantes (VE2) et le nombre de composantes nécessaires pour 80 % de variance (k_for_VE80).
- `fisher_index()` : indice de Fisher multivarié (éq. 4.4) — mesure la séparabilité linéaire entre transactions légitimes et frauduleuses dans l'espace projeté. Calcule J_Fisher = (μ₁−μ₀)ᵀ Sw⁻¹ (μ₁−μ₀) / trace(Sw).
- `_ks_statistic_vs_normal()` (statique) : calcule la statistique D_KS entre la distribution empirique d'une feature normalisée et une loi normale standard (éq. 4.5), via comparaison ECDF / CDF théorique.
- `ks_per_feature()` : applique le test KS à toutes les features **continues** (BINARY_FEATURES exclues). Calcule ks_mean uniquement sur ces features, et liste dans `features_needing_transform` celles dont D_KS ≥ 0,15. Ce seuil correspond à la limite de régularité B-spline degrée 3 (section 4.1.4).
- `grid_coverage()` : pour chaque feature continue (BINARY_FEATURES exclues), calcule le ratio d'amplitude normalisée sur la grille provisoire [-3, 3] (éq. 4.6). Un ratio hors de [0,8 ; 1,0] indique une feature sous-couverte ou dépassant la grille.
- `decide()` : applique la règle de décision éq. 4.7 en trois branches : "KAN valide" (J_Fisher > 1, VE2 ≥ 40 %, D_KS_mean < 0,15), "Transformations requises" (J_Fisher > 1 mais features non conformes), "Architecture alternative" (Fisher insuffisant).
- `run_full_validation()` : enchaîne normalize → pca → fisher_index → ks_per_feature → grid_coverage → decide et retourne le rapport complet.
- `run_full_validation_with_retry(max_retries=1)` : implémente le protocole complet de la section 4.1.5. Si la décision est "Transformations requises", applique `apply_recommended_transforms()`, reconstruit un nouveau `TopologyValidator` sur les données transformées, relance la validation et met à jour l'état interne de `self` (pour que `plot_*()` reflète l'état post-transformation). Borné à `max_retries` itérations pour éviter une boucle infinie. En cas d'échec après épuisement des essais, ajoute un champ `transform_warning` au rapport.
- `apply_recommended_transforms()` : applique log(1+x) sur les features listées dans `features_needing_transform`. Gère les valeurs négatives par décalage (shift = −min) avant application.
- `plot_pca_projection()` : scatter 2D dans l'espace des deux premières composantes principales, coloré par classe (légitime / fraude).
- `plot_ks_summary()` : histogramme des D_KS par feature (features continues uniquement), avec ligne seuil à 0,15.

#### `MoMTSimVisualizer`
**Rôle :** Visualisations exploratoires des données simulées.

**Entrées :** le DataFrame de features, optionnellement un DataFrame de données cibles agrégées pour la comparaison NRMSE.

**Méthodes :**

- `plot_volume_per_action()` : courbes de volume de transactions par step et par type d'action.
- `plot_nrmse_comparison(action)` : superposition simulé vs cible pour une action donnée, avec calcul du NRMSE normalisé — utilisée pour la validation SSE du simulateur.
- `plot_fraud_scenario_distribution()` : histogramme de répartition des transactions frauduleuses par scénario.
- `plot_fraud_timeline()` : évolution temporelle (720 steps) des fraudes par scénario.
- `plot_r1_r2_scatter()` : nuage de points r1 vs r2 coloré par classe — visualise la séparabilité du scénario ATO.
- `plot_feature_distributions()` : histogrammes superposés (légitime vs fraude) pour une sélection de features continues.
- `plot_smurfing_network_delta()` : distribution de la commission mule observée (delta_commission_ratio), séparée entre mules SMURFING confirmées et candidates légitimes, avec seuil vertical à 10 % (Zhdanova et al.).

---

### 2.5 `backend/pipeline_runner.py`

Orchestrateur asynchrone du pipeline, exposé via FastAPI. Utilise des threads Python avec un store in-memory (`_jobs`) pour gérer les jobs de longue durée.

**Fonctions principales :**

- `start_simulation(p)` / `_run_simulation_bg(job_id, p)` : exécute TorchParameters → TorchMoMTSimEngine → TorchFraudInjector sur 720 steps et sauvegarde `rawLog_torch.csv`.
- `start_features(job_id)` / `_run_features_bg(job_id)` : charge rawLog_torch.csv, appelle `FeatureEngineer.compute_all()`, sauvegarde `featuresLog.csv`.
- `start_kan_validation(job_id)` / `_run_kan_bg(job_id)` : charge featuresLog.csv, instancie `TopologyValidator`, appelle `run_full_validation_with_retry(max_retries=1)`, génère les graphiques et retourne le rapport complet (incluant les champs `transform_applied` et `transform_warning` si applicable).
- `start_calibration(p)` / `_run_calibration_bg(job_id, p)` : lance la calibration SSE/SPSA via `SSEFraudCalibrator` et sauvegarde les probabilités optimisées.
- `get_job(job_id)`, `list_jobs()` : interrogent le store in-memory.

---

### 2.6 Fichiers CSV attendus

| Fichier | Rôle | Produit par |
|---|---|---|
| `paramFiles/clientsProfiles.csv` | Profils comportementaux par action (mean, std, poids, bornes) | Fourni (données calibrées) |
| `paramFiles/aggregatedTransactions.csv` | Volume horaire cible par action (720 steps) | Fourni |
| `paramFiles/initialBalancesDistribution.csv` | Distribution empirique des soldes initiaux (tranches) | Fourni |
| `paramFiles/overdraftLimits.csv` | Limites de découvert par tranche de montant moyen | Fourni |
| `paramFiles/maxOccurrencesPerClient.csv` | Nombre max de transactions par client et par mois | Fourni |
| `rawLog_torch.csv` | Log brut de la simulation (toutes transactions) | Phase 0 (`momtsim_torch.py`) |
| `featuresLog.csv` | Log enrichi des 12 features par transaction | Phase 1 (`features.py`) |
| `calibrated_probas.json` | Probabilités de fraude calibrées par SPSA | Calibration SSE (`calibration_sse.py`) |

---

## 3. Les quatre corrections apportées dans ce chat

### Correction 1 — `features.py` : fenêtre temporelle manquante dans l'appariement mule (Smurfing)

**Problème initial :** La fonction `_delta_commission_smurfing()` utilisait `pd.merge_asof(direction="backward")` sans aucune contrainte de délai. Pour chaque transaction sortante d'un compte, elle recherchait la dernière transaction entrante dans tout l'historique passé, quelle que soit la distance temporelle. Un compte pouvait donc être marqué `is_mule_candidate=True` par coïncidence de ratio sur des transactions séparées de plusieurs semaines — sans lien causal réel avec le scénario Smurfing.

**Pourquoi c'était un problème :** Le mémoire (section 3.2.5) définit explicitement le délai de transfert mule comme Δt_mule ~ U(2h, 24h). Le critère 1 de Zhdanova et al. (section 1.4.4, repris en 3.2.6) qualifie la mule candidate par une paire de transactions liées temporellement. Un appariement sans borne de délai produit des faux positifs non pertinents et contredit directement la définition du scénario simulé.

**Ce qui a été changé :** Ajout d'un paramètre `mule_tolerance_steps` dans `FeatureEngineer.__init__()` (défaut : 48 steps). Ce paramètre est passé à `pd.merge_asof` via le paramètre `tolerance`. La valeur 48 correspond à `delay_mule_max_hours × 2 = 24 × 2`, une marge conservatrice (facteur ×2) sur la fenêtre [2h, 24h] du mémoire, pour absorber les arrondis horaires du simulateur. Toute paire dont l'écart `step_out − step_in` dépasse 48 steps produit un NaN dans `step_in` après le merge — le compte ne reçoit pas `is_mule_candidate=True`.

---

### Correction 2 — `viz.py` : le test KS traitait les flags binaires comme des variables continues

**Problème initial :** `ks_per_feature()` appliquait le test de Kolmogorov-Smirnov contre une loi normale à la totalité des 12 features de FEATURES_12, y compris `flag_nuit` et `flag_anomalie`. Ces deux variables sont des indicatrices {0, 1} : elles ne possèdent que deux points de masse et ne peuvent mathématiquement jamais ressembler à une loi normale continue. Le résultat était un D_KS systématiquement élevé pour ces deux features, qui apparaissaient invariablement dans `features_needing_transform` — faussant `ks_mean` (critère de la règle éq. 4.7) et suggérant d'appliquer log(1+x) à un booléen, ce qui est sans sens.

**Pourquoi c'était un problème :** La section 4.1.4 du mémoire précise que le test KS mesure la régularité des distributions marginales sur lesquelles les B-splines de chaque arête KAN opèrent. Ce critère (D_KS < 0,15) n'a de sens que pour des features continues destinées à être approchées par des splines. Les indicatrices booléennes ne sont pas approximées de la même façon — elles n'ont pas vocation à être transformées par log1p.

**Ce qui a été changé :** Ajout d'une constante de module `BINARY_FEATURES = ["flag_nuit", "flag_anomalie"]`, documentée. Dans `ks_per_feature()`, les features de `BINARY_FEATURES` sont sautées ; `ks_mean` est calculé uniquement sur les features continues restantes. Dans `grid_coverage()`, les mêmes features sont exclues (une grille B-spline sur [-3, 3] n'a pas de sens pour une indicatrice). Les deux features binaires sont ainsi transmises telles quelles au pipeline KAN sans être signalées à tort.

---

### Correction 3 — `viz.py` : la règle de décision (éq. 4.7) n'était pas bouclée

**Problème initial :** `apply_recommended_transforms()` existait mais n'était jamais appelée automatiquement en réponse à une décision "Transformations requises". Le pipeline s'arrêtait à l'affichage de la liste des features à transformer, sans revalider les données après transformation. Dans `pipeline_runner.py`, les 5 étapes de validation (normalize, pca, fisher_index, ks_per_feature, grid_coverage, decide) étaient appelées séquentiellement sans mécanisme de retry.

**Pourquoi c'était un problème :** La section 4.1.5 du mémoire décrit une étape explicite du protocole : si le test KS signale des features non conformes, celles-ci sont transformées avant transmission au pipeline d'entraînement KAN. Ce n'est pas une option laissée à l'utilisateur — c'est une boucle transform → revalidation complète qui doit s'exécuter automatiquement.

**Ce qui a été changé :** Ajout de la méthode `run_full_validation_with_retry(max_retries=1)` dans `TopologyValidator`. Cette méthode exécute `run_full_validation()`, et si la décision est "Transformations requises", applique `apply_recommended_transforms()`, construit un nouveau `TopologyValidator` sur les données transformées, relance la validation complète, et copie l'état du nouveau validateur dans `self` (pour que `plot_pca_projection()` et `plot_ks_summary()` reflètent l'état post-transformation). La boucle est bornée à `max_retries` itérations : si le test KS reste positif après épuisement des essais, un champ `transform_warning` est ajouté au rapport. `_run_kan_bg()` dans `pipeline_runner.py` a été simplifié pour utiliser cette seule méthode (2 champs supplémentaires `transform_applied` et `transform_warning` sont exposés dans le résultat).

---

### Correction 4 — `viz.py` : hypothèse de grille [-3, 3] non documentée comme provisoire

**Problème initial :** `grid_coverage()` supposait une grille B-spline sur [-3, 3] sans aucun commentaire indiquant que cette hypothèse est provisoire. Cette valeur n'est reliée à aucune architecture KAN réelle, car celle-ci n'est pas encore implémentée dans le périmètre du projet (section 4.2 du mémoire).

**Ce qui a été changé :** Ajout d'un commentaire explicite au-dessus de la méthode indiquant que les bornes [-3, 3] sont une hypothèse provisoire fondée sur la convention post-normalisation z-score (convention qui couvre ~99,7 % de la masse gaussienne théorique), et qu'elles devront être révisées une fois l'architecture MKAN réellement définie (section 4.2, hors périmètre Phase 1). Aucune valeur n'a été modifiée.

---

## 4. Limites et hypothèses restantes

### 4.1 Grille tarifaire du Split Deposit et valeur de S_seuil

La grille tarifaire dans `fraudScenariosConfig.json` (section `split_deposit.tariff_grid`) et le seuil de structuration `S_seuil = 500 000` (section `smurfing`) ne sont pas issus de données réelles de Mobile Money camerounais. Ces valeurs sont des approximations vraisemblables. Pour une validation empirique du scénario Split Deposit, il faudrait calibrer la grille sur des données tarifaires réelles d'opérateurs CEMAC (MTN MoMo, Orange Money). Cette limitation est assumée pour la Phase 0 mais devra être signalée dans le mémoire.

### 4.2 Forme temporelle de la calibration SSE (Dr)

Le calibrateur `SSEFraudCalibrator` optimise les probabilités de déclenchement par scénario par SPSA pour minimiser l'erreur quadratique entre le volume horaire simulé et la cible. La forme de la courbe de demande cible `Dr(step)` est interpolée depuis `aggregatedTransactions.csv`, dont les données d'origine ne sont pas documentées dans le code comme issues de données réelles. Si ces données sont synthétiques ou issues d'une autre source que des logs CEMAC réels, la calibration SSE mesure une cohérence interne du simulateur plutôt qu'un calage sur le monde réel.

### 4.3 Hypothèse de grille B-spline [-3, 3]

Comme documenté dans le code (correction 4), les bornes [-3, 3] de `grid_coverage()` sont provisoires. Elles seront à réviser après la définition de l'architecture MKAN (section 4.2 du mémoire). En particulier, si les features présentent des queues lourdes après log-transformation, les bornes optimales pourraient différer significativement.

### 4.4 Granularité horaire vs délai Split Deposit

Le simulateur opère à une granularité de 1 step = 1 heure. Le paramètre `T_split_min_sec` / `T_split_max_sec` (60–120 secondes dans la config) n'est pas utilisé dans la simulation puisque le simulateur ne résout pas les secondes. Les fragments du Split Deposit sont logés au même step, ce qui est documenté dans `features.py` comme une limitation assumée (le commentaire précise "équivalent de la fenêtre 60–120s puisque le simulateur les génère simultanément au même step").

### 4.5 Appariement mule pour les transactions non-TRANSFER

Le test `is_mule_candidate` dans `_delta_commission_smurfing()` se limite aux transactions de type TRANSFER. Dans le scénario Smurfing réel, une mule peut aussi recevoir des CASH_IN et envoyer des PAYMENT. Cette limitation est héritée de la modélisation du scénario dans `momtsim_torch.py` (qui génère uniquement des TRANSFER pour la chaîne émetteur→mule→récepteur).

### 4.6 Absence de window sur le test de revalidation

`run_full_validation_with_retry` est borné à `max_retries=1`. Si une seconde transformation log1p ne suffit pas (features avec distributions multimodales ou très asymétriques), le pipeline retourne un avertissement mais ne propose pas d'alternative (Box-Cox, transformation puissance, etc.). Cette limitation est délibérée pour la Phase 1 et devra être adressée si l'architecture KAN est effectivement sensible à la régularité des distributions d'entrée.
