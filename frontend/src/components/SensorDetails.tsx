import type { Sensor } from "../api/sensors"

import { PredictionButton } from "./PredictionButton"


interface SensorDetailsProps {
  sensor: Sensor
  onClose: () => void
}


export function SensorDetails({
  sensor,
  onClose,
}: SensorDetailsProps) {
  return (
    <section className="sensor-details">
      <div className="sensor-details-header">
        <div>
          <span className="sensor-details-label">
            Датчик #{sensor.id}
          </span>

          <h2>{sensor.name}</h2>
        </div>

        <button
          className="sensor-details-close"
          onClick={onClose}
        >
          Закрыть
        </button>
      </div>

      <div className="sensor-details-grid">
        <div>
          <span>Тип</span>
          <strong>{sensor.type}</strong>
        </div>

        <div>
          <span>Текущее значение</span>
          <strong>{sensor.value}</strong>
        </div>

        <div>
          <span>Статус</span>
          <strong>{sensor.status}</strong>
        </div>

        <div>
          <span>Риск</span>
          <strong>
            {Math.round(sensor.risk * 100)}%
          </strong>
        </div>
      </div>

      <div className="sensor-details-prediction">
        <h3>ML-прогноз</h3>

        <PredictionButton sensorId={sensor.id} />
      </div>
    </section>
  )
}
