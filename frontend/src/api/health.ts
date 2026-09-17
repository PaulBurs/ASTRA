export interface SystemHealth {
  status: "ok" | "error"
  application: string
  database: "connected" | "disconnected"
  ml: "available" | "unavailable"
}


export async function getSystemHealth(): Promise<SystemHealth> {
  const response = await fetch("http://127.0.0.1:8000/api/health")

  if (!response.ok) {
    throw new Error("Не удалось получить состояние ASTRA")
  }

  return response.json()
}
