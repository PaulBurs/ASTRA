import { useCallback, useEffect, useState } from "react"
import { datasetRequest, type ForecastJob } from "../api/liveWorkspace"
import { forecastTiming } from "../utils/forecastTiming"

const number = (value: number) => value.toLocaleString("ru-RU")
const active = (job: ForecastJob | null) => ["running", "stopping"].includes(job?.status ?? "")
const statusText: Record<ForecastJob["status"], string> = {
  running: "Идёт расчёт", stopping: "Останавливаем", completed: "Расчёт завершён",
  stopped: "Расчёт остановлен", interrupted: "Расчёт прерван", error: "Ошибка расчёта",
}

/** Model inference is a separate step: it starts only by this button and never while data is being prepared. */
export function ForecastPanel({ datasetId, userId, datasetReady }: { datasetId?: string; userId: string; datasetReady: boolean }) {
  const [job, setJob] = useState<ForecastJob | null>(null)
  const [preparing, setPreparing] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [, setTick] = useState(0)
  const load = useCallback(async () => {
    if (!datasetId || !datasetReady) return
    const value = await datasetRequest<{ job: ForecastJob | null; preparing: boolean }>(datasetId, "forecasts/job", userId)
    setJob(value.job); setPreparing(value.preparing)
  }, [datasetId, datasetReady, userId])
  const running = active(job)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try { await load(); if (alive) setError("") } catch (cause) { if (alive) setError((cause as Error).message) }
      finally { if (alive) timer = setTimeout(poll, running ? 2000 : 10000) }
    }
    void poll()
    return () => { alive = false; clearTimeout(timer) }
  }, [load, running])
  useEffect(() => {            // elapsed time keeps moving between polls
    if (!running) return
    const timer = setInterval(() => setTick(value => value + 1), 1000)
    return () => clearInterval(timer)
  }, [running])
  async function act(path: string) {
    if (!datasetId) return
    setBusy(true); setError("")
    try { setJob(await datasetRequest<ForecastJob>(datasetId, path, userId, "POST")) }
    catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  const blocked = !datasetReady || preparing
  const timing = job && forecastTiming(job)
  return <section className="dataset-result dataset-forecast" aria-labelledby="dataset-forecast-title" aria-live="polite">
    <div className="dataset-card-heading">
      <h2 id="dataset-forecast-title">Прогноз модели</h2>
      {job && <span className={`dataset-badge ${job.status === "completed" ? "is-ready" : job.status === "error" ? "is-error" : ""}`}>{statusText[job.status]}</span>}
    </div>
    <p className="dataset-description">Расчёт вероятности тревоги для всех датчиков обученной моделью. Запускается только этой кнопкой (или кнопкой на главной) и не выполняется во время подготовки данных.</p>
    {blocked && <p className="dataset-note">{!datasetReady ? "Станет доступен после подготовки данных и проверки ML." : "Идёт подготовка данных. Прогноз можно запустить после её завершения."}</p>}
    {job && <div className="dataset-progress">
      <div><span>{number(job.completed)} из {number(job.total)} датчиков · готово {number(job.predicted)}, без данных {number(job.skipped)}{job.failed ? `, ошибок ${number(job.failed)}` : ""}</span><strong>{job.total ? Math.floor(job.completed / job.total * 100) : 0}%</strong></div>
      <progress max={job.total || 1} value={job.completed} aria-label="Прогресс расчёта прогноза"/>
      {timing && <small>{timing}</small>}
    </div>}
    {job?.error && <p className="dataset-error" role="alert">{job.error}</p>}
    {error && <p className="dataset-error" role="alert">{error}</p>}
    <div className="dataset-actions">
      <button className="dataset-primary" type="button" disabled={busy || blocked || running} onClick={() => void act("forecasts")}>
        {running ? "Прогноз рассчитывается…" : job?.completed ? "Пересчитать недостающие прогнозы" : "Запустить прогноз модели"}
      </button>
      {running && <button type="button" disabled={busy || job?.status === "stopping"} onClick={() => void act("forecasts/stop")}>
        {job?.status === "stopping" ? "Останавливаем…" : "Остановить прогноз"}</button>}
    </div>
  </section>
}
