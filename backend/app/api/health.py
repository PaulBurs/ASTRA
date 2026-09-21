from fastapi import APIRouter, Depends

from app.core.dependencies import get_ml_service
from app.ml.service import MLService
from app.schemas.health import HealthResponse
from app.services.health_service import HealthService


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(
    ml_service: MLService = Depends(get_ml_service),
):
    service = HealthService(ml_service)

    return service.get_health()
