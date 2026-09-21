from app.db.database import check_database_connection
from app.ml.service import MLService


class HealthService:
    """Собирает состояние основных компонентов ASTRA."""

    def __init__(self, ml_service: MLService):
        self.ml_service = ml_service

    def get_health(self) -> dict:
        database_connected = check_database_connection()
        ml_available = self.ml_service.health()

        system_ok = database_connected and ml_available

        return {
            "status": "ok" if system_ok else "error",
            "application": "ASTRA",
            "database": (
                "connected"
                if database_connected
                else "disconnected"
            ),
            "ml": (
                "available"
                if ml_available
                else "unavailable"
            ),
        }
