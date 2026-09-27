import type { Sensor } from "../api/sensors"

import { PredictionButton } from "./PredictionButton"
import {
  formatOccurredAt,
  formatSensorValue,
} from "../utils/sensorFormat"


interface SensorDetailsProps {
  sensor: Sensor
  datasetId?: string
  onClose: () => void
}


export function SensorDetails({
  sensor,
  datasetId,
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
		  <span>Инженерная система</span>
		  <strong>
			{sensor.engineering_system ?? "Не указана"}
		  </strong>
		</div>

		<div>
		  <span>Объект</span>
		  <strong>
			{sensor.object_id ?? "Не указан"}
		  </strong>
		</div>

        <div>
		  <span>Текущее значение</span>
		  <strong>{formatSensorValue(sensor)}</strong>
		</div>
		
		<div>
		  <span>Последнее событие</span>
		  <strong>
			{formatOccurredAt(sensor.occurred_at)}
		  </strong>
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

        <PredictionButton key={`${datasetId}-${sensor.id}`} sensorId={sensor.id} datasetId={datasetId} />
      </div>
    </section>
  )
}
