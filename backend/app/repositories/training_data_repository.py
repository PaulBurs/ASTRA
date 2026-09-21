from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import datetime


class TrainingDataRepository(ABC):
    """Источник исторических данных для обучения ML."""

    @abstractmethod
    def iter_events(
        self,
        sensor_ids: list[int],
        start: datetime,
        end: datetime,
        batch_size: int = 50_000,
    ) -> Iterator[list[dict]]:
        """
        Возвращает исторические события порциями.

        Весь набор данных никогда не загружается
        в память одновременно.
        """
        pass
