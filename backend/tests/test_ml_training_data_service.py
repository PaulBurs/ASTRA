from datetime import datetime

import pytest

from app.repositories.dummy_sensor_catalog_repository import (
    DummySensorCatalogRepository,
)
from app.repositories.dummy_training_data_repository import (
    DummyTrainingDataRepository,
)
from app.services.ml_training_data_service import (
    MLTrainingDataService,
    TrainingSensorsNotFoundError,
)


def create_service() -> MLTrainingDataService:
    return MLTrainingDataService(
        sensor_catalog_repository=(
            DummySensorCatalogRepository()
        ),
        training_data_repository=(
            DummyTrainingDataRepository()
        ),
    )


def test_training_service_finds_gas_sensors():
    service = create_service()

    sensor_ids = service.get_sensor_ids(
        engineering_system="Газовая охрана",
        sensor_type="Газовый датчик",
    )

    assert sensor_ids == [
        900001,
        900002,
    ]


def test_training_service_rejects_unknown_type():
    service = create_service()

    with pytest.raises(
        TrainingSensorsNotFoundError
    ):
        service.get_sensor_ids(
            engineering_system="Несуществующая система",
            sensor_type="Несуществующий датчик",
        )


def test_training_service_streams_gas_events():
    service = create_service()

    batches = list(
        service.iter_training_events(
            engineering_system="Газовая охрана",
            sensor_type="Газовый датчик",
            start=datetime(
                2026,
                3,
                5,
                0,
                0,
            ),
            end=datetime(
                2026,
                3,
                6,
                0,
                0,
            ),
            batch_size=2,
        )
    )

    assert len(batches) == 2

    events = [
        event
        for batch in batches
        for event in batch
    ]

    assert len(events) == 3

    assert all(
        event["sensor_id"] == 900001
        for event in events
    )

    assert (
        events[-1]["text_value"]
        == "Обнаружен газ"
    )
