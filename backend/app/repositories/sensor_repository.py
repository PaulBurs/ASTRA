from abc import ABC, abstractmethod


class SensorRepository(ABC):
    """Интерфейс источника данных датчиков."""

    @abstractmethod
    def get_all(self) -> list[dict]:
        """Возвращает все доступные датчики."""
        pass

    @abstractmethod
    def get_by_id(self, sensor_id: int) -> dict | None:
        """Возвращает датчик по ID или None."""
        pass
