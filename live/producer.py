"""
live/producer.py  Producteur de transactions brutes MoMTSim.

Génère le flux pas à pas (un step de simulation par tick) et publie chaque
transaction BRUTE (aucune ingénierie de caractéristiques : c'est le
consommateur qui la fait) sur deux canaux simultanés :
  - un topic Kafka (mm.transactions.momtsim) ;
  - un tampon mémoire compact lu par le serveur REST (live/server.py).

Avant le direct, le producteur rejoue un ÉCHAUFFEMENT (historique simulé, marqué
`warmup`) : sans lui, les variables à fenêtre longue (30 et 90 jours) seraient
calculées sur un historique vide et les comptes, très peu actifs, mettraient des
milliers de steps à atteindre les 10 transactions nécessaires au scoring.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from momtsim_torch import (  # noqa: E402
    TorchParameters, TorchMoMTSimEngine, TorchFraudInjector,
)

PARAM_DIR = str(_ROOT / "config" / "paramFiles")
FRAUD_CONFIG_PATH = str(_ROOT / "config" / "fraudScenariosConfig.json")
CALIBRATED_PROBAS_PATH = _ROOT / "config" / "calibrated_probas.json"

KAFKA_TOPIC = "mm.transactions.momtsim"
KAFKA_BOOTSTRAP = os.environ.get("MOMTSIM_KAFKA_BOOTSTRAP", "localhost:9092")

# Régime « clairsemé » proche de celui de l'entraînement de MKAN (500 000 clients,
# ~0,006 transaction par client et par step). Mesuré sur 1440 steps :
#   20 000 clients, volume x0,05, 130 mules -> 22,6 % de fraude par transaction,
#   0,010 tx/client/step, 0,9 % de mules parmi les comptes scorés, 18 ms/step.
# (le taux dépend de n_mules et du volume, pas du nombre de clients : 5 000 et
#  10 000 clients donnent le même taux)
DEFAULT_CLIENTS = 20000
DEFAULT_VOLUME_SCALE = 0.05
DEFAULT_MULES = 130
DEFAULT_WARMUP_STEPS = 1500
MERCHANT_RATIO = 0.024
N_BANKS = 8
MAX_SLOTS = 3
# Rapport mules / volume validé ; on prévient quand on s'en éloigne trop.
ANCHOR_MULES_PER_VOLUME = DEFAULT_MULES / DEFAULT_VOLUME_SCALE

RING_CAPACITY = 1_200_000     # > 2 200 steps : couvre la plus longue fenêtre de variables (90 jours)

COLUMNS = ("step", "time_s", "action", "amount", "nameOrig", "nameDest",
           "oldBalanceOrig", "newBalanceOrig", "oldBalanceDest", "newBalanceDest",
           "isSuccessful", "isFraud", "isFlaggedFraud", "fraudScenario", "warmup")


def _load_fraud_probas() -> dict | None:
    if CALIBRATED_PROBAS_PATH.exists():
        with open(CALIBRATED_PROBAS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


class RingBuffer:
    """Tampon circulaire thread-safe, stocké en tuples (compact : ~300 octets par
    transaction). Les identifiants sont contigus, donc `since` est en O(limit)."""

    def __init__(self, capacity: int = RING_CAPACITY):
        self._capacity = capacity
        self._items: list[tuple] = []
        self._first_id = 1                  # identifiant de _items[0]
        self._lock = threading.Lock()

    def extend(self, rows: list[tuple]) -> None:
        if not rows:
            return
        with self._lock:
            self._items.extend(rows)
            over = len(self._items) - int(self._capacity * 1.1)
            if over > 0:
                drop = len(self._items) - self._capacity
                del self._items[:drop]
                self._first_id += drop

    def since(self, since_id: int, limit: int = 20000) -> tuple[list[dict], int]:
        with self._lock:
            start = max(since_id + 1, self._first_id) - self._first_id
            chunk = self._items[start:start + limit]
            last_id = (self._first_id + start + len(chunk) - 1) if chunk else since_id
        return [dict(zip(COLUMNS, t)) for t in chunk], last_id

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._first_id + len(self._items) - 1


class LiveProducer:
    """Moteur MoMTSim avancé pas à pas, publiant en continu."""

    def __init__(self, n_clients: int = DEFAULT_CLIENTS, tick_seconds: float = 0.5,
                 seed: int = 1000, kafka_enabled: bool = True,
                 volume_scale: float = DEFAULT_VOLUME_SCALE, n_mules: int = DEFAULT_MULES,
                 warmup_steps: int = DEFAULT_WARMUP_STEPS):
        self.run_id = uuid.uuid4().hex[:12]
        self.tick_seconds = tick_seconds
        self.warmup_steps = warmup_steps
        self.warming = warmup_steps > 0
        self.ring = RingBuffer()
        self.step = 0
        self.total_published = 0
        self._stop = threading.Event()
        self._kafka_producer = None
        self.params_cfg = {
            "n_clients": n_clients,
            "n_merchants": max(5, round(n_clients * MERCHANT_RATIO)),
            "n_banks": N_BANKS, "n_mules": n_mules, "max_slots": MAX_SLOTS,
            "volume_scale": volume_scale, "warmup_steps": warmup_steps,
        }
        cfg = self.params_cfg

        ratio = n_mules / max(volume_scale, 1e-9)
        if not (0.75 * ANCHOR_MULES_PER_VOLUME <= ratio <= 1.25 * ANCHOR_MULES_PER_VOLUME):
            print(f"[WARN] rapport mules/volume = {ratio:.0f} (validé : "
                  f"{ANCHOR_MULES_PER_VOLUME:.0f} +/- 25 %). Le taux de fraude cible 20-26 % "
                  f"n'est plus garanti : plus de mules ou moins de volume = plus de fraude.",
                  flush=True)
        density = 3000 * volume_scale / max(n_clients, 1)
        print(f"[INIT] {n_clients} clients, {cfg['n_merchants']} marchands, {N_BANKS} banques, "
              f"{n_mules} mules, volume x{volume_scale} (~{density:.3f} tx/client/step), "
              f"echauffement {warmup_steps} steps", flush=True)

        params = TorchParameters(PARAM_DIR, FRAUD_CONFIG_PATH, n_clients=n_clients,
                                 seed=seed, volume_scale=volume_scale)
        self._params = params
        self.engine = TorchMoMTSimEngine(
            params, n_clients=n_clients, n_merchants=cfg["n_merchants"],
            n_banks=N_BANKS, n_mules=n_mules, max_slots_per_step=MAX_SLOTS, seed=seed)
        self.injector = TorchFraudInjector(self.engine, params,
                                           fraud_probas=_load_fraud_probas(), seed=seed,
                                           volume_follow=True)
        if kafka_enabled:
            self._init_kafka()

    def _init_kafka(self) -> None:
        try:
            from kafka import KafkaProducer
        except ImportError:
            print("[WARN] kafka-python absent  publication Kafka désactivée "
                  "(le canal REST reste disponible).", flush=True)
            return
        try:
            self._kafka_producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                linger_ms=50,
            )
            print(f"[OK] Kafka connecte : {KAFKA_BOOTSTRAP} / topic {KAFKA_TOPIC}", flush=True)
        except Exception as exc:
            print(f"[WARN] Kafka indisponible ({exc})  publication Kafka "
                  f"désactivée, le canal REST reste disponible.", flush=True)

    def _actor_id(self, idx: int) -> str:
        """Indice d'acteur interne -> identifiant stable façon PaySim."""
        e = self.engine
        if idx >= e.MULE_OFFSET:
            return f"U{idx - e.MULE_OFFSET}"
        if idx >= e.BANK_OFFSET:
            return f"B{idx - e.BANK_OFFSET}"
        if idx >= e.MERCHANT_OFFSET:
            return f"M{idx - e.MERCHANT_OFFSET}"
        return f"C{idx}"

    def _advance(self, warm: bool) -> list[tuple]:
        """Un step de simulation -> transactions brutes du step, en tuples."""
        self.engine.step_once(self.step)
        self.injector.inject(self.step)
        self.engine.end_of_step(self.step, self._params)
        df = self.engine.flush_log()
        self.step += 1
        if df.empty:
            return []
        cols = {
            "step": df["step"].astype(int).tolist(),
            "time_s": df["time_s"].astype(float).tolist(),
            "action": df["action"].tolist(),
            "amount": df["amount"].astype(float).tolist(),
            "nameOrig": [self._actor_id(int(i)) for i in df["nameOrig"]],
            "nameDest": [self._actor_id(int(i)) for i in df["nameDest"]],
            "oldBalanceOrig": df["oldBalanceOrig"].astype(float).tolist(),
            "newBalanceOrig": df["newBalanceOrig"].astype(float).tolist(),
            "oldBalanceDest": df["oldBalanceDest"].astype(float).tolist(),
            "newBalanceDest": df["newBalanceDest"].astype(float).tolist(),
            "isSuccessful": df["isSuccessful"].astype(bool).tolist(),
            "isFraud": df["isFraud"].astype(bool).tolist(),
            "isFlaggedFraud": df["isFlaggedFraud"].astype(bool).tolist(),
            "fraudScenario": df["fraudScenario"].tolist(),
            "warmup": [warm] * len(df),
        }
        return list(zip(*(cols[c] for c in COLUMNS)))

    def _publish(self, rows: list[tuple]) -> None:
        if not rows:
            return
        self.ring.extend(rows)
        self.total_published += len(rows)
        if self._kafka_producer is not None:
            for t in rows:
                self._kafka_producer.send(KAFKA_TOPIC, {**dict(zip(COLUMNS, t)),
                                                        "run_id": self.run_id})

    def run(self) -> None:
        if self.warmup_steps:
            t0 = time.perf_counter()
            for i in range(self.warmup_steps):
                if self._stop.is_set():
                    return
                self._publish(self._advance(warm=True))
                if (i + 1) % 250 == 0:
                    print(f"[ECHAUFFEMENT] {i + 1}/{self.warmup_steps} steps, "
                          f"{self.total_published} transactions", flush=True)
            if self._kafka_producer is not None:
                self._kafka_producer.flush()
            self.warming = False
            print(f"[OK] echauffement termine en {time.perf_counter() - t0:.0f}s : "
                  f"passage au direct", flush=True)
        self.warming = False
        while not self._stop.is_set():
            t0 = time.perf_counter()
            self._publish(self._advance(warm=False))
            if self.step % 20 == 0:
                print(f"[STEP {self.step}] {self.total_published} transactions "
                      f"publiees", flush=True)
            elapsed = time.perf_counter() - t0
            self._stop.wait(max(0.0, self.tick_seconds - elapsed))

    def stop(self) -> None:
        self._stop.set()
