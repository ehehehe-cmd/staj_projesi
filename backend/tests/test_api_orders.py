"""``api/routers/orders.py`` testleri — TASARIM.md §4, §12.7. ``api_client``
fixture'ı sayesinde HTTP katmanı da ``db_session`` ile AYNI savepoint
transaction'ında çalışır (bkz. conftest.py) — gerçek DB'ye hiçbir kalıcı
yazım YAPILMAZ.
"""

from __future__ import annotations

import random

from app.core.constraints import RollingConstraints
from app.data_generation.generator import DEFAULT_CONFIG_PATH, generate_batch, load_synthetic_config
from app.db import crud


def _constraints(**overrides) -> RollingConstraints:
    base = dict(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    base.update(overrides)
    return RollingConstraints(**base)


def _seed(db_session, *, seed: int, batches: int = 1) -> None:
    config = load_synthetic_config(DEFAULT_CONFIG_PATH)
    rng = random.Random(seed)
    for _ in range(batches):
        batch = generate_batch(config, _constraints(), rng)
        crud.insert_generated_batch(db_session, batch)
    db_session.flush()


class TestListOrders:
    def test_empty_pool_returns_empty_list(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        r = api_client.get("/api/orders")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_seeded_orders_with_expected_shape(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=1, batches=1)
        r = api_client.get("/api/orders", params={"limit": 1000})
        assert r.status_code == 200
        body = r.json()
        assert len(body) > 0
        row = body[0]
        for key in ("id", "order_class", "status", "width_mm", "thickness_mm", "steel_grade"):
            assert key in row

    def test_filters_by_order_class_and_status(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=2, batches=2)
        r = api_client.get("/api/orders", params={"order_class": "transition", "status": "pending", "limit": 1000})
        assert r.status_code == 200
        body = r.json()
        assert body
        assert all(row["order_class"] == "transition" and row["status"] == "pending" for row in body)

    def test_limit_is_respected(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=3, batches=3)
        r = api_client.get("/api/orders", params={"limit": 5})
        assert r.status_code == 200
        assert len(r.json()) == 5


class TestListGroups:
    def test_returns_available_groups(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        _seed(db_session, seed=4, batches=2)
        r = api_client.get("/api/orders/groups", params={"status": "available"})
        assert r.status_code == 200
        body = r.json()
        assert body
        assert all(row["status"] == "available" for row in body)
        assert all(row["group_size"] > 0 for row in body)


class TestGenerateOrders:
    def test_generate_inserts_orders_and_emits_event(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        r = api_client.post("/api/orders/generate", json={"seed": 42, "batches": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["inserted_orders"] > 0
        assert body["inserted_groups"] >= 1

        listed = api_client.get("/api/orders", params={"limit": 1000}).json()
        assert len(listed) == body["inserted_orders"]

    def test_generate_with_clear_pending_reports_cleared_counts(self, api_client, db_session):
        crud.clear_pending_pool(db_session)
        api_client.post("/api/orders/generate", json={"seed": 5, "batches": 1})
        r2 = api_client.post("/api/orders/generate", json={"seed": 6, "batches": 1, "clear_pending": True})
        assert r2.status_code == 200
        assert r2.json()["cleared_orders"] > 0

    def test_batches_out_of_range_is_rejected(self, api_client, db_session):
        r = api_client.post("/api/orders/generate", json={"batches": 0})
        assert r.status_code == 422
        r2 = api_client.post("/api/orders/generate", json={"batches": 1000})
        assert r2.status_code == 422
