import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["SETUP_TOKEN"] = "test-setup-token"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.config import settings  # noqa: E402
from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

settings.SETUP_TOKEN = "test-setup-token"


# 기본은 SQLite 메모리 DB. TEST_DATABASE_URL 을 주면 그 DB(예: Neon 의 테스트 전용 DB)에서 돌린다.
# 주의: 테스트마다 테이블을 지웠다 만든다 — 운영 DB 주소를 넣지 말 것.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def db():
    if TEST_DATABASE_URL:
        from app.config import _normalize_db_url
        engine = create_engine(_normalize_db_url(TEST_DATABASE_URL))
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        if TEST_DATABASE_URL:
            Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db):
    def _get_db():
        yield db
    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
