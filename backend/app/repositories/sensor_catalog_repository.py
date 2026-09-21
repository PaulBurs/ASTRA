from abc import ABC, abstractmethod


class SensorCatalogRepository(ABC):
    """Каталог каналов/датчиков для аналитики и ML."""

    @abstractmethod
    def get_sensor_ids(
        self,
        engineering_system: str | None = None,
        sensor_type: str | None = None,
    ) -> list[int]:
        """Возвращает ID каналов по заданным фильтрам."""
        pass

    @abstractmethod
    def get_sensor_metadata(
        self,
        sensor_id: int,
    ) -> dict | None:
        """Возвращает метаданные канала."""
        pass
