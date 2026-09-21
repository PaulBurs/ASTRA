from datetime import datetime

from ml.src.contracts import (
    MLEvent,
    PredictionInput,
)
from ml.src.runtime import predict


def main() -> None:
    prediction_input = PredictionInput(
        sensor_id=900001,
        sensor_type="Газовый датчик",
        engineering_system="Газовая охрана",
        sensor_name="Example gas sensor",
        object_id=1001,
        as_of=datetime(
            2026,
            3,
            5,
            12,
            0,
        ),
        lookback_hours=24,
        events=[
            MLEvent(
                event_id=1,
                occurred_at=datetime(
                    2026,
                    3,
                    5,
                    11,
                    40,
                ),
                value_type="numeric",
                numeric_value=0.01,
            ),
            MLEvent(
                event_id=2,
                occurred_at=datetime(
                    2026,
                    3,
                    5,
                    11,
                    50,
                ),
                value_type="numeric",
                numeric_value=0.03,
            ),
        ],
    )

    result = predict(
        prediction_input
    )

    print(
        result.model_dump()
    )


if __name__ == "__main__":
    main()
