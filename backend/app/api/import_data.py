from fastapi import APIRouter, File, UploadFile

from app.services.import_service import ImportService


router = APIRouter()

import_service = ImportService()


@router.post("")
async def import_data(
    file: UploadFile = File(...)
):
    return await import_service.import_file(file)
