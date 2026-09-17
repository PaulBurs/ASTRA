from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_ml_training():
    response = client.post("/api/ml/train")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "completed"
    assert "model_version" in data
