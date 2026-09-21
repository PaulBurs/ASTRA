from app.ml.service import MLService
from app.repositories.sensor_repository import SensorRepository
from app.services.health_service import HealthService


class DashboardService:
    """Формирует данные для панели диспетчера."""

    def __init__(
        self,
        sensor_repository: SensorRepository,
        ml_service: MLService,
    ):
        self.sensor_repository = sensor_repository
        self.ml_service = ml_service

    def get_dashboard(self) -> dict:
        sensors = self.sensor_repository.get_all()

        summary = {
            "total_sensors": len(sensors),
            "ok": sum(
                sensor["status"] == "OK"
                for sensor in sensors
            ),
            "warning": sum(
                sensor["status"] == "WARNING"
                for sensor in sensors
            ),
            "critical": sum(
                sensor["status"] == "CRITICAL"
                for sensor in sensors
            ),
            "max_risk": max(
                (
                    sensor["risk"]
                    for sensor in sensors
                ),
                default=0.0,
            ),
        }

        health_service = HealthService(self.ml_service)

        return {
            "system": health_service.get_health(),
            "summary": summary,
            "sensors": sensors,
        }
