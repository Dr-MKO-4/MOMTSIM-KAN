"""
MoMTSim-KAN — Réimplémentation Python/NumPy de MoMTSim
adaptée aux 5 scénarios de fraude formalisés au Chapitre 3
du mémoire (ATO, Refund Fraud, Fake Credentials, Split Deposit, Smurfing).

Dépendances : numpy, pandas
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from collections import deque
from enum import Enum, auto
from typing import Optional
import bisect
import uuid
import json  # pour fraudScenariosConfig.yaml

RNG = np.random.default_rng(1000)  # graine globale, remplaçable

# ---------------------------------------------------------------------------
# 1. UTILITAIRES (équivalents RandomCollection / BoundedArrayDeque)
# ---------------------------------------------------------------------------

class RandomCollection:
    """Tirage pondéré O(log n) via cumul de poids (équiv. NavigableMap Java)."""
    def __init__(self):
        self._items = []
        self._cum_weights = []
        self._total = 0.0

    def add(self, weight: float, item):
        self._total += weight
        self._cum_weights.append(self._total)
        self._items.append(item)

    def next(self, rng=RNG):
        if not self._items:
            raise ValueError("RandomCollection vide")
        r = rng.uniform(0, self._total)
        idx = bisect.bisect_left(self._cum_weights, r)
        return self._items[min(idx, len(self._items) - 1)]


class BoundedDeque(deque):
    """File bornée à maxlen (équiv. BoundedArrayDeque, 100 par défaut)."""
    def __init__(self, maxlen=100):
        super().__init__(maxlen=maxlen)


# ---------------------------------------------------------------------------
# 2. CHARGEMENT DES PARAMÈTRES (les 6 CSV MoMTSim + config fraude YAML)
# ---------------------------------------------------------------------------

@dataclass
class ClientActionProfile:
    action: str
    profile_id: int
    min_tx: int
    max_tx: int
    mean_amount: float
    std_amount: float
    weight: float


@dataclass
class StepActionProfile:
    step: int
    action: str
    count: int
    total_sum: float
    avg: float
    std: float


class Parameters:
    """Charge les 6 CSV + le YAML de config fraude."""

    def __init__(self, param_dir: str, fraud_config_path: str,
                 seed: int = 1000, n_clients=2000, n_merchants=300,
                 n_banks=20, transfer_limit=5_000_000):
        self.seed = seed
        self.n_clients = n_clients
        self.n_merchants = n_merchants
        self.n_banks = n_banks
        self.transfer_limit = transfer_limit

        self.transaction_types = pd.read_csv(f"{param_dir}/transactionsTypes.csv")["type"].tolist()

        self.client_profiles_df = pd.read_csv(f"{param_dir}/clientsProfiles.csv")
        self.action_profile_pool: dict[str, RandomCollection] = {}
        for action, grp in self.client_profiles_df.groupby("action"):
            rc = RandomCollection()
            for _, row in grp.iterrows():
                cap = ClientActionProfile(
                    action=action, profile_id=row["profile_id"],
                    min_tx=row["min_tx_per_month"], max_tx=row["max_tx_per_month"],
                    mean_amount=row["mean_amount"], std_amount=row["std_amount"],
                    weight=row["weight"])
                rc.add(row["weight"], cap)
            self.action_profile_pool[action] = rc

        agg = pd.read_csv(f"{param_dir}/aggregatedTransactions.csv")
        self.steps_profiles: list[dict[str, StepActionProfile]] = [dict() for _ in range(720)]
        for _, row in agg.iterrows():
            sap = StepActionProfile(row["step"], row["action"], row["count"],
                                     row["sum"], row["avg"], row["std"])
            self.steps_profiles[int(row["step"])][row["action"]] = sap
        self.total_target_count = agg.groupby("step")["count"].sum().to_dict()

        self.initial_balances_df = pd.read_csv(f"{param_dir}/initialBalancesDistribution.csv")
        self._balance_rc = RandomCollection()
        for _, row in self.initial_balances_df.iterrows():
            self._balance_rc.add(row["proportion"], (row["range_min"], row["range_max"]))

        self.overdraft_df = pd.read_csv(f"{param_dir}/overdraftLimits.csv")

        self.max_occ_df = pd.read_csv(f"{param_dir}/maxOccurrencesPerClient.csv")
        self.max_occurrences = dict(zip(self.max_occ_df["action"], self.max_occ_df["max_occurrences"]))

        with open(fraud_config_path, "r", encoding="utf-8") as f:
            self.fraud_config = json.load(f)

    def pick_initial_balance(self, rng=RNG) -> float:
        lo, hi = self._balance_rc.next(rng)
        return float(rng.uniform(lo, hi))

    def get_overdraft_limit(self, mean_amount: float) -> float:
        for _, row in self.overdraft_df.iterrows():
            lo = -np.inf if str(row["mean_amount_min"]) == "-inf" else float(row["mean_amount_min"])
            hi = np.inf if str(row["mean_amount_max"]) == "inf" else float(row["mean_amount_max"])
            if lo <= mean_amount < hi:
                return float(row["overdraft_limit"])
        return 0.0

    def pick_client_profile(self, action: str, rng=RNG) -> Optional[ClientActionProfile]:
        pool = self.action_profile_pool.get(action)
        return pool.next(rng) if pool else None


# ---------------------------------------------------------------------------
# 3. TRANSACTION
# ---------------------------------------------------------------------------

@dataclass
class Transaction:
    step: int
    action: str
    amount: float
    name_orig: str
    old_balance_orig: float
    new_balance_orig: float
    name_dest: str
    old_balance_dest: float
    new_balance_dest: float
    is_fraud: bool = False
    is_flagged_fraud: bool = False
    is_unauthorized_overdraft: bool = False
    is_successful: bool = True
    fraud_scenario: Optional[str] = None  # ATO / REFUND / FAKE_CRED / SPLIT_DEP / SMURFING


# ---------------------------------------------------------------------------
# 4. AGENTS
# ---------------------------------------------------------------------------

class ActorType(Enum):
    BANK = auto()
    CLIENT = auto()
    MERCHANT = auto()
    MULE = auto()
    ATO_FRAUDSTER = auto()
    REFUND_FRAUDSTER = auto()
    FAKE_CRED_FRAUDSTER = auto()
    SPLIT_DEP_FRAUDSTER = auto()
    SMURF_EMITTER = auto()
    SMURF_RECEIVER = auto()


class SuperActor:
    def __init__(self, actor_id: str, actor_type: ActorType, balance: float = 0.0,
                 overdraft_limit: float = 0.0, mean_amount: float = 0.0):
        self.id = actor_id
        self.type = actor_type
        self.balance = balance
        self.overdraft_limit = overdraft_limit
        self.mean_amount = mean_amount
        self.history = BoundedDeque(maxlen=100)  # derniers contacts
        self.tx_count_lifetime: dict[str, int] = {}
        self.high_risk = False

    def can_withdraw(self, amount: float) -> bool:
        return (self.balance - amount) >= self.overdraft_limit

    def deposit(self, amount: float):
        self.balance += amount

    def withdraw(self, amount: float) -> bool:
        if self.can_withdraw(amount):
            self.balance -= amount
            return True
        return False

    def remember(self, other_id: str):
        if other_id not in self.history:
            self.history.append(other_id)


class Merchant(SuperActor):
    def __init__(self, actor_id, high_risk=False):
        super().__init__(actor_id, ActorType.MERCHANT)
        self.high_risk = high_risk
        self.refund_acceptance_proba = float(RNG.uniform(0.3, 0.95))


class Bank(SuperActor):
    def __init__(self, actor_id):
        super().__init__(actor_id, ActorType.BANK)


class Client(SuperActor):
    def __init__(self, actor_id, params: Parameters, rng=RNG):
        balance0 = params.pick_initial_balance(rng)
        # profil par action
        self.profiles: dict[str, ClientActionProfile] = {}
        target_counts = {}
        for action in params.transaction_types:
            prof = params.pick_client_profile(action, rng)
            if prof:
                self.profiles[action] = prof
                target_counts[action] = rng.integers(prof.min_tx, prof.max_tx + 1)
        mean_amount_global = np.mean([p.mean_amount for p in self.profiles.values()]) if self.profiles else 0.0
        overdraft = params.get_overdraft_limit(mean_amount_global)
        super().__init__(actor_id, ActorType.CLIENT, balance=balance0,
                          overdraft_limit=overdraft, mean_amount=mean_amount_global)
        self.target_total_count = sum(target_counts.values())
        self.client_weight = 0.0  # renseigné par MoMTSimState (part du total)
        # état "solde d'équilibre" pour spring model
        self.equilibrium = max(1.0, 40 * mean_amount_global)
        self.in_prob = 0.5
        self.out_prob = 0.5
        self.tx_history_amounts = deque(maxlen=10)  # pour Flag anomalie (µ+2σ glissant)
        self.recent_transfers = deque(maxlen=50)     # pour la règle de fraude native

    # --- 3.3 Spring Model ---
    def spring_probabilities(self):
        k = 1.0 / self.equilibrium
        spring_force = k * (self.equilibrium - self.balance)
        correction_strength = 1.0
        new_prob_in = 0.5 * (1 + correction_strength * spring_force + (self.in_prob - self.out_prob))
        new_prob_in = float(np.clip(new_prob_in, 0.0, 1.0))
        return new_prob_in, 1.0 - new_prob_in

    # --- 3.1 nombre de transactions à ce step (binomiale) ---
    def draw_tx_count(self, step_target_count: int, rng=RNG) -> int:
        if self.target_total_count <= 0 or step_target_count <= 0:
            return 0
        n = int(rng.binomial(step_target_count, min(1.0, self.client_weight)))
        return n

    # --- 3.2 montant (loi normale, profil client + profil step) ---
    def draw_amount(self, action: str, step_profile: Optional[StepActionProfile], rng=RNG) -> float:
        prof = self.profiles.get(action)
        if prof is None:
            return 0.0
        if step_profile is not None:
            mu = (prof.mean_amount + step_profile.avg) / 2
            sigma = np.sqrt((prof.std_amount**2 + step_profile.std**2)) / 2
        else:
            mu, sigma = prof.mean_amount, prof.std_amount
        amount = rng.normal(mu, max(sigma, 1e-6))
        while amount <= 0:
            amount = rng.normal(mu, max(sigma, 1e-6))
        return float(amount)

    # --- 3.4 Stickiness ---
    def pick_counterparty(self, candidate_pool: list[str], rng=RNG) -> str:
        if self.history and rng.uniform() < 0.90:
            return rng.choice(list(self.history))
        target = rng.choice(candidate_pool)
        if target not in self.history and rng.uniform() < 0.90:
            self.remember(target)
        return target

    # --- 3.6 règle de détection native ---
    def check_native_fraud_flag(self, amount: float, transfer_limit: float) -> bool:
        self.recent_transfers.append(amount)
        if len(self.recent_transfers) >= 3:
            balance_max = max(self.recent_transfers) if self.recent_transfers else self.balance
            if (balance_max - self.balance - amount) > transfer_limit * 2.5:
                return True
        return False

    def update_amount_history(self, amount: float):
        self.tx_history_amounts.append(amount)

    def anomaly_flag(self, amount: float) -> bool:
        if len(self.tx_history_amounts) < 2:
            return False
        mu = np.mean(self.tx_history_amounts)
        sigma = np.std(self.tx_history_amounts)
        return amount > (mu + 2 * sigma)


class Mule(Client):
    """Compte fantoche : step() n'agit pas seul, activé par un fraudeur."""
    def __init__(self, actor_id, params: Parameters, rng=RNG):
        super().__init__(actor_id, params, rng)
        self.type = ActorType.MULE
        self.controller_id: Optional[str] = None

    def fraudulent_cash_out(self, amount: float) -> bool:
        return self.withdraw(amount)


# ---------------------------------------------------------------------------
# 5. AGENTS FRAUDEURS — formules EXACTES de la section 3.2 du mémoire
# ---------------------------------------------------------------------------

class BaseFraudster:
    scenario_name = "BASE"

    def __init__(self, cfg: dict, params: Parameters):
        self.cfg = cfg
        self.params = params

    def make_tx(self, step, action, amount, orig: SuperActor, dest: SuperActor,
                fraud=True, flagged=False) -> Transaction:
        old_o, old_d = orig.balance, dest.balance
        success = orig.withdraw(amount)
        if success:
            dest.deposit(amount)
        return Transaction(
            step=step, action=action, amount=amount,
            name_orig=orig.id, old_balance_orig=old_o, new_balance_orig=orig.balance,
            name_dest=dest.id, old_balance_dest=old_d, new_balance_dest=dest.balance,
            is_fraud=fraud, is_flagged_fraud=flagged, is_successful=success,
            fraud_scenario=self.scenario_name)


class ATOFraudster(BaseFraudster):
    """3.2.1 — Account Takeover : retraits massifs haute vélocité."""
    scenario_name = "ATO"

    def __init__(self, cfg, params):
        super().__init__(cfg["ato"], params)

    def execute(self, step: int, victim: Client, mule_pool: list[Mule], rng=RNG) -> list[Transaction]:
        c = self.cfg
        if victim.balance < c["B_min"]:
            return []
        B0 = victim.balance
        n = int(rng.integers(c["n_min"], c["n_max"] + 1))
        mules = list(rng.choice(mule_pool, size=min(n, len(mule_pool)), replace=False))
        # fragments non vus auparavant (nouveauté du destinataire garantie par choix pool mules)
        remaining = B0
        txs = []
        t = step
        for mule in mules:
            if remaining <= 0:
                break
            frac = rng.uniform(c["frag_min"], c["frag_max"])
            amount = min(remaining, frac * B0)
            if amount <= 0:
                continue
            dt = rng.exponential(1.0 / c["lambda_ato"])  # en fraction de step (heures)
            tx = self.make_tx(t, "TRANSFER", amount, victim, mule, fraud=True)
            txs.append(tx)
            remaining -= amount
            t = step  # toutes les tx restent horodatées dans la fenêtre <10 min = même step
        return txs


class RefundFraudster(BaseFraudster):
    """3.2.2 — Refund Fraud : boucles paiement/remboursement."""
    scenario_name = "REFUND"

    def __init__(self, cfg, params):
        super().__init__(cfg["refund"], params)
        self.vuln_registry: dict[str, list[str]] = {}  # fraudster_id -> [merchant_ids]
        self.cycle_counts: dict[str, int] = {}

    def select_vulnerable_merchants(self, fraudster_id: str, merchants: list[Merchant]):
        thresh = self.cfg["p_refund_threshold"]
        vuln = [m.id for m in merchants if m.refund_acceptance_proba > thresh]
        self.vuln_registry[fraudster_id] = vuln

    def execute(self, step: int, fraudster_id: str, orig: SuperActor,
                merchants: dict[str, Merchant], rng=RNG) -> list[Transaction]:
        c = self.cfg
        vuln = self.vuln_registry.get(fraudster_id, [])
        if not vuln:
            return []
        m_id = rng.choice(vuln)
        merchant = merchants[m_id]
        amount = float(rng.normal(3325, 800))  # ancré sur moyenne paiement marchand du mémoire
        amount = max(amount, 100)
        pay_tx = self.make_tx(step, "PAYMENT", amount, orig, merchant, fraud=True)
        refund_tx = self.make_tx(step, "REFUND", amount, merchant, orig, fraud=True)
        self.cycle_counts[fraudster_id] = self.cycle_counts.get(fraudster_id, 0) + 1
        if self.cycle_counts[fraudster_id] >= c["k_max"]:
            vuln.remove(m_id)
            self.cycle_counts[fraudster_id] = 0
        return [pay_tx, refund_tx]


class FakeCredentialsFraudster(BaseFraudster):
    """3.2.3 — Fake Credentials : dormance puis exfiltration."""
    scenario_name = "FAKE_CRED"

    def __init__(self, cfg, params):
        super().__init__(cfg["fake_credentials"], params)

    def execute_dormant_tx(self, step: int, actor: Client, merchant: Merchant, rng=RNG) -> Transaction:
        c = self.cfg
        amount = float(rng.uniform(500, c["m_leg_max"]))
        return self.make_tx(step, "PAYMENT", amount, actor, merchant, fraud=False)

    def execute_exfiltration(self, step: int, actor: Client, dest: SuperActor,
                              plafond: float, rng=RNG) -> Transaction:
        c = self.cfg
        amount = float(rng.uniform(c["m_exp_ratio_min"] * plafond, plafond))
        return self.make_tx(step, "TRANSFER", amount, actor, dest, fraud=True, flagged=True)


class SplitDepositFraudster(BaseFraudster):
    """3.2.4 — Split Deposit : arbitrage de commission par agent."""
    scenario_name = "SPLIT_DEP"

    def __init__(self, cfg, params):
        super().__init__(cfg["split_deposit"], params)
        self.tariff_grid: list[tuple[float, float]] = [
            (float(t["threshold"]), float(t["commission"])) for t in self.cfg["tariff_grid"]
        ]

    def _commission(self, amount: float) -> float:
        c = 0.0
        for threshold, comm in self.tariff_grid:
            if amount >= threshold:
                c = comm
        return c

    def optimal_fragmentation(self, total: float, rng=RNG) -> list[float]:
        best_k, best_gain = 1, self._commission(total)
        for k in range(2, 6):
            frag = total / k
            gain_k = k * self._commission(frag)
            if gain_k > best_gain:
                best_gain, best_k = gain_k, k
        eps = rng.uniform(0, self.cfg["epsilon_max"])
        base = total / best_k
        fragments = [base + rng.uniform(-eps, eps) for _ in range(best_k - 1)]
        fragments.append(total - sum(fragments))
        return [max(f, 1.0) for f in fragments]

    def execute(self, step: int, client: Client, agent: SuperActor,
                total_deposit: float, rng=RNG) -> list[Transaction]:
        fragments = self.optimal_fragmentation(total_deposit, rng)
        return [self.make_tx(step, "CASH_IN", f, agent, client, fraud=True) for f in fragments]


class SmurfingNetwork(BaseFraudster):
    """3.2.5 — Smurfing : réseau f1 -> mules -> f2, critères de Zhdanova et al."""
    scenario_name = "SMURFING"

    def __init__(self, cfg, params, emitter: SuperActor, receiver: SuperActor,
                 mules: list[Mule], n_conscious_ratio=0.6):
        super().__init__(cfg["smurfing"], params)
        self.emitter = emitter
        self.receiver = receiver
        self.mules = mules
        n_conscious = int(len(mules) * n_conscious_ratio)
        self.conscious_mules = set(m.id for m in mules[:n_conscious])

    def run_laundering_operation(self, step: int, total_X: float, rng=RNG) -> list[Transaction]:
        c = self.cfg
        s_seuil = c["S_seuil"]
        k = int(rng.integers(2, len(self.mules) + 1))
        chosen = list(rng.choice(self.mules, size=min(k, len(self.mules)), replace=False))
        fractions = rng.uniform(0.70 * s_seuil, 0.99 * s_seuil, size=len(chosen))
        fractions = fractions / fractions.sum() * min(total_X, len(chosen) * 0.99 * s_seuil)

        txs = []
        for mule, x_i in zip(chosen, fractions):
            tx_in = self.make_tx(step, "TRANSFER", float(x_i), self.emitter, mule, fraud=True)
            txs.append(tx_in)
            delta_i = rng.uniform(c["delta_min"], c["delta_max"])
            amount_out = float(x_i) * (1 - delta_i)
            tx_out = self.make_tx(step, "TRANSFER", amount_out, mule, self.receiver, fraud=True)
            txs.append(tx_out)
        return txs