import os
from datetime import datetime

import httpx

from app.repositories.ml_data_repository import (
    MLDataRepository,
)


class AgentMLDataRepository(
    MLDataRepository
):
    """
    ML history через ASTRA Source Agent.

    Backend не имеет прямого доступа
    к исходным CSV-файлам.
    """

    MAX_EVENTS = 5000

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

    def get_latest_event_time(
        self,
        sensor_id: int,
    ) -> datetime | None:
        try:
            response = httpx.get(
                (
                    f"{self.agent_url}"
                    f"/data/ml/{sensor_id}/latest"
                ),
                timeout=30.0,
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

        occurred_at = data.get(
            "occurred_at"
        )

        if occurred_at is None:
            return None

        return datetime.fromisoformat(
            occurred_at
        )

    def get_events(
        self,
        sensor_id: int,
        start: datetime,
        end: datetime,
        limit: int = 5000,
    ) -> list[dict]:
        if (
            limit <= 0
            or limit > self.MAX_EVENTS
        ):
            raise ValueError(
                "limit must be between "
                f"1 and {self.MAX_EVENTS}"
            )

        if start > end:
            raise ValueError(
                "start must not be later than end"
            )

        try:
            response = httpx.get(
                (
                    f"{self.agent_url}"
                    f"/data/ml/{sensor_id}/events"
                ),
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "limit": limit,
                },
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

        events = response.json()

        if not isinstance(
            events,
            list,
        ):
            raise RuntimeError(
                "Source Agent returned "
                "invalid ML event list"
            )

        result: list[dict] = []

        for event in events:
            occurred_at = event.get(
                "occurred_at"
            )

            datetime_value = event.get(
                "datetime_value"
            )

            result.append(
                {
                    **event,
                    "occurred_at": (
                        datetime.fromisoformat(
                            occurred_at
                        )
                        if occurred_at
                        else None
                    ),
                    "datetime_value": (
                        datetime.fromisoformat(
                            datetime_value
                        )
                        if datetime_value
                        else None
                    ),
                }
            )

        return result
