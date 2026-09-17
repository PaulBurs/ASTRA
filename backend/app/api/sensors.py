from fastapi import APIRouter

from app.repositories.dummy_sensor_repository import DummySensorRepository
from app.schemas.sensor import SensorResponse
from app.services.sensor_service import SensorService


router = APIRouter()

sensor_repository = DummySensorRepository()
sensor_service = SensorService(sensor_repository)


@router.get("", response_model=list[SensorResponse])
def get_sensors():
    return sensor_service.get_sensors()
