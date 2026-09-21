"""
ASTRA ML integration example.

Этот файл показывает ML-разработчику, как получать
исторические данные через backend-контракт без прямого SQL.

Сейчас используются Dummy repositories.
После подключения реального PostgreSQL интерфейс
MLTrainingDataService останется тем же.
"""

from datetime import datetime
from pathlib import Path
import sys


# backend/ пока не установлен как отдельный Python package,
# поэтому для демонстрационного скрипта добавляем его в sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_DIR))


from app.repositories.dummy_sensor_catalog_repository import (  # noqa: E402
    DummySensorCatalogRepository,
)
from app.repositories.dummy_training_data_repository import (  # noqa: E402
    DummyTrainingDataRepository,
)
from app.services.ml_training_data_service import (  # noqa: E402
    MLTrainingDataService,
)


def main() -> None:
    # ML-разработчик работает с сервисом,
    # а не с SQL и структурой PostgreSQL напрямую.
    service = MLTrainingDataService(
        sensor_catalog_repository=(
            DummySensorCatalogRepository()
        ),
        training_data_repository=(
            DummyTrainingDataRepository()
        ),
    )

    engineering_system = "Газовая охрана"
    sensor_type = "Газовый датчик"

    start = datetime(
        2026,
        3,
        5,
        0,
        0,
    )

    end = datetime(
        2026,
        3,
        6,
        0,
        0,
    )

    print("ASTRA ML example")
    print("=" * 50)

    sensor_ids = service.get_sensor_ids(
        engineering_system=engineering_system,
        sensor_type=sensor_type,
    )

    print(
        f"Engineering system: {engineering_system}"
    )
    print(
        f"Sensor type: {sensor_type}"
    )
    print(
        f"Found sensors: {sensor_ids}"
    )

    print()
    print("Reading training events...")
    print()

    total_events = 0

    for batch_number, batch in enumerate(
        service.iter_training_events(
            engineering_system=engineering_system,
            sensor_type=sensor_type,
            start=start,
            end=end,
            batch_size=2,
        ),
        start=1,
    ):
        print(
            f"Batch #{batch_number}: "
            f"{len(batch)} events"
        )

        for event in batch:
            print(
                "  "
                f"{event['occurred_at']} | "
                f"sensor={event['sensor_id']} | "
                f"type={event['value_type']} | "
                f"numeric={event['numeric_value']} | "
                f"text={event['text_value']}"
            )

        total_events += len(batch)

    print()
    print(
        f"Total events received: {total_events}"
    )

    print()
    print(
        "Next step: pass each batch to "
        "ml/src preprocessing and feature engineering."
    )


if __name__ == "__main__":
    main()
