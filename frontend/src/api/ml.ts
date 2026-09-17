import { API_URL } from "../config";


export interface MLPrediction {
  sensor_id: number;
  probability: number;
  horizon_hours: number;
  model_version: string;
}


export async function getPrediction(
  sensorId: number
): Promise<MLPrediction> {
  const response = await fetch(
    `${API_URL}/api/ml/predict/${sensorId}`
  );

  if (!response.ok) {
    throw new Error("Не удалось получить ML-прогноз");
  }

  return response.json();
}
