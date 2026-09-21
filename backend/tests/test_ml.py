from fastapi.testclient import TestClient

from app.core.dependencies import get_ml_service
from app.ml.service import MLService
from main import app
from app.ml.contracts import MLPredictionInput


client = TestClient(app)


class UnavailableMLService(MLService):
    def health(self) -> bool:
        return False

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "test-v1",
            "message": "Test model",
        }
        
    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        return {
            "sensor_id": prediction_input.sensor_id,
            "probability": 0.0,
            "horizon_hours": 24,
            "model_version": "test-v1",
        }


def test_ml_health():
    response = client.get("/api/ml/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "available"
    }


def test_train_model():
    response = client.post("/api/ml/train")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "completed"
    assert data["model_version"] == "dummy-v1"


def test_ml_health_when_service_unavailable():
    def override_ml_service():
        return UnavailableMLService()

    app.dependency_overrides[get_ml_service] = override_ml_service

    try:
        response = client.get("/api/ml/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "unavailable"
        }

    finally:
        app.dependency_overrides.clear()


def test_system_health_when_ml_unavailable():
    def override_ml_service():
        return UnavailableMLService()

    app.dependency_overrides[get_ml_service] = override_ml_service

    try:
        response = client.get("/api/health")

        assert response.status_code == 200

        data = response.json()

        assert data["status"] == "error"
        assert data["ml"] == "unavailable"

    finally:
        app.dependency_overrides.clear()
        
        
def test_ml_prediction():
    response = client.get("/api/ml/predict/56682")

    assert response.status_code == 200

    data = response.json()

    assert data["sensor_id"] == 56682
    assert 0.0 <= data["probability"] <= 1.0
    assert data["horizon_hours"] >= 24
    assert data["model_version"] == "dummy-v1"
