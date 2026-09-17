export type SensorStatus = "OK" | "WARNING" | "CRITICAL"

export interface Sensor {
  id: number
  name: string
  type: string
  value: number
  status: SensorStatus
  risk: number
}

export async function getSensors(): Promise<Sensor[]> {
  const response = await fetch("http://127.0.0.1:8000/api/sensors")

  if (!response.ok) {
    throw new Error("Не удалось получить список датчиков")
  }

  return response.json()
}
