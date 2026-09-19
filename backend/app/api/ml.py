from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import (
    get_ml_service,
    get_sensor_repository,
)
from app.ml.service import MLService
from app.repositories.sensor_repository import SensorRepository
from app.schemas.ml import (
    MLHealthResponse,
    MLPredictionResponse,
    MLTrainResponse,
)
from app.services.prediction_service import (
    PredictionService,
    SensorNotFoundError,
)


router = APIRouter()


@router.get("/health", response_model=MLHealthResponse)
def ml_health(
    ml_service: MLService = Depends(get_ml_service),
):
    return {
        "status": "available" if ml_service.health() else "unavailable"
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
    ml_service: MLService = Depends(get_ml_service),
    sensor_repository: SensorRepository = Depends(
        get_sensor_repository
    ),
):
    service = PredictionService(
        sensor_repository=sensor_repository,
        ml_service=ml_service,
    )

    try:
        return service.predict(sensor_id)

    except SensorNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found",
        )
    
    
def test_ml_prediction_for_unknown_sensor():
    response = client.get("/api/ml/predict/999999")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Sensor not found"
    }
