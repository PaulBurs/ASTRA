from app.repositories.sensor_repository import SensorRepository
from app.services.sensor_service import SensorService


class TestSensorRepository(SensorRepository):
    def get_all(self) -> list[dict]:
        return [
            {
                "id": 1,
                "name": "TEST-SENSOR",
                "type": "temperature",
                "value": 42.0,
                "status": "OK",
                "risk": 0.25,
            }
        ]


def test_sensor_service_uses_repository():
    repository = TestSensorRepository()
    service = SensorService(repository)

    sensors = service.get_sensors()

    assert len(sensors) == 1
    assert sensors[0]["name"] == "TEST-SENSOR"
