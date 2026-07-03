# Analyse complète du projet MoMTSim

> Simulateur multi-agents de transactions de mobile money avec génération de fraudes synthétiques.  
> Langage : Java — Moteur de simulation : MASON — Données cibles : contexte africain (monnaie mobile)

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture du projet](#2-architecture-du-projet)
3. [Le modèle mathématique](#3-le-modèle-mathématique)
4. [Les types de fraude](#4-les-types-de-fraude)
5. [Flux d'exécution principal](#5-flux-dexécution-principal)
6. [Les paramètres d'entrée](#6-les-paramètres-dentrée)
7. [Les agents et leurs comportements](#7-les-agents-et-leurs-comportements)
8. [Structures de données clés](#8-structures-de-données-clés)
9. [Production des résultats](#9-production-des-résultats)
10. [Décomposition classe par classe](#10-décomposition-classe-par-classe)

---

## 1. Vue d'ensemble

MoMTSim est un **simulateur de transactions financières synthétiques**. Son objectif est de produire un jeu de données réaliste de transactions de mobile money (paiements par téléphone mobile, typiques d'Afrique subsaharienne) accompagné de cas de fraude étiquetés, utilisable pour entraîner ou évaluer des algorithmes de détection de fraude.

Le programme génère un fichier CSV contenant des centaines de milliers de transactions, chacune étant décrite par : qui paie, qui reçoit, combien, quel type d'opération, et si la transaction est frauduleuse ou non.

La simulation fonctionne sur **720 pas de temps** (720 heures = 30 jours) pendant lesquels des milliers d'agents (clients, marchands, banques, fraudeurs) interagissent selon des règles probabilistes calées sur des données réelles.

---

## 2. Architecture du projet

Le code est organisé en sept packages Java :

### `org.momtsim` — Cœur de la simulation
Contient le point d'entrée (`MoMTSimApp`), la classe d'état de la simulation (`MoMTSimState`) et une variante itérative (`IteratingMoMTSim`) qui expose les transactions comme un flux Java.

### `org.momtsim.actors` — Les agents
Toutes les entités qui peuplent la simulation : clients, marchands, banques, fraudeurs, mules. Chaque agent qui agit de façon autonome implémente l'interface `Steppable` de MASON, ce qui signifie qu'il possède une méthode `step()` appelée à chaque pas de temps.

### `org.momtsim.base` — Objets métier fondamentaux
La classe `Transaction` (enregistrement d'une opération) et les classes de profil comportemental (`ClientProfile`, `ClientActionProfile`, `StepActionProfile`).

### `org.momtsim.identity` — Gestion des identités
Fabrique et représentation des identités des acteurs (noms, e-mails, numéros de téléphone, identifiants) générées via la bibliothèque `jFairy`.

### `org.momtsim.parameters` — Chargement de la configuration
Lecture du fichier `.properties` et des six fichiers CSV de paramètres. Ces classes transforment les données brutes en objets utilisables par la simulation.

### `org.momtsim.output` — Export des résultats
Écriture des fichiers de sortie : log brut de toutes les transactions, statistiques agrégées par heure, résumé des fraudeurs, métriques d'erreur (NRMSE).

### `org.momtsim.utils` — Utilitaires
Lecture CSV, sélection aléatoire pondérée (`RandomCollection`), file bornée (`BoundedArrayDeque`), accès base de données MySQL optionnel, et utilitaires de graphe pour le module réseau de drogue (désactivé).

---

## 3. Le modèle mathématique

### 3.1 Nombre de transactions d'un client à une étape donnée

À chaque pas de temps, chaque client tire son nombre de transactions d'une **loi binomiale** :

```
nombre_transactions = B(stepTargetCount, clientWeight)
```

où :
- `stepTargetCount` est le nombre total de transactions attendues à cette heure précise (lu dans les données historiques)
- `clientWeight = targetCount_du_profil / totalTargetCount` est la part que ce client représente dans la population

Cela garantit que le volume global de transactions reste conforme aux données cibles, tout en laissant chaque client agir de façon indépendante.

### 3.2 Montant d'une transaction

Le montant est tiré d'une **loi normale** :

```
montant = N(μ, σ)
```

avec :
- `μ = (moyenne_profil_client + moyenne_profil_étape) / 2`
- `σ = sqrt((std_client² + std_étape²)) / 2`

Si le montant tiré est négatif ou nul, on retire à nouveau jusqu'à obtenir un montant valide.

### 3.3 Choix du type d'action (Spring Model)

C'est l'algorithme le plus sophistiqué du projet. Il détermine quelle action (dépôt, retrait, paiement, etc.) un client va effectuer en tenant compte de trois facteurs :
1. Les probabilités de son **profil personnel**
2. Les probabilités de l'**heure courante** (certaines actions sont plus fréquentes le matin, etc.)
3. Son **solde courant** par rapport à un équilibre cible

Le troisième point est géré par un **modèle de ressort** : si le solde du client est très bas, il sera poussé vers des actions qui font entrer de l'argent (dépôts), et vice versa. La force de rappel est calculée ainsi :

```
equilibrium = 40 × montant_moyen_attendu
k = 1 / equilibrium
springForce = k × (equilibrium - solde_courant)

nouvelleProbEntrée = 0.5 × (1 + correctionStrength × springForce + (probEntrée - probSortie))
```

Le résultat est borné entre 0 et 1, puis appliqué en facteur multiplicatif sur les probabilités brutes pour les recaler.

### 3.4 Stickiness — fidélité aux marchands et aux clients connus

Lorsqu'un client doit choisir un marchand ou un autre client pour une transaction :
- Avec une probabilité de **90 %**, il réutilise un acteur avec lequel il a déjà interagi (liste des 100 derniers)
- Avec **10 %** de chance, il choisit un nouvel acteur au hasard dans la population
- Si un client inconnu est choisi, il devient un "ami" avec **90 %** de probabilité (ajouté à la liste des interlocuteurs mémorisés)

### 3.5 Gestion des soldes et découverts

Chaque client dispose d'un **solde initial** tiré d'une distribution empirique (67 % des clients commencent avec 0–99 unités). La limite de découvert autorisée dépend du montant moyen des transactions du client :

| Plage de montant moyen | Limite de découvert |
|------------------------|---------------------|
| < 0                    | 0                   |
| 0 – 50 000             | −25 000             |
| 50 000 – 100 000       | −75 000             |
| 100 000 – 200 000      | −150 000            |
| > 200 000              | −200 000            |

Une transaction est refusée si elle ferait passer le solde en dessous de la limite de découvert.

### 3.6 Détection de fraude intégrée (règle métier)

Une règle de détection simpliste est implémentée nativement pour les transferts :

```
Si le client a effectué au moins 3 transferts
ET que (soldeMax - soldeCourant - montant) > transferLimit × 2,5
→ La transaction est marquée comme suspectée frauduleuse (isFlaggedFraud = true)
```

La limite de transfert par défaut est 5 000 000 unités.

---

## 4. Les types de fraude

### 4.1 Third Party Fraud (fraude tiers — compte compromis)

C'est la fraude principale, active par défaut avec une probabilité de **80 %** par pas de temps.

Le fraudeur possède :
- Une **mule** (compte de retrait sous son contrôle)
- Deux **marchands favoris** marqués à haut risque (il a compromis leur terminal)

À chaque pas de temps, il procède ainsi :
1. Il sélectionne une victime — de préférence un client qui fréquente ses marchands compromis, sinon un client aléatoire
2. Il effectue un **paiement test** (PAYMENT) d'environ 25 % du montant moyen de la victime, pour vérifier que le compte est accessible
3. Si le paiement réussit, il effectue un **transfert** (TRANSFER) vers sa mule, également pour environ 25 % du montant moyen
4. Ce transfert est marqué frauduleux avec une probabilité de 30 %
5. Avec une probabilité de 30 %, la mule effectue ensuite un **retrait en espèces** (CASH_OUT) frauduleux

### 4.2 First Party Fraud (fraude interne — fausse identité)

Activée avec la probabilité `firstPartyFraudProbability` (réglée à 0 par défaut, donc inactive dans la configuration standard).

Le fraudeur crée de fausses identités composites en mélangeant des données volées (SSN, e-mail, téléphone de trois identités différentes), ouvre des comptes de mule et transfère des fonds vers un compte de retrait final.

### 4.3 Direct Deposit Fraud

Variante du fraudeur tiers qui utilise un dépôt en espèces (CASH_IN) au lieu d'un paiement marchand comme transaction initiale.

### 4.4 Refund Fraud

Enchaîne un paiement marchand et un transfert pour simuler un schéma de remboursement frauduleux.

### 4.5 Split Deposit Fraud

Fractionne une somme en 1 à 10 petits dépôts CASH_IN vers le même marchand, stratégie cherchant à passer sous les seuils de détection. Tous ces dépôts sont marqués frauduleux.

---

## 5. Flux d'exécution principal

### Démarrage

Le programme lit le fichier `MoMTSim.properties` et instancie l'ensemble des paramètres. Il peut exécuter la simulation plusieurs fois si `nbTimesRepeat > 1`, chaque exécution produisant un dossier de sortie horodaté distinct.

### Initialisation de la population

À l'ouverture de chaque simulation :
1. Les **banques** sont créées et enregistrées dans le moteur MASON
2. Les **marchands** sont créés ; 90 % d'entre eux sont marqués à haut risque
3. Les **fraudeurs** sont créés : 50 % de type tiers (chacun choisit 2 marchands à haut risque comme "favoris"), 50 % de type premier parti
4. Les **clients** sont créés, chacun recevant un profil comportemental tiré aléatoirement, un solde initial et une limite de découvert

Chaque agent actif (client, fraudeur) est enregistré dans le planificateur de MASON avec `scheduleRepeating`, ce qui signifie que sa méthode `step()` sera appelée automatiquement à chaque pas de temps.

### La boucle de simulation

À chaque pas de temps :
1. MASON appelle `step()` sur chaque agent enregistré
2. Chaque client décide combien de transactions faire et les exécute
3. Chaque fraudeur décide s'il agit et effectue ses opérations malveillantes
4. Les transactions générées sont collectées par l'application
5. Elles sont immédiatement écrites dans les fichiers de sortie (mode append) pour économiser la mémoire
6. La console affiche une étoile toutes les 10 étapes

### Clôture

Une fois les 720 pas écoulés :
- Le fichier des fraudeurs est écrit (profits, victimes)
- La distribution des profils clients est exportée
- Un résumé des erreurs (NRMSE) comparant les statistiques simulées aux données cibles est calculé et sauvegardé

---

## 6. Les paramètres d'entrée

### Fichier `MoMTSim.properties`

Ce fichier texte centralise toute la configuration :

| Paramètre | Valeur par défaut | Signification |
|-----------|-------------------|---------------|
| `seed` | 1000 | Graine du générateur de nombres aléatoires |
| `nbSteps` | 720 | Nombre de pas de temps (heures) |
| `multiplier` | 1 | Facteur de mise à l'échelle de la population |
| `nbClients` | 2000 | Nombre de clients |
| `nbFraudsters` | 100 | Nombre de fraudeurs |
| `nbMerchants` | 300 | Nombre de marchands |
| `nbBanks` | 20 | Nombre de banques |
| `firstPartyFraudProbability` | 0.000 | Probabilité qu'un fraudeur interne agisse |
| `thirdPartyFraudProbability` | 0.80 | Probabilité qu'un fraudeur tiers agisse |
| `thirdPartyNewVictimProbability` | 0.40 | Probabilité de cibler une nouvelle victime |
| `merchantReuseProbability` | 0.90 | Fidélité aux marchands déjà utilisés |
| `thirdPartyPercentHighRiskMerchants` | 0.90 | Part des marchands marqués à haut risque |
| `transferLimit` | 5 000 000 | Seuil de détection des gros transferts |

La graine peut être réglée sur `"time"` pour utiliser l'horloge système, rendant chaque exécution unique.

### Fichiers CSV dans `paramFiles/`

**`transactionsTypes.csv`** — Liste les six types d'actions valides : CASH_IN, CASH_OUT, DEBIT, PAYMENT, TRANSFER, DEPOSIT.

**`clientsProfiles.csv`** — Décrit la distribution des comportements clients. Pour chaque type d'action, il y a plusieurs profils possibles, chacun avec un nombre minimum et maximum de transactions par mois, un montant moyen, un écart-type, et un poids de fréquence. Exemple : un profil CASH_IN prévoit entre 10 et 99 transactions avec un montant moyen de 72 111 unités.

**`aggregatedTransactions.csv`** — Donne le nombre attendu de transactions, la somme, la moyenne et l'écart-type par type d'action et par heure sur 30 jours. C'est la "vérité terrain" que la simulation cherche à reproduire.

**`initialBalancesDistribution.csv`** — Décrit la distribution des soldes initiaux des clients en tranches. 67,14 % des clients commencent avec un solde entre 0 et 99 unités.

**`overdraftLimits.csv`** — Associe une plage de montant moyen de transaction à une limite de découvert (montant négatif maximal autorisé).

**`maxOccurrencesPerClient.csv`** — Nombre maximum de transactions de chaque type qu'un client peut effectuer sur toute la simulation.

---

## 7. Les agents et leurs comportements

### SuperActor — la classe de base

Tous les agents héritent de `SuperActor`. Cette classe fournit :
- Un **solde** (`balance`) et une **limite de découvert** (`overdraftLimit`)
- Les méthodes `deposit()` et `withdraw()` avec vérification du découvert
- Un **historique des 100 derniers clients** avec lesquels l'acteur a interagi (file bornée)
- Un énuméré `Type` : BANK, CLIENT, FIRST_PARTY_FRAUDSTER, THIRD_PARTY_FRAUDSTER, MERCHANT, MULE

### Client — l'agent central

C'est l'agent qui génère la grande majorité des transactions. À chaque pas de temps, il :
1. Calcule son nombre de transactions via la loi binomiale
2. Pour chaque transaction, choisit l'action via le spring model
3. Choisit le montant via la loi normale
4. Choisit l'interlocuteur (marchand ou autre client) avec la règle de stickiness
5. Exécute la transaction et met à jour les soldes des deux parties

Le client possède un profil comportemental qui définit la distribution de ses types de transactions, et un poids (`clientWeight`) qui détermine à quelle fréquence il est "tiré au sort" pour agir.

### Merchant — agent passif

Un marchand reçoit des paiements, des dépôts et des retraits mais n'initie rien. Il est simplement une destination dans les transactions. Il peut être marqué "à haut risque", ce qui signifie que les fraudeurs le ciblent préférentiellement.

### Bank — agent passif

Une banque reçoit des débits et des dépôts directs. Comportement identique au marchand, seulement passif.

### Mule — compte fantoche

Une mule étend la classe Client mais sa méthode `step()` ne fait rien — elle est inerte dans la simulation normale. Son seul rôle actif est la méthode `fraudulentCashOut()`, appelée par le fraudeur qui la contrôle pour retirer l'argent transféré illicitement.

### ThirdPartyFraudster — fraudeur externe

C'est le fraudeur le plus actif. Il maintient une liste de victimes et deux marchands compromis. À chaque pas de temps, il tente une séquence paiement-test → transfert → retrait selon les probabilités décrites dans la section fraude.

### FirstPartyFraudster — fraudeur interne

Inactif par défaut. Lorsqu'il agit, il génère de fausses identités composites (mix de données volées à trois personnes réelles) et crée des comptes mules pour blanchir des fonds.

---

## 8. Structures de données clés

### RandomCollection

C'est la structure centrale pour toutes les sélections aléatoires pondérées. Elle utilise une `NavigableMap` dont les clés sont des poids cumulatifs. Pour tirer un élément, on génère un nombre aléatoire entre 0 et le poids total, puis on cherche l'entrée immédiatement supérieure dans la map. C'est un tirage en O(log n).

La graine du générateur Mersenne Twister peut être fixée pour la reproductibilité.

### BoundedArrayDeque

Une file à deux bouts (`ArrayDeque`) avec une taille maximale fixe (100 par défaut). Dès qu'un élément est ajouté et que la taille est atteinte, l'élément le plus ancien est retiré. Utilisée pour mémoriser les 100 derniers interlocuteurs de chaque acteur, sans consommer de mémoire infinie.

### Transaction

Un objet immuable (dans les faits) qui capture l'état complet d'une opération : le pas de temps, le type, le montant, l'identité et le solde avant/après des deux parties, et quatre drapeaux booléens (isFraud, isFlaggedFraud, isUnauthorizedOverdraft, isSuccessful).

### Profils par étape (StepsProfiles)

Une liste de 720 maps, une par heure. Chaque map associe un type d'action à son profil pour cette heure (nombre cible, somme, moyenne, écart-type). C'est la carte de référence que la simulation cherche à reproduire statistiquement.

---

## 9. Production des résultats

### Fichiers générés

Tous les fichiers sont écrits dans `outputs/MoMTSim_<timestamp>_<seed>/` :

**`rawLog.csv`** — Le fichier principal. Chaque ligne est une transaction avec les colonnes : step, action, amount, nameOrig, oldBalanceOrig, newBalanceOrig, nameDest, oldBalanceDest, newBalanceDest, isFraud. C'est ce fichier qui sera utilisé pour entraîner un modèle de détection.

**`aggregatedTransactions.csv`** — Statistiques par heure et par type d'action (count, sum, avg, std), permettant de comparer le comportement simulé aux données cibles.

**`fraudsters.csv`** — Résumé par fraudeur : nom, type, nombre de victimes, liste des victimes, profit total.

**`clientsProfiles.csv`** — Distribution des profils comportementaux attribués aux clients.

**`MoMTSim.properties`** (copie) — Paramètres utilisés pour cette exécution, pour la traçabilité.

**`Summary.txt`** — Métriques de qualité de la simulation.

### Métriques de qualité : le NRMSE

Pour mesurer à quel point la simulation ressemble aux données réelles, on calcule le **NRMSE (Normalized Root Mean Square Error)** pour trois estimateurs (montant moyen, écart-type, nombre de transactions) et pour chaque type d'action :

```
RMSE = sqrt( Σ(simulé[i] - cible[i])² / n )
NRMSE = RMSE / (max_cible - min_cible)
```

Plus le NRMSE est proche de 0, plus la simulation est fidèle aux données historiques.

### Écriture incrémentale

Pour ne pas accumuler toutes les transactions en mémoire, les fichiers sont écrits pas à pas en mode append. À la fin de chaque pas de temps, les transactions de cette heure sont écrites puis supprimées de la liste en mémoire.

---

## 10. Décomposition classe par classe

### Package `org.momtsim`

**`MoMTSimApp`**  
Point d'entrée et orchestrateur. Lit les paramètres, crée le dossier de sortie, lance la boucle de simulation, collecte les transactions à chaque étape via `onTransactions()` et déclenche l'export final dans `finish()`.

**`MoMTSimState`**  
Classe abstraite héritant de `SimState` (MASON). Maintient les listes de tous les acteurs et la map de comptage des profils. Fournit les méthodes de sélection aléatoire (`pickRandomMerchant`, `pickRandomClient`, etc.) et délègue aux paramètres pour le profil de l'étape courante.

**`IteratingMoMTSim`**  
Alternative à `MoMTSimApp` pour un usage en flux. La simulation tourne dans un thread séparé (`SimulationWorker`) et place les transactions dans une `BlockingQueue` de 200 000 places. La classe implémente `Iterator<Transaction>`, permettant à un consommateur externe de traiter les transactions une par une au fil de leur génération.

---

### Package `org.momtsim.actors`

**`SuperActor`** — Base abstraite de tous les agents. Gère solde, découvert, historique.

**`Client`** — Agent actif principal. Implémente la logique de tirage binomial, spring model, stickiness, et dispatch des six types de transactions.

**`Merchant`** — Agent passif. Possède une identité et un drapeau `highRisk`.

**`Bank`** — Agent passif. Reçoit débits et dépôts.

**`Mule`** — Sous-classe de `Client` avec `step()` vide. Méthode active : `fraudulentCashOut()`.

**`FirstPartyFraudster`** — Crée des identités composites frauduleuses et des mules. Inactif par défaut.

**`ThirdPartyFraudster`** — Agent fraudeur principal : sélectionne victimes, enchaîne PAYMENT + TRANSFER, déclenche le cash-out de sa mule.

**`DirectDepositFraudster`** — Variante : remplace le PAYMENT par un CASH_IN.

**`RefundFraudster`** — Variante : simule un schéma de remboursement frauduleux.

**`SplitDepositFraudster`** — Variante : fractionne un montant en 1 à 10 petits CASH_IN.

---

### Package `org.momtsim.base`

**`Transaction`** — Enregistrement complet d'une opération : step, action, montant, identité + soldes avant/après des deux parties, quatre drapeaux booléens.

**`ClientProfile`** — Profil comportemental d'un client : map action → `ClientActionProfile`, probabilités d'action calculées, nombre total de transactions cible.

**`ClientActionProfile`** — Profil pour une action spécifique : plage de nombre de transactions, montant moyen et écart-type.

**`StepActionProfile`** — Profil d'une heure pour une action donnée : count, sum, avg, std, mois/jour/heure.

---

### Package `org.momtsim.parameters`

**`Parameters`** — Lit `MoMTSim.properties` et instancie toutes les sous-classes de paramètres. Gère `seed="time"` en convertissant l'horloge système.

**`ActionTypes`** — Classe statique. Charge les types d'actions valides et les occurrences maximales par client.

**`ClientsProfiles`** — Charge `clientsProfiles.csv`. Pour chaque action, maintient une `RandomCollection` permettant de tirer un profil proportionnellement à sa fréquence.

**`StepsProfiles`** — Charge `aggregatedTransactions.csv`. Construit la liste des 720 profils horaires, calcule les probabilités d'action par étape et le nombre cible total de transactions.

**`BalancesClients`** — Classes statiques. Charge les distributions de soldes initiaux et de découverts. Expose `pickNextBalance()` et `getOverdraftLimit(meanTx)`.

---

### Package `org.momtsim.output`

**`Output`** — Classe statique avec toutes les méthodes d'écriture fichier. Initialise les noms de fichiers à la création de la simulation, puis les méthodes `incrementalWrite*` sont appelées à chaque pas et les méthodes `write*` à la clôture.

**`Aggregator`** — Calcule les statistiques agrégées (sum, count, avg, std avec correction de Bessel) à partir d'une liste de transactions, filtrées par action et en excluant les transactions échouées.

**`SummaryBuilder`** — Calcule le NRMSE en comparant les séries temporelles simulées aux séries cibles pour chaque action et chaque estimateur statistique.

---

### Package `org.momtsim.identity`

**`IdentityFactory`** — Utilise `jFairy` pour générer des noms, e-mails, SSN et numéros de téléphone réalistes. Maintient des ensembles de numéros déjà utilisés pour garantir l'unicité.

**`Identity`** — Classe abstraite : id + name.

**`ClientIdentity`** — Ajoute email, SSN, phoneNumber. Méthode `replaceProperty()` pour créer des identités composites (fraude premier parti).

**`MerchantIdentity`** — Ajoute le drapeau `highRisk`.

**`BankIdentity`** — Préfixe l'identifiant avec "B".

---

### Package `org.momtsim.utils`

**`RandomCollection<E>`** — Sélection pondérée en O(log n) via `NavigableMap` à poids cumulatifs.

**`BoundedArrayDeque<T>`** — File bornée à 100 éléments par défaut.

**`CSVReader`** — Lecture simple de fichiers CSV : ignore l'en-tête, split par virgule.

**`DatabaseHandler`** — Insert optionnel dans MySQL via JDBC. Activé si `saveToDB=1` dans les propriétés.

**`GraphUtils`** — Utilitaires TinkerGraph pour charger le réseau de trafic de drogue (module désactivé).

---

### Package `org.momtsim.actors.networkdrugs` (désactivé)

**`NetworkDrug`** — Charge un graphe XML (`DrugNetworkOne.graphml`) et crée des agents `DrugDealer` et `DrugConsumer` selon la topologie du réseau.

**`DrugDealer`** — Étend `Client`. Accumule de l'argent de drogue dans un compteur séparé et effectue un retrait en espèces quand le seuil est atteint.

**`DrugConsumer`** — Étend `Client`. Calcule une probabilité d'achat basée sur ses dépenses mensuelles et le montant moyen des transactions. Effectue un transfert vers son dealer quand il souhaite acheter.

---

*Ce module réseau de drogue est présent dans le code mais n'est jamais instancié dans la simulation principale. Il était probablement prévu pour une extension du projet.*
