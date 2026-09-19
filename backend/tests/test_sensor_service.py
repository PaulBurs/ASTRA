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
        
    def get_by_id(self, sensor_id: int) -> dict | None:
        for sensor in self.get_all():
            if sensor["id"] == sensor_id:
                return sensor

        return None

def test_sensor_service_uses_repository():
    repository = TestSensorRepository()
    service = SensorService(repository)

    sensors = service.get_sensors()

    assert len(sensors) == 1
    assert sensors[0]["name"] == "TEST-SENSOR"
    
    
def test_sensor_service_get_sensor_by_id():
    repository = TestSensorRepository()
    service = SensorService(repository)

    sensor = service.get_sensor(1)

    assert sensor is not None
    assert sensor["id"] == 1
