from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dashboard import router as dashboard_router
from app.api.datasets import router as datasets_router
from app.api.data_source import router as data_source_router
from app.api.health import router as health_router
from app.api.ml import router as ml_router
from app.api.sensors import router as sensors_router
from app.api.live_workspace import router as workspace_router


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


# health.py already declares @router.get("/health"),
# therefore only the common /api prefix belongs here.
app.include_router(
    health_router,
    prefix="/api",
    tags=["health"],
)

app.include_router(
    sensors_router,
    prefix="/api/sensors",
    tags=["sensors"],
)

app.include_router(
    dashboard_router,
    prefix="/api/dashboard",
    tags=["dashboard"],
)

app.include_router(
    ml_router,
    prefix="/api/ml",
    tags=["ml"],
)

# data_source.py already owns prefix="/api/data-source".
app.include_router(
    data_source_router,
)
app.include_router(datasets_router)
app.include_router(workspace_router)


@app.get("/")
def root():
    return {
        "application": "ASTRA",
        "status": "running",
    }
