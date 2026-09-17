from app.ml.service import MLService


class DummyMLService(MLService):
    """Тестовая ML-заглушка. Настоящей модели здесь нет."""

    def health(self) -> bool:
        return True

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "dummy-v1",
            "message": "Dummy model training completed successfully",
        }

    def predict(self, sensor_id: int) -> dict:
        return {
            "sensor_id": sensor_id,
            "probability": 0.42,
            "horizon_hours": 24,
            "model_version": "dummy-v1",
        }
