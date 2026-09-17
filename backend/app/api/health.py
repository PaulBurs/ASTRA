from fastapi import APIRouter, Depends

from app.core.dependencies import get_ml_service
from app.db.database import check_database_connection
from app.ml.service import MLService
from app.schemas.health import HealthResponse


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    ml_service: MLService = Depends(get_ml_service),
):
    database_connected = check_database_connection()
    ml_available = ml_service.health()

    system_ok = database_connected and ml_available

    return {
        "status": "ok" if system_ok else "error",
        "application": "ASTRA",
        "database": "connected" if database_connected else "disconnected",
        "ml": "available" if ml_available else "unavailable",
    }
