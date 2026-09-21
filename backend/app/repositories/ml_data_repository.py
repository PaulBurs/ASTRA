from abc import ABC, abstractmethod
from datetime import datetime


class MLDataRepository(ABC):
    """Доступ к временным данным для online ML inference."""

    @abstractmethod
    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        """Возвращает время последнего события канала."""
        pass

    @abstractmethod
    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        """Возвращает события канала за заданный период."""
        pass
