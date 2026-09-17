from fastapi import APIRouter

from app.ml.dummy import DummyMLService


router = APIRouter()

ml_service = DummyMLService()


@router.get("/health")
def ml_health():
    return {
        "status": "available" if ml_service.health() else "unavailable"
    }


@router.post("/train")
def train_model():
    return ml_service.train()
