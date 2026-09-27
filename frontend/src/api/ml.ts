import { API_URL } from "../config";


export interface MLPrediction {
  sensor_id: number;
  probability: number;
  horizon_hours: number;
  model_version: string;
}


export async function getPrediction(
  sensorId: number,
  datasetId?: string,
): Promise<MLPrediction> {
  const response = await fetch(
    `${API_URL}/api/ml/predict/${sensorId}${datasetId ? `?dataset_id=${encodeURIComponent(datasetId)}` : ""}`
  );

  if (!response.ok) {
    let message = "Не удалось получить ML-прогноз";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") message = payload.detail;
    } catch {
      // The fallback message is suitable for non-JSON gateway errors.
    }
    throw new Error(message);
  }

  return response.json();
}
