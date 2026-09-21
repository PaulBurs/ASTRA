from abc import ABC, abstractmethod

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
