from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_get_sensors():
    response = client.get("/api/sensors")

    assert response.status_code == 200

    sensors = response.json()

    assert isinstance(sensors, list)
    assert len(sensors) > 0


def test_sensor_structure():
    response = client.get("/api/sensors")

    sensor = response.json()[0]

    assert "id" in sensor
    assert "name" in sensor
    assert "type" in sensor
    assert "value" in sensor
    assert "status" in sensor
    assert "risk" in sensor
    
def test_sensor_risk_range():
    response = client.get("/api/sensors")

    sensors = response.json()

    for sensor in sensors:
        assert 0.0 <= sensor["risk"] <= 1.0
