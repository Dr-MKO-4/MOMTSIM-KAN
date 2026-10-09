"""
live/server.py  Canal REST du flux live MoMTSim.

App FastAPI distincte de backend/api.py (aucune route ajoutée à celle-ci),
servie sur son propre port. Elle expose le tampon du producteur.
"""

from __future__ import annotations

from fastapi import FastAPI, Query

from .producer import LiveProducer


def build_app(producer: LiveProducer) -> FastAPI:
    app = FastAPI(title="MoMTSim live stream")

    @app.get("/live/transactions")
    def transactions(since_id: int = Query(0, ge=0),
                     limit: int = Query(20000, ge=1, le=50000)):
        """Transactions brutes postérieures à since_id.

        `run_id` change à chaque démarrage du producteur : un consommateur qui le
        voit changer doit repartir de since_id=0. Les lignes rejouées avant le
        direct portent `warmup: true`."""
        rows, last_id = producer.ring.since(since_id, limit=limit)
        return {"transactions": rows, "last_id": last_id, "run_id": producer.run_id,
                "step": producer.step, "warming": producer.warming,
                "total_published": producer.total_published}

    @app.get("/live/health")
    def health():
        return {"status": "ok", "run_id": producer.run_id, "step": producer.step,
                "warming": producer.warming, "total_published": producer.total_published,
                "last_id": producer.ring.last_id, "population": producer.params_cfg}

    return app
