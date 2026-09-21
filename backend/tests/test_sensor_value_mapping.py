from datetime import datetime
from decimal import Decimal

from app.repositories.postgres_sensor_repository import (
    PostgresSensorRepository,
)


def base_row() -> dict:
    return {
        "sensor_id": 1,
        "sensor_name": "Test sensor",
        "sensor_type": "Test type",
        "engineering_system": "Test system",
        "object_id": 100,
        "numeric_value": None,
        "datetime_value": None,
        "text_value": None,
        "value_type": None,
        "occurred_at": datetime(
            2026,
            3,
            5,
            12,
            0,
        ),
    }


def test_numeric_sensor_value():
    row = base_row()

    row["value_type"] = "numeric"
    row["numeric_value"] = Decimal("0.03")

    sensor = (
        PostgresSensorRepository._to_sensor(row)
    )

    assert sensor["value_type"] == "numeric"
    assert sensor["value"] == 0.03


def test_binary_sensor_value():
    row = base_row()

    row["value_type"] = "binary"
    row["numeric_value"] = Decimal("1")

    sensor = (
        PostgresSensorRepository._to_sensor(row)
    )

    assert sensor["value_type"] == "binary"
    assert sensor["value"] == 1.0


def test_text_sensor_value():
    row = base_row()

    row["value_type"] = "text"
    row["text_value"] = "Обнаружен газ"

    sensor = (
        PostgresSensorRepository._to_sensor(row)
    )

    assert sensor["value_type"] == "text"
    assert sensor["value"] == "Обнаружен газ"


def test_datetime_sensor_value():
    row = base_row()

    row["value_type"] = "datetime"
    row["datetime_value"] = datetime(
        2026,
        3,
        5,
        9,
        11,
        35,
    )

    sensor = (
        PostgresSensorRepository._to_sensor(row)
    )

    assert sensor["value_type"] == "datetime"
    assert (
        sensor["value"]
        == "2026-03-05T09:11:35"
    )


def test_sensor_without_events():
    row = base_row()

    sensor = (
        PostgresSensorRepository._to_sensor(row)
    )

    assert sensor["value_type"] is None
    assert sensor["value"] is None
