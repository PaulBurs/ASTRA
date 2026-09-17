from app.repositories.dummy_sensor_repository import DummySensorRepository


def test_dummy_sensor_repository_returns_sensors():
    repository = DummySensorRepository()

    sensors = repository.get_all()

    assert len(sensors) == 3
    assert sensors[0]["id"] == 56682


def test_dummy_sensor_repository_risk_range():
    repository = DummySensorRepository()

    sensors = repository.get_all()

    for sensor in sensors:
        assert 0.0 <= sensor["risk"] <= 1.0
