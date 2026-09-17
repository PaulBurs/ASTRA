from fastapi import UploadFile


class ImportService:
    """Сервис импорта файлов с данными в ASTRA."""

    ALLOWED_EXTENSIONS = {".xls", ".xlsx"}

    def validate_file(self, file: UploadFile) -> bool:
        filename = file.filename or ""

        return any(
            filename.lower().endswith(extension)
            for extension in self.ALLOWED_EXTENSIONS
        )

    async def import_file(self, file: UploadFile) -> dict:
        if not self.validate_file(file):
            return {
                "status": "error",
                "message": "Поддерживаются только файлы XLS и XLSX",
            }

        content = await file.read()

        return {
            "status": "success",
            "filename": file.filename,
            "size_bytes": len(content),
            "message": "Файл успешно принят ASTRA",
        }
