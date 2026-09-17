export interface ImportResult {
  status: "success" | "error"
  filename?: string
  size_bytes?: number
  message: string
}


export async function importData(file: File): Promise<ImportResult> {
  const formData = new FormData()

  formData.append("file", file)

  const response = await fetch(
    "http://127.0.0.1:8000/api/import",
    {
      method: "POST",
      body: formData,
    }
  )

  if (!response.ok) {
    throw new Error("Ошибка загрузки файла")
  }

  return response.json()
}
