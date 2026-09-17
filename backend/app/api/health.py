from fastapi import APIRouter

from app.db.database import check_database_connection
from app.ml.dummy import DummyMLService


router = APIRouter()

ml_service = DummyMLService()


@router.get("/health")
def health():
    database_connected = check_database_connection()
    ml_available = ml_service.health()

    system_ok = database_connected and ml_available

    return {
        "status": "ok" if system_ok else "error",
        "application": "ASTRA",
        "database": "connected" if database_connected else "disconnected",
        "ml": "available" if ml_available else "unavailable",
    }
