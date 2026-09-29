from uuid import UUID
from contextlib import asynccontextmanager
from concurrent.futures.process import BrokenProcessPool

from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from ml.src.datasets import validate_dataset
from ml.src.inference import (
    PredictionTargetNotFoundError,
)
from ml.src.prediction_workers import run_prediction, shutdown_workers

from ml.src.contracts import (
    HealthOutput,
    PredictionInput,
    PredictionOutput,
    TrainOutput,
    BatchPredictionInput,
    BatchPredictionOutput,
)
from ml.src.runtime import (
    health,
    predict,
    train,
)


@asynccontextmanager
async def lifespan(app):
    yield
    shutdown_workers()


app = FastAPI(
    title="ASTRA ML Service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post("/datasets/{dataset_id}/validate")
def validate_prepared_dataset(dataset_id: UUID):
    try:
        return validate_dataset(dataset_id)
    except PredictionTargetNotFoundError as error:
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


@app.post(
    "/datasets/{dataset_id}/predict/{sensor_id}",
    response_model=PredictionOutput,
)
def predict_prepared_sensor(dataset_id: UUID, sensor_id: int) -> PredictionOutput:
    try:
        return run_prediction(dataset_id, [sensor_id], single=True)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except (SQLAlchemyError, FileNotFoundError, ImportError, OSError, BrokenProcessPool) as error:
        raise HTTPException(503, "ML-модель или подготовленные данные недоступны") from error


@app.post("/datasets/{dataset_id}/predict-batch", response_model=BatchPredictionOutput)
def predict_prepared_sensors(dataset_id: UUID, request: BatchPredictionInput):
    try:
        return run_prediction(dataset_id, request.sensor_ids)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except (SQLAlchemyError, FileNotFoundError, ImportError, OSError, BrokenProcessPool) as error:
        raise HTTPException(503, "ML-модель или подготовленные данные недоступны") from error
