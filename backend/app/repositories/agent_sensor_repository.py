import os

import httpx

from app.repositories.sensor_repository import (
    SensorRepository,
)


class AgentSensorRepository(
    SensorRepository
):
    """
    Sensor repository backed by ASTRA Source Agent.

    Backend does not access source CSV files directly.
    """

    def __init__(
        self,
        agent_url: str | None = None,
    ):
        self.agent_url = (
            agent_url
            or os.getenv(
                "SOURCE_AGENT_URL",
                "http://host.docker.internal:9100",
            )
        ).rstrip("/")

    def get_all(self) -> list[dict]:
        try:
            response = httpx.get(
                f"{self.agent_url}/data/sensors",
                timeout=120.0,
            )
        except httpx.RequestError as error:
            raise RuntimeError(
                "Source Agent is unavailable"
            ) from error

        if response.is_error:
            raise RuntimeError(
                "Source Agent returned "
                f"HTTP {response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        if not isinstance(data, list):
            raise RuntimeError(
                "Source Agent returned invalid "
                "sensor list"
            )

        return data

    def get_by_id(
        self,
        sensor_id: int,
    ) -> dict | None:
        try:
            response = httpx.get(
                (
                    f"{self.agent_url}"
                    f"/data/sensors/{sensor_id}"
                ),
                timeout=120.0,
            )
        except httpx.RequestError as error:
            raise RuntimeError(
                "Source Agent is unavailable"
            ) from error

        if response.status_code == 404:
            return None

        if response.is_error:
            raise RuntimeError(
                "Source Agent returned "
                f"HTTP {response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        if not isinstance(data, dict):
            raise RuntimeError(
                "Source Agent returned invalid "
                "sensor object"
            )

        return data
