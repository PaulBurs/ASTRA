from uuid import UUID

import httpx
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
    dataset_id: UUID | None = None,
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
    if dataset_id is not None:
        if sensor_repository.get_by_id(sensor_id) is None:
            raise HTTPException(status_code=404, detail="Sensor not found")
        try:
            return ml_service.predict_dataset(dataset_id, sensor_id)
        except httpx.HTTPStatusError as error:
            detail = "Не удалось получить прогноз ML"
            try:
                detail = error.response.json().get("detail", detail)
            except ValueError:
                pass
            raise HTTPException(error.response.status_code, detail) from error
        except (httpx.HTTPError, NotImplementedError) as error:
            raise HTTPException(503, "ML-сервис недоступен") from error

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
