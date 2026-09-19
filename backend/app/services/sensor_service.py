from app.repositories.sensor_repository import SensorRepository


class SensorService:
    """Бизнес-слой работы с датчиками."""

    def __init__(self, repository: SensorRepository):
        self.repository = repository

    def get_sensors(self) -> list[dict]:
        return self.repository.get_all()

    def get_sensor(self, sensor_id: int) -> dict | None:
        return self.repository.get_by_id(sensor_id)
