from fastapi import FastAPI

from ml.src.contracts import (
    HealthOutput,
    PredictionInput,
    PredictionOutput,
    TrainOutput,
)
from ml.src.runtime import (
    health,
    predict,
    train,
)


app = FastAPI(
    title="ASTRA ML Service",
    version="1.0.0",
)


@app.get(
    "/health",
    response_model=HealthOutput,
)
def get_health() -> HealthOutput:
    return health()


@app.post(
    "/train",
    response_model=TrainOutput,
)
def train_model() -> TrainOutput:
    return train()


@app.post(
    "/predict",
    response_model=PredictionOutput,
)
def predict_model(
    prediction_input: PredictionInput,
) -> PredictionOutput:
    return predict(prediction_input)
