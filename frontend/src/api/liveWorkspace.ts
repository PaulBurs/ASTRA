import { API_URL } from "../config"
import type { Sensor } from "./sensors"
import type { MLPrediction } from "./ml"

export interface LiveCheck {
  id: number; sensor_id: number; assignee_id: string; deadline: string
  status: "Новая" | "В работе" | "Завершена"; revision: number
  outcome: "clear" | "fixed" | "unresolved" | null
  result: string | null; work_description: string | null; created_at: string; completed_at: string | null
}
export interface LiveWorkspaceData {
  sensors: Sensor[]; objects: { id: number; name: string | null }[]
  checks: LiveCheck[]; assignees: { id: string; name: string }[]
}
export interface ForecastRecord {
  sensor_id: number; status: "ready" | "skipped" | "error"; result: MLPrediction | null; error: string | null; updated_at: string
}
export interface ForecastJob {
  id: string; status: "running" | "stopping" | "stopped" | "completed" | "interrupted" | "error"
  total: number; completed: number; predicted: number; skipped: number; failed: number; error: string | null
}
export interface Forecasts { job: ForecastJob | null; predictions: ForecastRecord[] }
export interface SensorEvent {
  id: number; occurred_at: string; value_type: string; value: number | string | null; alarm: string | null
}
export interface SensorHistory {
  id: number | string; check_id: number | null; actor_id: string; action: string; created_at: string
}
export interface LiveSensorDetails {
  sensor: Sensor
  object: { id: number; name: string | null; type: string | null } | null
  events: SensorEvent[]
  checks: LiveCheck[]
  history: SensorHistory[]
  prediction: ForecastRecord | null
  employees: Record<string, string>
}
export async function datasetRequest<T>(dataset: string, path: string, userId: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_URL}/api/datasets/${encodeURIComponent(dataset)}/${path}`, {
    method, headers: { "Content-Type": "application/json", "X-Employee-ID": userId },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = "Не удалось выполнить запрос. Повторите попытку."
    try { const payload = await response.json(); if (typeof payload.detail === "string") message = payload.detail; else if (response.status === 422) message = "Проверьте заполненные поля и срок проверки." } catch { /* gateway response */ }
    throw new Error(message)
  }
  return response.json()
}
