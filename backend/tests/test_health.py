from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app
from tests.conftest import TEST_DB_NAME

client = TestClient(app)


def test_live() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_uses_real_database() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": TEST_DB_NAME}


def test_ready_returns_503_when_database_down() -> None:
    class BrokenSession:
        def execute(self, *_args: object, **_kwargs: object) -> None:
            raise OperationalError("SELECT 1", {}, Exception("db down"))

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
