from fastapi import APIRouter, File, UploadFile

from app.services.import_service import ImportService
from app.schemas.import_data import ImportResponse


router = APIRouter()

import_service = ImportService()


@router.post("", response_model=ImportResponse)
async def import_data(
    file: UploadFile = File(...)
):
    return await import_service.import_file(file)
