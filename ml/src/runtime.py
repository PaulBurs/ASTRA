from ml.src.contracts import (
    HealthOutput,
    PredictionInput,
    PredictionOutput,
    TrainOutput,
)
from ml.src.inference import model_info


def health() -> HealthOutput:
    available, version = model_info()
    return HealthOutput(
        available=available,
        model_version=version,
    )


def train() -> TrainOutput:
    _, version = model_info()
    return TrainOutput(
        status="not_started",
        model_version=version,
        message="Обучение запускается отдельным конвейером",
    )


def predict(
    prediction_input: PredictionInput,
) -> PredictionOutput:
    # Здесь позже появятся:
    #
    # preprocessing
    # feature engineering
    # model.predict_proba(...)
    #
    # Backend менять не потребуется.

    probability = 0.42

    return PredictionOutput(
        sensor_id=prediction_input.sensor_id,
        probability=probability,
        horizon_hours=24,
        model_version="legacy-dummy-v1",
    )
