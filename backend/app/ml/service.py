from abc import ABC, abstractmethod
from uuid import UUID

from app.ml.contracts import MLPredictionInput


class MLService(ABC):
    """Интерфейс подключения ML-модели к ASTRA."""

    @abstractmethod
    def health(self) -> bool:
        """Проверяет доступность ML-компонента."""
        pass

    @abstractmethod
    def train(self) -> dict:
        """Запускает обучение модели."""
        pass

    @abstractmethod
    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        """Строит прогноз по подготовленной истории датчика."""
        pass

    def predict_dataset(self, dataset_id: UUID, sensor_id: int) -> dict:
        """Строит прогноз из подготовленного набора данных."""
        raise NotImplementedError
