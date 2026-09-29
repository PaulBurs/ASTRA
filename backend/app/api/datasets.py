from pathlib import PurePath
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.db.database import engine
from app.services.dataset_import_service import DatasetImportService
from astra_pipeline.registry import ensure_registry

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


class SelectedFile(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if (PurePath(value).name != value or "\\" in value or "\x00" in value
                or not value.lower().endswith(".csv")):
            raise ValueError("Выберите CSV-файл из распакованного архива")
        return value


class CreateDataset(BaseModel):
    files: list[SelectedFile] = Field(min_length=3, max_length=32)

    @field_validator("files")
    @classmethod
    def distinct_names(cls, value):
        if len({file.name for file in value}) != len(value):
            raise ValueError("Файлы с одинаковыми именами нельзя загрузить в один набор")
        return value


def get_import_service():
    ensure_registry(engine)
    return DatasetImportService(engine)


@router.post("", status_code=201)
def create_dataset(request: CreateDataset, service=Depends(get_import_service)):
    return service.create(request.files)


@router.get("/{dataset_id}")
def dataset_status(dataset_id: UUID, service=Depends(get_import_service)):
    return service.status(dataset_id)


@router.delete("/{dataset_id}", status_code=204)
def discard_dataset(
    dataset_id: UUID,
    confirm_delete: bool = False,
    x_employee_id: str | None = Header(default=None),
    service=Depends(get_import_service),
):
    # Prepared datasets require an explicit second signal from the confirmation
    # UI. Incomplete uploads retain the existing one-click cleanup path.
    if confirm_delete and x_employee_id != "1001":
        raise HTTPException(403, "Удаление базы доступно только диспетчеру")
    service.discard(dataset_id, include_prepared=confirm_delete)


@router.put("/{dataset_id}/files/{index}")
async def upload_file(dataset_id: UUID, index: int, request: Request, service=Depends(get_import_service)):
    return await service.upload(dataset_id, index, request)


@router.post("/{dataset_id}/prepare", status_code=202)
def prepare(dataset_id: UUID, background_tasks: BackgroundTasks, service=Depends(get_import_service)):
    return service.start(dataset_id, background_tasks)


@router.post("/{dataset_id}/validate-ml")
def validate_ml(dataset_id: UUID, service=Depends(get_import_service)):
    service.status(dataset_id)
    with service.lock(dataset_id):
        return service.validate_ml(dataset_id)
