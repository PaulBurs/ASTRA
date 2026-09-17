import { useState } from "react";

import {
  getPrediction,
  type MLPrediction,
} from "../api/ml";


interface PredictionButtonProps {
  sensorId: number;
}


export function PredictionButton({
  sensorId,
}: PredictionButtonProps) {
  const [prediction, setPrediction] =
    useState<MLPrediction | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);


  async function handlePrediction() {
    try {
      setLoading(true);
      setError(null);

      const result = await getPrediction(sensorId);

      setPrediction(result);
    } catch {
      setError("Не удалось получить прогноз");
    } finally {
      setLoading(false);
    }
  }


  return (
    <div className="prediction-panel">
      <button
        onClick={handlePrediction}
        disabled={loading}
      >
        {loading ? "Расчёт..." : "Получить прогноз"}
      </button>

      {prediction && (
        <div className="prediction-result">
          <strong>
            Вероятность:{" "}
            {(prediction.probability * 100).toFixed(0)}%
          </strong>

          <span>
            Горизонт: {prediction.horizon_hours} ч.
          </span>

          <span>
            Модель: {prediction.model_version}
          </span>
        </div>
      )}

      {error && (
        <div className="prediction-error">
          {error}
        </div>
      )}
    </div>
  );
}
