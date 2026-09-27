from uuid import UUID

from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from ml.src.datasets import validate_dataset

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


@app.post("/datasets/{dataset_id}/validate")
def validate_prepared_dataset(dataset_id: UUID):
    try:
        return validate_dataset(dataset_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(503, "Не удалось прочитать подготовленные данные") from error


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
