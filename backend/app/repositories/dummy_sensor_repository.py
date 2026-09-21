from app.repositories.sensor_repository import SensorRepository


class DummySensorRepository(SensorRepository):
    """Временное хранилище датчиков до подключения PostgreSQL."""

    def get_all(self) -> list[dict]:
        return [
            {
                "id": 56682,
                "name": "МК-1.1.1.1.1.1",
                "type": "temperature",
                "value": 25.0,
                "status": "OK",
                "risk": 0.12,
                "engineering_system": "Диспетчерский контроль",
				"object_id": 1001,
				"value_type": "numeric",
				"occurred_at": None,
            },
            {
                "id": 183582,
                "name": "МК-2.2.2.2.2.14",
                "type": "temperature",
                "value": 25.4,
                "status": "WARNING",
                "risk": 0.63,
                "engineering_system": "Диспетчерский контроль",
				"object_id": 1001,
				"value_type": "numeric",
				"occurred_at": None,
            },
            {
                "id": 215811,
                "name": "МК-6.7.8.2.2.189",
                "type": "temperature",
                "value": 33.5,
                "status": "CRITICAL",
                "risk": 0.91,
                "engineering_system": "Диспетчерский контроль",
				"object_id": 1001,
				"value_type": "numeric",
				"occurred_at": None,
            },
        ]

    def get_by_id(self, sensor_id: int) -> dict | None:
        for sensor in self.get_all():
            if sensor["id"] == sensor_id:
                return sensor

        return None
