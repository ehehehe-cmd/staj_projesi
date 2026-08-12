"""simulation/notifier.py gerçek Postgres LISTEN/NOTIFY uçtan uca testi.

Bu dosya ``db_session`` (savepoint/rollback) fixture'ını KULLANMAZ — Postgres
NOTIFY yalnızca göndereni transaction'ı COMMIT ettiğinde teslim edilir,
bu yüzden gerçek bir commit + testin kendi temizliği gerekir (bkz.
``_cleanup``).
"""

from __future__ import annotations

import asyncio

from app.db import crud
from app.db.base import SessionLocal
from app.db.models import LiveEvent
from app.simulation.notifier import LiveEventNotifier


def _cleanup(event_id: int) -> None:
    with SessionLocal() as session:
        row = session.get(LiveEvent, event_id)
        if row is not None:
            session.delete(row)
            session.commit()


def test_notifier_receives_and_resolves_a_committed_event():
    async def _run() -> None:
        async with LiveEventNotifier() as notifier:
            await asyncio.sleep(0.1)  # LISTEN'in Postgres tarafında devreye girmesi için ufak bir pay

            with SessionLocal() as session:
                row = crud.emit_event(session, event_type="order_generated", payload={"probe": True})
                session.commit()
                event_id = row.id

            try:
                received_id = await notifier.wait_for_event(timeout=5.0)
                assert received_id == event_id

                resolved = await notifier.fetch_event(received_id)
                assert resolved is not None
                assert resolved.event_type == "order_generated"
                assert resolved.payload == {"probe": True}
                assert resolved.course_id is None
            finally:
                _cleanup(event_id)

    asyncio.run(_run())


def test_wait_for_event_times_out_when_nothing_is_notified():
    async def _run() -> None:
        async with LiveEventNotifier() as notifier:
            result = await notifier.wait_for_event(timeout=0.3)
            assert result is None

    asyncio.run(_run())


def test_fetch_event_returns_none_for_unknown_id():
    async def _run() -> None:
        async with LiveEventNotifier() as notifier:
            resolved = await notifier.fetch_event(-1)
            assert resolved is None

    asyncio.run(_run())
