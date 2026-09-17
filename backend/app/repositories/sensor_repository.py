from abc import ABC, abstractmethod


class SensorRepository(ABC):
    """Интерфейс источника данных датчиков."""

    @abstractmethod
    def get_all(self) -> list[dict]:
        """Возвращает все доступные датчики."""
        pass
