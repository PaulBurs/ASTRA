from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_dashboard():
    response = client.get("/api/dashboard")

    assert response.status_code == 200

    data = response.json()

    assert data["system"]["application"] == "ASTRA"

    assert data["summary"]["total_sensors"] == 3
    assert data["summary"]["ok"] == 1
    assert data["summary"]["warning"] == 1
    assert data["summary"]["critical"] == 1
    assert data["summary"]["max_risk"] == 0.91

    assert len(data["sensors"]) == 3


def test_dashboard_sensor_structure():
    response = client.get("/api/dashboard")

    assert response.status_code == 200

    sensor = response.json()["sensors"][0]

    assert "id" in sensor
    assert "name" in sensor
    assert "type" in sensor
    assert "value" in sensor
    assert "status" in sensor
    assert "risk" in sensor
