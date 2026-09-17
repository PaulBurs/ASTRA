from fastapi import APIRouter

from app.db.database import check_database_connection


router = APIRouter()


@router.get("/health")
def health():
    database_connected = check_database_connection()

    return {
        "status": "ok" if database_connected else "error",
        "application": "ASTRA",
        "database": "connected" if database_connected else "disconnected",
    }
