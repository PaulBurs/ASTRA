from app.ml.contracts import MLPredictionInput
from app.ml.service import MLService
from uuid import UUID


class DummyMLService(MLService):
    """Тестовая ML-заглушка."""

    def health(self) -> bool:
        return True

    def train(self) -> dict:
        return {
            "status": "completed",
            "model_version": "dummy-v1",
            "message": (
                "Dummy model training completed successfully"
            ),
        }

    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        return {
            "sensor_id": prediction_input.sensor_id,
            "probability": 0.42,
            "horizon_hours": 24,
            "model_version": "dummy-v1",
        }

    def predict_dataset(self, dataset_id: UUID, sensor_id: int) -> dict:
        return {
            "sensor_id": sensor_id,
            "probability": 0.42,
            "horizon_hours": 24,
            "model_version": "dummy-v1",
        }
