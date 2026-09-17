from app.ml.service import MLService


class DummyMLService(MLService):
    """Тестовая ML-заглушка. Настоящего обучения здесь нет."""

    def health(self) -> bool:
        return True

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "dummy-v1",
            "message": "Dummy model training completed successfully",
        }
