import { API_URL } from "../config"

import type { SystemHealth } from "./health"
import type { Sensor } from "./sensors"


export interface DashboardSummary {
  total_sensors: number
  ok: number
  warning: number
  critical: number
  max_risk: number
}


export interface Dashboard {
  system: SystemHealth
  summary: DashboardSummary
  sensors: Sensor[]
}


export async function getDashboard(): Promise<Dashboard> {
  const response = await fetch(`${API_URL}/api/dashboard`)

  if (!response.ok) {
    throw new Error("Не удалось получить данные панели ASTRA")
  }

  return response.json()
}
