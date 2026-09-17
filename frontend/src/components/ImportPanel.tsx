import { useState } from "react"

import {
  importData,
  type ImportResult,
} from "../api/importData"


function ImportPanel() {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<ImportResult | null>(null)
  const [uploading, setUploading] = useState(false)


  async function handleUpload() {
    if (!file) {
      return
    }

    setUploading(true)
    setResult(null)

    try {
      const response = await importData(file)
      setResult(response)
    } catch {
      setResult({
        status: "error",
        message: "Не удалось загрузить файл",
      })
    } finally {
      setUploading(false)
    }
  }


  return (
    <section className="import-panel">
      <h2>Импорт данных</h2>

      <p>
        Загрузите исторические данные датчиков
        в формате XLS или XLSX.
      </p>

      <div className="import-controls">
        <input
          type="file"
          accept=".xls,.xlsx"
          onChange={(event) => {
            const selectedFile = event.target.files?.[0] ?? null

            setFile(selectedFile)
            setResult(null)
          }}
        />

        <button
          onClick={handleUpload}
          disabled={!file || uploading}
        >
          {uploading ? "Загрузка..." : "Загрузить"}
        </button>
      </div>

      {file && (
        <p className="selected-file">
          Выбран файл: <strong>{file.name}</strong>
        </p>
      )}

      {result && (
        <div
          className={
            result.status === "success"
              ? "import-result success"
              : "import-result failure"
          }
        >
          <strong>
            {result.status === "success" ? "✓ Успешно" : "Ошибка"}
          </strong>

          <p>{result.message}</p>

          {result.filename && (
            <p>Файл: {result.filename}</p>
          )}

          {result.size_bytes !== undefined && (
            <p>
              Размер: {(result.size_bytes / 1024).toFixed(1)} КБ
            </p>
          )}
        </div>
      )}
    </section>
  )
}


export default ImportPanel
