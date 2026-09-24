from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (
    get_ml_data_repository,
    get_ml_service,
    get_sensor_repository,
)
from app.ml.service import MLService
from app.repositories.ml_data_repository import MLDataRepository
from app.repositories.sensor_repository import SensorRepository
from app.schemas.ml import (
    MLHealthResponse,
    MLPredictionResponse,
    MLTrainResponse,
)
from app.services.prediction_service import (
    PredictionService,
    SensorDataNotFoundError,
    SensorNotFoundError,
)


router = APIRouter()


@router.get("/health", response_model=MLHealthResponse)
def ml_health(
    ml_service: MLService = Depends(get_ml_service),
):
    return {
        "status": (
            "available"
            if ml_service.health()
            else "unavailable"
        )
    }


@router.post("/train", response_model=MLTrainResponse)
def train_model(
    ml_service: MLService = Depends(get_ml_service),
):
    return ml_service.train()


@router.get(
    "/predict/{sensor_id}",
    response_model=MLPredictionResponse,
)
def predict(
    sensor_id: int,
    ml_service: MLService = Depends(
        get_ml_service
    ),
    sensor_repository: SensorRepository = Depends(
        get_sensor_repository
    ),
    ml_data_repository: MLDataRepository = Depends(
        get_ml_data_repository
    ),
):
    service = PredictionService(
        sensor_repository=sensor_repository,
        ml_data_repository=ml_data_repository,
        ml_service=ml_service,
    )

    try:
        return service.predict(sensor_id)

    except SensorNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found",
        )

    except SensorDataNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Sensor data not found",
        )

