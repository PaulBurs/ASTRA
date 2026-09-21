from app.repositories.sensor_catalog_repository import (
    SensorCatalogRepository,
)


class DummySensorCatalogRepository(
    SensorCatalogRepository
):
    """Тестовый каталог каналов."""

    def __init__(self):
        self.sensors = [
            {
                "sensor_id": 900001,
                "engineering_system": "Газовая охрана",
                "sensor_type": "Газовый датчик",
                "sensor_name": (
                    "Тестовый газовый датчик 1"
                ),
                "object_id": 1001,
            },
            {
                "sensor_id": 900002,
                "engineering_system": "Газовая охрана",
                "sensor_type": "Газовый датчик",
                "sensor_name": (
                    "Тестовый газовый датчик 2"
                ),
                "object_id": 1001,
            },
            {
                "sensor_id": 900003,
                "engineering_system": (
                    "Охранная подсистема"
                ),
                "sensor_type": "Датчик движения",
                "sensor_name": (
                    "Тестовый датчик движения"
                ),
                "object_id": 1002,
            },
        ]

    def get_sensor_ids(
        self,
        engineering_system: str | None = None,
        sensor_type: str | None = None,
    ) -> list[int]:
        result = self.sensors

        if engineering_system is not None:
            result = [
                sensor
                for sensor in result
                if sensor["engineering_system"]
                == engineering_system
            ]

        if sensor_type is not None:
            result = [
                sensor
                for sensor in result
                if sensor["sensor_type"]
                == sensor_type
            ]

        return [
            sensor["sensor_id"]
            for sensor in result
        ]

    def get_sensor_metadata(
        self,
        sensor_id: int,
    ) -> dict | None:
        for sensor in self.sensors:
            if sensor["sensor_id"] == sensor_id:
                return sensor

        return None
