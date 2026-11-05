from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict[str, str]:
    """Liveness: the process is up. Does not touch dependencies."""
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)) -> JSONResponse:
    """Readiness: verifies real database connectivity."""
    try:
        database = db.execute(text("SELECT current_database()")).scalar_one()
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "unreachable"},
        )
    return JSONResponse(content={"status": "ok", "database": database})
