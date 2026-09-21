from ml.src.contracts import (
    HealthOutput,
    PredictionInput,
    PredictionOutput,
    TrainOutput,
)


MODEL_VERSION = "dummy-v1"


def health() -> HealthOutput:
    return HealthOutput(
        available=True,
        model_version=MODEL_VERSION,
    )


def train() -> TrainOutput:
    # Здесь ML-разработчик позже подключит
    # настоящий training pipeline.
    return TrainOutput(
        status="completed",
        model_version=MODEL_VERSION,
        message="Dummy training completed",
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
        model_version=MODEL_VERSION,
    )
