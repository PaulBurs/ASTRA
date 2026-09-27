export interface DatasetFile {
  name: string
  size: number
  uploaded: boolean
  role: string | null
}

export interface Dataset {
  id: string
  status: "uploading" | "preparing" | "prepared" | "ready" | "error"
  stage: string
  files: DatasetFile[]
  counts: Record<string, number>
  error: string | null
  ml_check: { row_count: number; columns: string[] } | null
}

async function responseData(response: Response): Promise<Dataset> {
  const body = await response.json()
  if (!response.ok) {
    const detail = typeof body.detail === "string"
      ? body.detail
      : "Не удалось обработать запрос. Проверьте выбранные CSV-файлы."
    throw new Error(detail)
  }
  return body as Dataset
}

export async function createDataset(files: File[]): Promise<Dataset> {
  return responseData(await fetch("/api/datasets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ files: files.map(file => ({ name: file.name, size: file.size })) }),
  }))
}

export async function getDataset(id: string): Promise<Dataset> {
  return responseData(await fetch(`/api/datasets/${encodeURIComponent(id)}`))
}

export async function discardDataset(id: string): Promise<void> {
  const response = await fetch(`/api/datasets/${encodeURIComponent(id)}`, { method: "DELETE" })
  if (!response.ok) await responseData(response)
}

export async function prepareDataset(id: string): Promise<Dataset> {
  return responseData(await fetch(`/api/datasets/${encodeURIComponent(id)}/prepare`, { method: "POST" }))
}

export async function validateDatasetML(id: string): Promise<Dataset> {
  return responseData(await fetch(`/api/datasets/${encodeURIComponent(id)}/validate-ml`, { method: "POST" }))
}

export function uploadDatasetFile(
  id: string, index: number, file: File, onProgress: (bytes: number) => void,
): Promise<Dataset> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("PUT", `/api/datasets/${encodeURIComponent(id)}/files/${index}`)
    xhr.setRequestHeader("Content-Type", "application/octet-stream")
    xhr.upload.onprogress = event => onProgress(event.loaded)
    xhr.onerror = () => reject(new Error("Загрузка прервана: проверьте соединение с сервером"))
    xhr.onload = () => {
      try {
        const body = JSON.parse(xhr.responseText)
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as Dataset)
        else reject(new Error(typeof body.detail === "string" ? body.detail : "Ошибка загрузки файла"))
      } catch {
        reject(new Error("Сервер вернул некорректный ответ при загрузке"))
      }
    }
    xhr.send(file)
  })
}
