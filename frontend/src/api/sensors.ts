import { API_URL } from "../config"

export type SensorStatus =
  | "OK"
  | "WARNING"
  | "CRITICAL"

export type SensorValueType =
  | "numeric"
  | "binary"
  | "datetime"
  | "text"

export interface Sensor {
  id: number
  name: string
  type: string

  engineering_system: string | null
  object_id: number | null

  value_type: SensorValueType | null
  value: number | string | null
  occurred_at: string | null

  status: SensorStatus
  risk: number
}

export async function getSensors(): Promise<Sensor[]> {
  const response = await fetch(
    `${API_URL}/api/sensors`
  )

  if (!response.ok) {
    throw new Error(
      `Failed to load sensors: ${response.status}`
    )
  }

  return response.json()
}
