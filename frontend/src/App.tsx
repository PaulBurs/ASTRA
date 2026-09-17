import { useEffect, useState } from "react"

import { PredictionButton } from "./components/PredictionButton";

import { getSensors, type Sensor } from "./api/sensors"
import { getSystemHealth, type SystemHealth } from "./api/health"

import "./App.css"

import ImportPanel from "./components/ImportPanel"


function App() {
  const [sensors, setSensors] = useState<Sensor[]>([])
  const [health, setHealth] = useState<SystemHealth | null>(null)

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)


  useEffect(() => {
    Promise.all([
      getSensors(),
      getSystemHealth(),
    ])
      .then(([sensorsData, healthData]) => {
        setSensors(sensorsData)
        setHealth(healthData)
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


      <h2>Датчики</h2>

      {loading && <p>Загрузка...</p>}

      {!loading && !error && (
        <div className="sensor-list">
          {sensors.map((sensor) => (
            <div className="sensor-card" key={sensor.id}>
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
