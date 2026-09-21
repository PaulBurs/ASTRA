from datetime import datetime

from app.repositories.dummy_training_data_repository import (
    DummyTrainingDataRepository,
)


def test_training_repository_returns_batches():
    repository = DummyTrainingDataRepository()

    batches = list(
        repository.iter_events(
            sensor_ids=[900001],
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
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1


def test_training_repository_event_structure():
    repository = DummyTrainingDataRepository()

    batches = list(
        repository.iter_events(
            sensor_ids=[900001],
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
        )
    )

    event = batches[0][0]

    assert event["sensor_id"] == 900001
    assert "occurred_at" in event
    assert "value_type" in event
    assert "numeric_value" in event
    assert "text_value" in event
