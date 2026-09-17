from abc import ABC, abstractmethod


class MLService(ABC):
    """Интерфейс для подключения ML-модели к ASTRA."""

    @abstractmethod
    def health(self) -> bool:
        """Проверяет доступность ML-компонента."""
        pass

    @abstractmethod
    def train(self) -> dict:
        """Запускает обучение модели."""
        pass
