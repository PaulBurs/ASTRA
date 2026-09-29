import httpx
from uuid import UUID

from app.ml.contracts import MLPredictionInput
from app.ml.service import MLService


class HTTPMLService(MLService):
    """HTTP-клиент автономного ASTRA ML Service."""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url}/health",
                timeout=self.timeout_seconds,
            )

            response.raise_for_status()

            return bool(
                response.json().get(
                    "available",
                    False,
                )
            )

        except httpx.HTTPError:
            return False

    def train(self) -> dict:
        response = httpx.post(
            f"{self.base_url}/train",
            timeout=300.0,
        )

        response.raise_for_status()

        return response.json()

    def predict(
        self,
        prediction_input: MLPredictionInput,
    ) -> dict:
        response = httpx.post(
            f"{self.base_url}/predict",
            json=prediction_input.model_dump(
                mode="json"
            ),
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()

        return response.json()

    def predict_dataset(self, dataset_id: UUID, sensor_id: int) -> dict:
        response = httpx.post(
            f"{self.base_url}/datasets/{dataset_id}/predict/{sensor_id}",
            timeout=max(self.timeout_seconds, 120.0),
        )
        response.raise_for_status()
        return response.json()

    def predict_dataset_batch(self, dataset_id: UUID, sensor_ids: list[int]) -> dict:
        response = httpx.post(
            f"{self.base_url}/datasets/{dataset_id}/predict-batch",
            json={"sensor_ids": sensor_ids},
            timeout=max(self.timeout_seconds, 300.0),
        )
        response.raise_for_status()
        return response.json()
