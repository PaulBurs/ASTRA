from app.repositories.dummy_sensor_catalog_repository import (
    DummySensorCatalogRepository,
)


def test_catalog_filters_gas_sensors():
    repository = DummySensorCatalogRepository()

    sensor_ids = repository.get_sensor_ids(
        engineering_system="Газовая охрана",
        sensor_type="Газовый датчик",
    )

    assert sensor_ids == [
        900001,
        900002,
    ]


def test_catalog_filters_motion_sensors():
    repository = DummySensorCatalogRepository()

    sensor_ids = repository.get_sensor_ids(
        engineering_system="Охранная подсистема",
        sensor_type="Датчик движения",
    )

    assert sensor_ids == [900003]


def test_catalog_returns_metadata():
    repository = DummySensorCatalogRepository()

    sensor = repository.get_sensor_metadata(
        900001
    )

    assert sensor is not None
    assert sensor["sensor_id"] == 900001
    assert sensor["sensor_type"] == "Газовый датчик"


def test_catalog_unknown_sensor():
    repository = DummySensorCatalogRepository()

    assert (
        repository.get_sensor_metadata(999999)
        is None
    )
