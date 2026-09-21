import { useEffect, useState } from "react"

import { PredictionButton } from "./components/PredictionButton";
import { SensorDetails } from "./components/SensorDetails"

import type {
  Sensor,
  SensorStatus,
} from "./api/sensors"

import type { SystemHealth } from "./api/health"
import {
  getDashboard,
  type DashboardSummary,
} from "./api/dashboard"

import "./App.css"

import ImportPanel from "./components/ImportPanel"


type SensorFilter = "ALL" | SensorStatus
type SensorSort =
  | "RISK_DESC"
  | "RISK_ASC"
  | "VALUE_DESC"
  | "NAME_ASC"
  
  
function App() {
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [summary, setSummary] =
  useState<DashboardSummary | null>(null)
  const [sensorFilter, setSensorFilter] =
  useState<SensorFilter>("ALL")
  const [selectedSensor, setSelectedSensor] =
  useState<Sensor | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [sensorSort, setSensorSort] =
  useState<SensorSort>("RISK_DESC")

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const visibleSensors = sensors
  .filter((sensor) => {
    const matchesStatus =
      sensorFilter === "ALL" ||
      sensor.status === sensorFilter

    const query = searchQuery
      .trim()
      .toLowerCase()

    const matchesSearch =
      query === "" ||
      sensor.name.toLowerCase().includes(query) ||
      String(sensor.id).includes(query)

    return matchesStatus && matchesSearch
  })
  .sort((a, b) => {
    switch (sensorSort) {
      case "RISK_ASC":
        return a.risk - b.risk

      case "VALUE_DESC":
        return b.value - a.value

      case "NAME_ASC":
        return a.name.localeCompare(b.name, "ru")

      case "RISK_DESC":
      default:
        return b.risk - a.risk
    }
  })

  useEffect(() => {
  getDashboard()
    .then((dashboard) => {
      setSensors(dashboard.sensors)
      setHealth(dashboard.system)
      setSummary(dashboard.summary)
      setError(null)
    })
    .catch(() => {
      setError("Не удалось подключиться к ASTRA API")
    })
    .finally(() => {
      setLoading(false)
    })
}, [])


  return (
    <main>
      <header>
        <div>
          <h1>ASTRA</h1>
          <p>Система мониторинга инженерной инфраструктуры</p>
        </div>

        {health ? (
		  <span
			className={
			  health.status === "ok"
				? "system-online"
				: "system-offline"
			}
		  >
			{health.status === "ok"
			  ? "● Система работает"
			  : "● Система недоступна"}
		  </span>
		) : (
		  <span className="system-offline">
			● Нет подключения
		  </span>
		)}
      </header>


      {error && (
        <div className="error-message">
          {error}
        </div>
      )}


      {health && (
        <>
          <h2>Состояние системы</h2>

          <div className="health-grid">
            <HealthCard
              title="Backend"
              value={health.status === "ok" ? "Работает" : "Ошибка"}
              ok={health.status === "ok"}
            />

            <HealthCard
              title="PostgreSQL"
              value={
                health.database === "connected"
                  ? "Подключена"
                  : "Нет подключения"
              }
              ok={health.database === "connected"}
            />

            <HealthCard
              title="ML-модель"
              value={
                health.ml === "available"
                  ? "Доступна"
                  : "Недоступна"
              }
              ok={health.ml === "available"}
            />
          </div>
        </>
      )}
      
      {summary && (
        <>
          <h2>Сводка</h2>

          <div className="summary-grid">
            <div className="summary-card">
              <span>Всего датчиков</span>
              <strong>{summary.total_sensors}</strong>
            </div>

            <div className="summary-card summary-ok">
              <span>Норма</span>
              <strong>{summary.ok}</strong>
            </div>

            <div className="summary-card summary-warning">
              <span>Предупреждение</span>
              <strong>{summary.warning}</strong>
            </div>

            <div className="summary-card summary-critical">
              <span>Критические</span>
              <strong>{summary.critical}</strong>
            </div>

            <div className="summary-card summary-risk">
              <span>Максимальный риск</span>

              <strong>
                {Math.round(summary.max_risk * 100)}%
              </strong>

              <div className="risk-track">
                <div
                  className={`risk-fill ${
                    summary.max_risk >= 0.7
                      ? "risk-critical"
                      : summary.max_risk >= 0.4
                        ? "risk-warning"
                        : "risk-ok"
                  }`}
                  style={{
                    width: `${Math.round(
                      summary.max_risk * 100
                    )}%`,
                  }}
                />
              </div>
            </div>
          </div>
        </>
      )}


      <h2>Датчики</h2>
      
      <div className="sensor-toolbar">
		  <div className="sensor-controls">
			<input
			  type="search"
			  placeholder="Поиск по ID или названию..."
			  value={searchQuery}
			  onChange={(event) =>
				setSearchQuery(event.target.value)
			  }
			/>

			<label>
			  Статус:

			  <select
				value={sensorFilter}
				onChange={(event) =>
				  setSensorFilter(
				    event.target.value as SensorFilter
				  )
				}
			  >
				<option value="ALL">Все</option>
				<option value="CRITICAL">Критические</option>
				<option value="WARNING">Предупреждение</option>
				<option value="OK">Норма</option>
			  </select>
			</label>

			<label>
			  Сортировка:

			  <select
				value={sensorSort}
				onChange={(event) =>
				  setSensorSort(
				    event.target.value as SensorSort
				  )
				}
			  >
				<option value="RISK_DESC">
				  Риск: сначала высокий
				</option>

				<option value="RISK_ASC">
				  Риск: сначала низкий
				</option>

				<option value="VALUE_DESC">
				  Значение: по убыванию
				</option>

				<option value="NAME_ASC">
				  Название
				</option>
			  </select>
			</label>
		  </div>

  <span>
    Показано: {visibleSensors.length} из {sensors.length}
  </span>
</div>

      {loading && <p>Загрузка...</p>}

      {!loading && !error && (
        <div className="sensor-list">
          {visibleSensors.map((sensor) => (
            <div
			  className={`sensor-card sensor-${sensor.status.toLowerCase()}`}
			  key={sensor.id}
			  onClick={() => setSelectedSensor(sensor)}
			>
              <div>
                <strong>{sensor.name}</strong>
                <p>{sensor.type}</p>
              </div>

              <div>
                <strong>{sensor.value}</strong>
              </div>

              <div>
                <Status status={sensor.status} />
                <p>
                  Риск: {Math.round(sensor.risk * 100)}%
                </p>
              </div>

              <PredictionButton sensorId={sensor.id} />
            </div>
          ))}
        </div>
      )}
      
      {selectedSensor && (
        <SensorDetails
          sensor={selectedSensor}
          onClose={() => setSelectedSensor(null)}
        />
      )}
      
      <ImportPanel />
      
    </main>
  )
}


function HealthCard({
  title,
  value,
  ok,
}: {
  title: string
  value: string
  ok: boolean
}) {
  return (
    <div className="health-card">
      <span>{title}</span>

      <strong className={ok ? "health-ok" : "health-error"}>
        ● {value}
      </strong>
    </div>
  )
}


function Status({ status }: { status: Sensor["status"] }) {
  if (status === "OK") {
    return <span className="status ok">● Норма</span>
  }

  if (status === "WARNING") {
    return <span className="status warning">● Внимание</span>
  }

  return <span className="status critical">● Критично</span>
}


export default App
