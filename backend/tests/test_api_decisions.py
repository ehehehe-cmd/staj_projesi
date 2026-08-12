"""``api/routers/decisions.py`` testleri — TASARIM.md §4, §8, §12.7.

Not: ``decided_at`` sütununun varsayılanı ``server_default=func.now()`` —
Postgres'te ``now()`` bir transaction İÇİNDE SABİTTİR (``clock_timestamp()``
DEĞİL); ``db_session`` fixture'ı tüm testi TEK bir dış transaction'da
çalıştırdığı için (bkz. conftest.py) aynı testte art arda oluşturulan satırlar
AYNI ``decided_at``'i alır. Zaman-sıralı/``since`` testleri bu yüzden
``decided_at``'i AÇIKÇA (artan) değerlere set eder — gerçek canlı sistemde
(ayrı transaction'lar) bu doğal olarak farklılaşır."""

from __future__ import annotations

import datetime as dt

from app.core.constraints import RollingConstraints
from app.db import crud


def _constraints(**overrides) -> RollingConstraints:
    base = dict(
        delta_w=75.0, delta_t=0.75, delta_h=7.0, delta_theta=45.0,
        kz=3_000_000.0, lr=3, m_min=60, m_max=100, soft_transition_limit=3,
    )
    base.update(overrides)
    return RollingConstraints(**base)


def _make_manager_decision(db_session, course, *, step_index: int, selected_group_id=None, reward=0.0, decided_at=None):
    row = crud.record_manager_decision(
        db_session, course_id=course.id, step_index=step_index, vector=[1.0],
        eligible_group_ids=[], selected_group_id=selected_group_id, reward=reward, model_version_id=None,
    )
    if decided_at is not None:
        row.decided_at = decided_at
        db_session.flush()
    return row


class TestListDecisions:
    def test_empty_returns_empty_page(self, api_client, db_session):
        r = api_client.get("/api/decisions")
        assert r.status_code == 200
        body = r.json()
        assert body["items"] == []
        assert body["next_since"] is None

    def test_combines_manager_and_worker_decisions_sorted_by_time(self, api_client, db_session):
        base = dt.datetime.now(dt.timezone.utc)
        course = crud.start_new_course(db_session, constraints=_constraints())
        m1 = _make_manager_decision(db_session, course, step_index=1, decided_at=base)
        w1 = crud.record_worker_decision(
            db_session, manager_decision_id=m1.id, course_id=course.id, step_index=0,
            vector=[0.1], eligible_transition_ids=[], selected_transition_order_id=None,
            success=True, reward=5.0, model_version_id=None,
        )
        w1.decided_at = base + dt.timedelta(seconds=1)
        m2 = _make_manager_decision(db_session, course, step_index=2, decided_at=base + dt.timedelta(seconds=2))
        db_session.flush()

        r = api_client.get("/api/decisions")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 3
        kinds = [item["kind"] for item in body["items"]]
        assert kinds == ["manager", "worker", "manager"]
        decided_ats = [item["decided_at"] for item in body["items"]]
        assert decided_ats == sorted(decided_ats)
        assert m2 is not None

    def test_filters_by_kind_and_course_id(self, api_client, db_session):
        course_a = crud.start_new_course(db_session, constraints=_constraints())
        course_b = crud.start_new_course(db_session, constraints=_constraints())
        _make_manager_decision(db_session, course_a, step_index=1)
        _make_manager_decision(db_session, course_b, step_index=1)

        r = api_client.get("/api/decisions", params={"kind": "manager", "course_id": course_a.id})
        body = r.json()
        assert all(item["course_id"] == course_a.id for item in body["items"])
        assert all(item["kind"] == "manager" for item in body["items"])

    def test_since_filters_out_older_decisions(self, api_client, db_session):
        base = dt.datetime.now(dt.timezone.utc)
        course = crud.start_new_course(db_session, constraints=_constraints())
        _make_manager_decision(db_session, course, step_index=1, decided_at=base)
        first_page = api_client.get("/api/decisions").json()
        cursor = first_page["next_since"]
        assert cursor is not None

        _make_manager_decision(db_session, course, step_index=2, decided_at=base + dt.timedelta(seconds=1))
        r2 = api_client.get("/api/decisions", params={"since": cursor})
        assert r2.status_code == 200
        body2 = r2.json()
        assert len(body2["items"]) == 1
        assert body2["items"][0]["step_index"] == 2

    def test_invalid_kind_is_rejected(self, api_client, db_session):
        r = api_client.get("/api/decisions", params={"kind": "bogus"})
        assert r.status_code == 422
