from fastapi import APIRouter, Depends

from app.core.dependencies import (
    get_ml_service,
    get_sensor_repository,
)
from app.ml.service import MLService
from app.repositories.sensor_repository import SensorRepository
from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService


router = APIRouter()


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    ml_service: MLService = Depends(get_ml_service),
    sensor_repository: SensorRepository = Depends(
        get_sensor_repository
    ),
):
    service = DashboardService(
        sensor_repository=sensor_repository,
        ml_service=ml_service,
    )

    return service.get_dashboard()
