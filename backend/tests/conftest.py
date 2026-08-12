import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import engine


@pytest.fixture()
def db_session():
    """Her testten sonra rollback yapan bir transaction icinde calisir.

    join_transaction_mode="create_savepoint": session.rollback() (bir IntegrityError
    testinden sonra ORM state'ini sifirlamak icin kullanilir) bir SAVEPOINT'e geri
    doner, disaridaki connection-level transaction'i bozmaz -- boylece fixture teardown'daki
    transaction.rollback() her zaman gecerli bir transaction uzerinde calisir.

    Faz 1 testleri gercek (dockerized) Postgres'e karsi calisir -- TASARIM.md domain
    katmani icin ongorulen 'DB'den bagimsiz training' ilkesi (SS1.2) sadece training/env.py
    icin gecerlidir; DB semasinin dogru kuruldugunu dogrulamak zaten gercek bir DB gerektirir.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="session")
def _api_test_client():
    """FastAPI ``TestClient``, tüm test oturumu için TEK sefer açılır (lifespan
    gerçek bir asyncpg LISTEN bağlantısı açtığı için her testte yeniden
    açmak gereksiz maliyetlidir) — TASARIM.md §12.7. Kullanıcıya doğrudan
    verilmez, ``api_client`` fixture'ı bunun üzerine per-test DB izolasyonu
    ekler."""
    import app.main as main_module

    with TestClient(main_module.app) as client:
        yield client


@pytest.fixture()
def api_client(_api_test_client, db_session):
    """``api_client``: HTTP router testleri için — ``get_db`` bağımlılığı
    BU TESTİN KENDİ ``db_session``'ına (savepoint/rollback izolasyonlu)
    yönlendirilir, böylece bir route'un yaptığı gerçek DB yazımları testin
    dışına SIZMAZ (gerçek geliştirme veritabanı kirlenmez — Faz 5'in
    ``test_live_engine_e2e.py``sında elle keşfedilen sızıntı riskinin
    router seviyesinde tekrarlanmaması için, bkz. TASARIM.md §12.6.4)."""
    import app.main as main_module
    from app.api.deps import get_db

    def _override_get_db():
        yield db_session

    main_module.app.dependency_overrides[get_db] = _override_get_db
    try:
        yield _api_test_client
    finally:
        main_module.app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True, scope="session")
def _verify_schema_applied():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version is not None, (
            "alembic_version bos -- once `alembic upgrade head` calistirilmali "
            "(bkz. backend/ dizininde: .venv/bin/alembic upgrade head)"
        )
