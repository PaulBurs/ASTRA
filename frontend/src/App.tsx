import { useEffect, useState } from "react"

import { WarningsPage } from "./components/WarningsPage"
import { PredictionButton } from "./components/PredictionButton"
import { SensorDetails } from "./components/SensorDetails"
import DataSourcePanel from "./components/DataSourcePanel"

import type {
  Sensor,
  SensorStatus,
} from "./api/sensors"

import {
  getSystemHealth,
  type SystemHealth,
} from "./api/health"

import {
  getDashboard,
  type DashboardSummary,
} from "./api/dashboard"

import {
  formatOccurredAt,
  formatSensorValue,
} from "./utils/sensorFormat"

import "./App.css"

type SensorFilter = "ALL" | SensorStatus

type SensorSort =
  | "RISK_DESC"
  | "RISK_ASC"
  | "VALUE_DESC"
  | "NAME_ASC"

type ActivePage = "warnings" | "dashboard"

const DISPLAY_LIMIT = 100

function numericSensorValue(sensor: Sensor): number {
  if (typeof sensor.value === "number") {
    return sensor.value
  }

  return Number.NEGATIVE_INFINITY
}

function App() {
  const [activePage, setActivePage] =
    useState<ActivePage>("warnings")

  const [sensors, setSensors] = useState<Sensor[]>([])
  const [health, setHealth] =
    useState<SystemHealth | null>(null)
  const [summary, setSummary] =
    useState<DashboardSummary | null>(null)
  const [sensorFilter, setSensorFilter] =
    useState<SensorFilter>("ALL")
  const [selectedSensor, setSelectedSensor] =
    useState<Sensor | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [sensorSort, setSensorSort] =
    useState<SensorSort>("RISK_DESC")
  const [sourceConnected, setSourceConnected] =
    useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const visibleSensors = sensors
    .filter((sensor) => {
      const matchesStatus =
        sensorFilter === "ALL" ||
        sensor.status === sensorFilter

      const query = searchQuery.trim().toLowerCase()

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
          return (
            numericSensorValue(b) -
            numericSensorValue(a)
          )

        case "NAME_ASC":
          return a.name.localeCompare(b.name, "ru")

        case "RISK_DESC":
        default:
          return b.risk - a.risk
      }
    })

  const displayedSensors = visibleSensors.slice(
    0,
    DISPLAY_LIMIT,
  )

  useEffect(() => {
    getSystemHealth()
      .then((systemHealth) => {
        setHealth(systemHealth)
      })
      .catch(() => {
        setHealth(null)
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  async function loadDashboard() {
    setLoading(true)
    setError(null)

    try {
      const dashboard = await getDashboard()

      setSensors(dashboard.sensors)
      setHealth(dashboard.system)
      setSummary(dashboard.summary)
      setSourceConnected(true)
    } catch {
      setError(
        "Не удалось получить данные выбранного источника",
      )
    } finally {
      setLoading(false)
    }
  }

  function handleSourceConnected() {
    setSourceConnected(true)
    setSensors([])
    setSummary(null)
    setSelectedSensor(null)

    void loadDashboard()
  }

  if (activePage === "warnings") {
    return (
      <WarningsPage
        onOpenObjects={() => setActivePage("dashboard")}
        onOpenJournal={() =>
          window.alert("Журнал прогнозов пока не подключён")
        }
      />
    )
  }

  return (
    <main>
      <header>
        <div>
          <h1>ASTRA</h1>
          <p>
            Система мониторинга инженерной инфраструктуры
          </p>
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

      <nav
        aria-label="Разделы"
        style={{
          display: "flex",
          gap: "8px",
          margin: "16px 0",
        }}
      >
        <button
          type="button"
          onClick={() => setActivePage("warnings")}
        >
          Предупреждения
        </button>

        <button
          type="button"
          aria-current="page"
          onClick={() => setActivePage("dashboard")}
        >
          Датчики
        </button>
      </nav>

      <>
          <DataSourcePanel
            onConnected={handleSourceConnected}
          />

          {error && (
            <div className="error-message">{error}</div>
          )}

          {health && (
            <>
              <h2>Состояние системы</h2>

              <div className="health-grid">
                <HealthCard
                  title="Backend"
                  value={
                    health.status === "ok"
                      ? "Работает"
                      : "Ошибка"
                  }
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
                          summary.max_risk * 100,
                        )}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            </>
          )}

          {sourceConnected && (
            <>
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
                          event.target.value as SensorFilter,
                        )
                      }
                    >
                      <option value="ALL">Все</option>
                      <option value="CRITICAL">
                        Критические
                      </option>
                      <option value="WARNING">
                        Предупреждение
                      </option>
                      <option value="OK">Норма</option>
                    </select>
                  </label>

                  <label>
                    Сортировка:
                    <select
                      value={sensorSort}
                      onChange={(event) =>
                        setSensorSort(
                          event.target.value as SensorSort,
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
                  Показано: {displayedSensors.length} из{" "}
                  {sensors.length}
                </span>
              </div>

              {loading && <p>Загрузка...</p>}

              {!loading &&
                !error &&
                visibleSensors.length === 0 && (
                  <div className="sensor-empty">
                    <strong>Датчики не найдены</strong>
                    <p>
                      Измените строку поиска или фильтр
                      статуса.
                    </p>
                  </div>
                )}

              {!loading &&
                !error &&
                visibleSensors.length > 0 && (
                  <>
                    <div className="sensor-list">
                      {displayedSensors.map((sensor) => (
                        <div
                          className={`sensor-card sensor-${sensor.status.toLowerCase()}`}
                          key={sensor.id}
                          onClick={() =>
                            setSelectedSensor(sensor)
                          }
                        >
                          <div className="sensor-card-main">
                            <div className="sensor-card-title">
                              <strong>{sensor.name}</strong>
                              <span className="sensor-id">
                                #{sensor.id}
                              </span>
                            </div>

                            <p>{sensor.type}</p>

                            {sensor.engineering_system && (
                              <p className="sensor-system">
                                {sensor.engineering_system}
                              </p>
                            )}

                            <p className="sensor-event-time">
                              Последнее событие:{" "}
                              {formatOccurredAt(
                                sensor.occurred_at,
                              )}
                            </p>
                          </div>

                          <div className="sensor-card-value">
                            <span>Значение</span>
                            <strong>
                              {formatSensorValue(sensor)}
                            </strong>
                            {sensor.value_type && (
                              <small>{sensor.value_type}</small>
                            )}
                          </div>

                          <div className="sensor-card-risk">
                            <Status status={sensor.status} />

                            <div className="sensor-risk-header">
                              <span>Риск</span>
                              <strong>
                                {Math.round(sensor.risk * 100)}%
                              </strong>
                            </div>

                            <div className="risk-track">
                              <div
                                className={`risk-fill ${
                                  sensor.risk >= 0.7
                                    ? "risk-critical"
                                    : sensor.risk >= 0.4
                                      ? "risk-warning"
                                      : "risk-ok"
                                }`}
                                style={{
                                  width: `${Math.round(
                                    sensor.risk * 100,
                                  )}%`,
                                }}
                              />
                            </div>
                          </div>

                          <div
                            className="sensor-card-actions"
                            onClick={(event) =>
                              event.stopPropagation()
                            }
                          >
                            <PredictionButton
                              sensorId={sensor.id}
                            />
                          </div>
                        </div>
                      ))}
                    </div>

                    {visibleSensors.length >
                      DISPLAY_LIMIT && (
                      <p className="sensor-list-note">
                        Показаны первые {DISPLAY_LIMIT}{" "}
                        датчиков. Используйте поиск и фильтры,
                        чтобы сузить список.
                      </p>
                    )}
                  </>
                )}
            </>
          )}

          {selectedSensor && (
            <SensorDetails
              sensor={selectedSensor}
              onClose={() => setSelectedSensor(null)}
            />
          )}
      </>
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
      <strong
        className={ok ? "health-ok" : "health-error"}
      >
        ● {value}
      </strong>
    </div>
  )
}

function Status({
  status,
}: {
  status: Sensor["status"]
}) {
  if (status === "OK") {
    return <span className="status ok">● Норма</span>
  }

  if (status === "WARNING") {
    return <span className="status warning">● Внимание</span>
  }

  return <span className="status critical">● Критично</span>
}

export default App
