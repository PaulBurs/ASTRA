from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_sensor_repository
from app.repositories.sensor_repository import SensorRepository
from app.schemas.sensor import SensorResponse
from app.services.sensor_service import SensorService


router = APIRouter()


@router.get("", response_model=list[SensorResponse])
def get_sensors(
    repository: SensorRepository = Depends(get_sensor_repository),
):
    service = SensorService(repository)

    return service.get_sensors()


@router.get("/{sensor_id}", response_model=SensorResponse)
def get_sensor(
    sensor_id: int,
    repository: SensorRepository = Depends(get_sensor_repository),
):
    service = SensorService(repository)

    sensor = service.get_sensor(sensor_id)

    if sensor is None:
        raise HTTPException(
            status_code=404,
            detail="Sensor not found",
        )

    return sensor
