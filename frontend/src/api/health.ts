import { API_URL } from "../config"

export interface SystemHealth {
  status: "ok" | "error"
  application: string
  database: "connected" | "disconnected"
  ml: "available" | "unavailable"
}


export async function getSystemHealth(): Promise<SystemHealth> {
  const response = await fetch(`${API_URL}/api/health`)

  if (!response.ok) {
    throw new Error("Не удалось получить состояние ASTRA")
  }

  return response.json()
}
