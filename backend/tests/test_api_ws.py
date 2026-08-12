"""``WS /ws/live`` uçtan uca testi — TASARIM.md §4, §8, §12.7.

``api_client`` (savepoint/rollback) fixture'ı burada KULLANILMAZ: NOTIFY
teslimi yalnızca göndereni transaction'ı COMMIT ettiğinde gerçekleşir
(bkz. Faz 5 ``test_notifier.py``'nin aynı gerekçesi). Bu dosya kendi
``TestClient``'ını (kendi lifespan'ı, kendi gerçek asyncpg LISTEN
bağlantısı) açar ve oluşturduğu tek satırı teardown'da siler.

``receive_json`` bir timeout parametresi almıyor (Starlette testclient) —
sonsuz asılma riskine karşı bir thread + ``future.result(timeout=...)``
ile sarmalanır.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.db import crud
from app.db.base import SessionLocal
from app.db.models import LiveEvent
import app.main as main_module


def _receive_json_with_timeout(ws, *, timeout: float = 10.0):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ws.receive_json)
        return future.result(timeout=timeout)


def test_ws_broadcasts_a_committed_live_event_to_connected_clients():
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/live") as ws:
            with SessionLocal() as session:
                row = crud.emit_event(session, event_type="order_generated", payload={"probe": "ws"})
                session.commit()
                event_id = row.id
            try:
                message = _receive_json_with_timeout(ws)
                assert message["id"] == event_id
                assert message["event_type"] == "order_generated"
                assert message["payload"] == {"probe": "ws"}
            finally:
                with SessionLocal() as cleanup:
                    obj = cleanup.get(LiveEvent, event_id)
                    if obj is not None:
                        cleanup.delete(obj)
                        cleanup.commit()


def test_ws_broadcasts_to_multiple_connected_clients():
    with TestClient(main_module.app) as client:
        with client.websocket_connect("/ws/live") as ws1, client.websocket_connect("/ws/live") as ws2:
            with SessionLocal() as session:
                row = crud.emit_event(session, event_type="order_generated", payload={"probe": "multi"})
                session.commit()
                event_id = row.id
            try:
                m1 = _receive_json_with_timeout(ws1)
                m2 = _receive_json_with_timeout(ws2)
                assert m1["id"] == event_id
                assert m2["id"] == event_id
            finally:
                with SessionLocal() as cleanup:
                    obj = cleanup.get(LiveEvent, event_id)
                    if obj is not None:
                        cleanup.delete(obj)
                        cleanup.commit()
