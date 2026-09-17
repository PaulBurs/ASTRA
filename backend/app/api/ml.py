from fastapi import APIRouter, Depends

from app.core.dependencies import get_ml_service
from app.ml.service import MLService
from app.schemas.ml import (
    MLHealthResponse,
    MLPredictionResponse,
    MLTrainResponse,
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
):
    return ml_service.predict(sensor_id)
