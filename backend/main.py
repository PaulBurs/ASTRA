from fastapi import FastAPI

from app.api.health import router as health_router


app = FastAPI(
    title="ASTRA API",
    description="Backend API for ASTRA monitoring system",
    version="0.1.0",
)

app.include_router(
    health_router,
    prefix="/api",
    tags=["System"],
)


@app.get("/")
def root():
    return {
        "application": "ASTRA",
        "status": "running"
    }
