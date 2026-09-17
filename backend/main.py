from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.ml import router as ml_router
from app.api.sensors import router as sensors_router
from app.api.import_data import router as import_router


app = FastAPI(
    title="ASTRA API",
    description="Backend API for ASTRA monitoring system",
    version="0.1.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
    "http://localhost:5173",
    "http://127.0.0.1:5173",
],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    health_router,
    prefix="/api",
    tags=["System"],
)

app.include_router(
    ml_router,
    prefix="/api/ml",
    tags=["Machine Learning"],
)

app.include_router(
    sensors_router,
    prefix="/api/sensors",
    tags=["Sensors"],
)

app.include_router(
    import_router,
    prefix="/api/import",
    tags=["Data Import"],
)


@app.get("/")
def root():
    return {
        "application": "ASTRA",
        "status": "running",
    }
