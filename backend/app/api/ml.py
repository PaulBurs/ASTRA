from fastapi import APIRouter

from app.ml.dummy import DummyMLService
from app.schemas.ml import MLHealthResponse, MLTrainResponse


router = APIRouter()

ml_service = DummyMLService()


@router.get("/health", response_model=MLHealthResponse)
def ml_health():
    return {
        "status": "available" if ml_service.health() else "unavailable"
    }


@router.post("/train", response_model=MLTrainResponse)
def train_model():
    return ml_service.train()
