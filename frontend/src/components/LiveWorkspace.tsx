import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { User } from "../api/auth"
import { datasetRequest, type ForecastJob, type Forecasts, type LiveCheck, type LiveSensorDetails, type LiveWorkspaceData } from "../api/liveWorkspace"
import { getPrediction } from "../api/ml"
import { navigate, type Route } from "../state/navigation"
import { formatDate, outcomes } from "../state/workspace"
import { DetailPanel } from "./DetailPanel"
import { EmptyWorkspace } from "./EmptyWorkspace"
import "./DemoWorkspace.css"
import "./LiveWorkspace.css"

const titles = { warnings: "Главная", map: "Карта", checks: "Проверки", archive: "Архив" }
const subtitles = { warnings: "Все датчики, показания и прогнозы из загруженной базы", map: "Объекты и датчики из загруженной базы", checks: "Назначенные исполнители, сроки и результаты осмотров", archive: "Завершённые проверки и итоговые отчёты" }
const percent = (value: number) => `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`
const valueType = (value: string | null | undefined) => ({ numeric: "Числовое", text: "Текстовое", boolean: "Логическое" }[value ?? ""] ?? value ?? "Не указан в БД")
const alarmType = (value: string | null) => value === null || value === "" ? "" : ["t", "true", "1"].includes(value.toLowerCase()) ? " · тревожное событие" : ["f", "false", "0"].includes(value.toLowerCase()) ? " · обычное событие" : ` · признак тревоги: ${value}`

export function LiveWorkspace({ datasetId, user, route }: { datasetId: string; user: User; route: Route }) {
  const [workspace, setWorkspace] = useState<LiveWorkspaceData | null>(null)
  const [forecasts, setForecasts] = useState<Forecasts>({ job: null, predictions: [] })
  const [detailsState, setDetailsState] = useState<{ sensorId: number; value: LiveSensorDetails | null; error: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [forecastError, setForecastError] = useState("")
  const [busy, setBusy] = useState(false)
  const [predicting, setPredicting] = useState<number | null>(null)
  const locked = useRef(false)
  const [refresh, setRefresh] = useState(0)
  const reload = useCallback(() => setRefresh(value => value + 1), [])
  useEffect(() => {
    let active = true
    void datasetRequest<LiveWorkspaceData>(datasetId, "workspace", user.id).then(value => {
      if (active) { setWorkspace(value); setError("") }
    }).catch(cause => { if (active) setError(cause.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [datasetId, user.id, refresh])
  const selectedSensorId = route.id && workspace
    ? route.page === "warnings" || route.page === "map" ? Number(route.id)
      : workspace.checks.find(check => String(check.id) === route.id)?.sensor_id
    : undefined
  const details = detailsState && detailsState.sensorId === selectedSensorId ? detailsState.value : null
  const detailsError = detailsState && detailsState.sensorId === selectedSensorId ? detailsState.error : ""
  const detailsLoading = !!selectedSensorId && detailsState?.sensorId !== selectedSensorId
  useEffect(() => {
    if (!selectedSensorId || !Number.isInteger(selectedSensorId)) return
    let active = true
    void datasetRequest<LiveSensorDetails>(datasetId, `sensors/${selectedSensorId}`, user.id)
      .then(value => { if (active) setDetailsState({ sensorId: selectedSensorId, value, error: "" }) })
      .catch(cause => { if (active) setDetailsState({ sensorId: selectedSensorId, value: null, error: (cause as Error).message }) })
    return () => { active = false }
  }, [datasetId, user.id, selectedSensorId, refresh])
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      let delay = 12000
      try {
        const value = await datasetRequest<Forecasts>(datasetId, "forecasts", user.id)
        if (active) { setForecasts(value); setForecastError("") }
        if (["running", "stopping"].includes(value.job?.status ?? "")) delay = 2000
      } catch (cause) { if (active) setForecastError((cause as Error).message) }
      finally { if (active) timer = setTimeout(poll, delay) }
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [datasetId, user.id, refresh])
  // Refresh assignments made in another browser/session when returning to a tab.
  useEffect(() => {
    const listener = () => { if (!document.hidden) reload() }
    document.addEventListener("visibilitychange", listener)
    return () => document.removeEventListener("visibilitychange", listener)
  }, [reload])
  async function run(operation: () => Promise<void>) {
    if (locked.current) return
    locked.current = true; setBusy(true); setError("")
    try { await operation() } catch (cause) { setError((cause as Error).message) }
    finally { locked.current = false; setBusy(false) }
  }
  async function predictAll() {
    await run(async () => {
      const job = await datasetRequest<ForecastJob>(datasetId, "forecasts", user.id, "POST")
      setForecasts(current => ({ ...current, job })); reload()
    })
  }
  async function stopPredictions() {
    await run(async () => {
      const job = await datasetRequest<ForecastJob>(datasetId, "forecasts/stop", user.id, "POST")
      setForecasts(current => ({ ...current, job }))
    })
  }
  async function predictOne(id: number) {
    await run(async () => {
      setPredicting(id)
      try {
        const result = await getPrediction(id, datasetId)
        setForecasts(current => ({ ...current, predictions: [...current.predictions.filter(row => row.sensor_id !== id), {
          sensor_id: id, status: "ready", result, error: null, updated_at: new Date().toISOString(),
        }] }))
      } finally { setPredicting(null); reload() }
    })
  }
  async function createCheck(sensorId: number, form: FormData) {
    await run(async () => {
      const check = await datasetRequest<LiveCheck>(datasetId, "checks", user.id, "POST", {
        sensor_id: sensorId, assignee_id: form.get("assignee"), deadline: new Date(String(form.get("deadline"))).toISOString(),
      })
      setWorkspace(current => current && { ...current, checks: [check, ...current.checks] })
      navigate("checks", check.id)
    })
  }
  async function updateCheck(check: LiveCheck, action: "start" | "complete", form?: FormData) {
    await run(async () => {
      const updated = await datasetRequest<LiveCheck>(datasetId, `checks/${check.id}`, user.id, "PATCH", {
        action, revision: check.revision, outcome: form?.get("outcome") ?? undefined,
        result: form?.get("result") ?? "", work_description: form?.get("work") ?? "",
      })
      setWorkspace(current => current && { ...current, checks: current.checks.map(row => row.id === check.id ? updated : row) })
      if (updated.status === "Завершена") navigate("archive", updated.id)
    })
  }
  if (route.page === "data") return null // Keep polling and batch state alive on the upload screen.
  if (!workspace) return <main className="warnings-page"><section className="section-empty" role={loading ? "status" : "alert"}><h2>{loading ? "Загрузка датчиков…" : "Не удалось прочитать базу данных"}</h2>{error && <p>{error}</p>}{!loading && <button onClick={reload}>Повторить</button>}</section></main>
  if (!(route.page in titles)) return <EmptyWorkspace page={route.page}/>
  return <LiveTable key={route.page} page={route.page as keyof typeof titles} selectedId={route.id} user={user} workspace={workspace} forecasts={forecasts}
    details={details} detailsLoading={detailsLoading} detailsError={detailsError}
    busy={busy} predicting={predicting} error={error || forecastError} onReload={reload} onPredict={predictOne} onPredictAll={predictAll} onStopPredictions={stopPredictions} onCreate={createCheck} onUpdate={updateCheck}/>
}

function LiveTable({ page, selectedId, user, workspace, forecasts, details, detailsLoading, detailsError, busy, predicting, error, onReload, onPredict, onPredictAll, onStopPredictions, onCreate, onUpdate }: {
  page: keyof typeof titles; selectedId?: string; user: User; workspace: LiveWorkspaceData; forecasts: Forecasts
  details: LiveSensorDetails | null; detailsLoading: boolean; detailsError: string
  busy: boolean; predicting: number | null; error: string; onReload: () => void; onPredict: (id: number) => Promise<void>; onPredictAll: () => Promise<void>
  onStopPredictions: () => Promise<void>
  onCreate: (sensorId: number, form: FormData) => Promise<void>; onUpdate: (check: LiveCheck, action: "start" | "complete", form?: FormData) => Promise<void>
}) {
  const [query, setQuery] = useState("")
  const [filter, setFilter] = useState("Все")
  const [category, setCategory] = useState("")
  const [sort, setSort] = useState("id")
  const [index, setIndex] = useState(0)
  const [assignOpen, setAssignOpen] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 60000); return () => clearInterval(timer) }, [])
  const predictions = useMemo(() => new Map(forecasts.predictions.map(row => [row.sensor_id, row])), [forecasts.predictions])
  const sensors = useMemo(() => new Map(workspace.sensors.map(row => [row.id, row])), [workspace.sensors])
  const objects = useMemo(() => new Map(workspace.objects.map(row => [row.id, row.name || `Объект №${row.id}`])), [workspace.objects])
  const technician = user.role === "technician"
  const sensorPage = page === "warnings" || page === "map"
  const objectName = (id: number | null) => id === null ? "Объект не указан" : objects.get(id) ?? `Объект №${id}`
  const assigneeName = (id: string) => workspace.assignees.find(row => row.id === id)?.name ?? id
  const active = workspace.checks.filter(row => row.status !== "Завершена")
  const checksBySensor = useMemo(() => new Map(workspace.checks.filter(row => row.status !== "Завершена").map(row => [row.sensor_id, row])), [workspace.checks])
  const job = forecasts.job
  const calculating = job?.status === "running" || job?.status === "stopping"
  const hasPrediction = (id: number) => predictions.get(id)?.status === "ready"
  const match = (...values: unknown[]) => values.join(" ").toLowerCase().includes(query.trim().toLowerCase())
  const visibleSensors = workspace.sensors.filter(sensor => match(sensor.id, sensor.name, sensor.type, objectName(sensor.object_id))
    && (!category || (page === "map" ? String(sensor.object_id) === category : sensor.engineering_system === category))
    && (filter === "Все" || (filter === "Без прогноза" ? !hasPrediction(sensor.id) : filter === "С прогнозом" ? hasPrediction(sensor.id) : checksBySensor.has(sensor.id))))
    .sort((a, b) => sort === "risk" ? (predictions.get(b.id)?.result?.probability ?? -1) - (predictions.get(a.id)?.result?.probability ?? -1) : a.id - b.id)
  const visibleChecks = workspace.checks.filter(check => (page === "archive" ? check.status === "Завершена" : check.status !== "Завершена")
    && match(check.id, check.sensor_id, sensors.get(check.sensor_id)?.name, objectName(sensors.get(check.sensor_id)?.object_id ?? null), check.result)
    && (filter === "Все" || check.status === filter) && (!category || check.assignee_id === category))
  const total = sensorPage ? visibleSensors.length : visibleChecks.length
  const pages = Math.max(1, Math.ceil(total / 100)), currentPage = Math.min(index, pages - 1), start = currentPage * 100
  const check = !sensorPage ? workspace.checks.find(row => String(row.id) === selectedId) : undefined
  const selected = selectedId ? sensors.get(sensorPage ? Number(selectedId) : check?.sensor_id ?? -1) : undefined
  const selectedForecast = selected && (predictions.get(selected.id) ?? details?.prediction ?? undefined)
  const sensorChecks = details?.checks ?? []
  const displayValue = (value: number | string | null) => value === null || value === "" ? "Значение не указано" : String(value)
  const button = (id: number) => <button disabled={busy || calculating} onClick={event => { event.stopPropagation(); void onPredict(id) }}>{predicting === id ? "Расчёт…" : hasPrediction(id) ? "Обновить прогноз" : "Получить прогноз"}</button>
  const open = (id: number) => { setAssignOpen(false); navigate(page, id) }
  return <main className="warnings-page demo-workspace live-workspace"><section className="demo-main">
    <div className="warnings-page-heading"><h1>{technician && page === "checks" ? "Мои проверки" : titles[page]}</h1><p>{subtitles[page]}</p></div>
    {page === "warnings" && <div className="demo-summary">
      <button onClick={() => { setFilter("Все"); setIndex(0) }}><strong>{workspace.sensors.length.toLocaleString("ru-RU")}</strong>Датчиков в базе</button>
      <button onClick={() => { setFilter("С прогнозом"); setIndex(0) }}><strong>{workspace.sensors.filter(row => hasPrediction(row.id)).length.toLocaleString("ru-RU")}</strong>Готовых прогнозов</button>
      <button onClick={() => navigate("checks")}><strong>{active.length}</strong>Текущих проверок</button>
    </div>}
    <div className="demo-action-buttons demo-reload">{page === "warnings" && <><button className="primary" disabled={busy || calculating || !workspace.sensors.length} onClick={() => void onPredictAll()}>{calculating ? "Рассчитываем прогнозы…" : "Рассчитать прогноз всех датчиков"}</button>{calculating && !technician && <button className="live-stop-button" disabled={busy || job?.status === "stopping"} onClick={() => void onStopPredictions()}>{job?.status === "stopping" ? "Останавливаем…" : "Остановить прогноз"}</button>}</>}<button disabled={busy} onClick={onReload}>Обновить данные</button></div>
    {job && <section className="live-progress" aria-live="polite"><strong>{job.status === "running" ? "Расчёт прогноза" : job.status === "stopping" ? "Остановка расчёта" : job.status === "completed" ? "Расчёт завершён" : job.status === "stopped" ? "Расчёт остановлен" : "Расчёт прерван"}: {job.completed.toLocaleString("ru-RU")} из {job.total.toLocaleString("ru-RU")}</strong>
      <progress max={job.total || 1} value={job.completed}/><span>Готово: {job.predicted} · Недостаточно данных: {job.skipped} · Ошибок: {job.failed}</span>
      {job.status === "running" && <span>Можно переходить между разделами и закрывать страницу. Расчёт продолжится на сервере.</span>}{job.status === "stopping" && <span>Новые датчики больше не добавляются. Завершаем уже начатые расчёты.</span>}{job.error && <span role="alert">{job.error}</span>}
    </section>}
    {error && <p className="live-error" role="alert">{error}</p>}
    {page === "map" && <p className="live-map-note">В загруженных таблицах нет географических координат. Ниже — объекты и датчики из базы. Выберите объект, чтобы просмотреть его датчики и назначенные проверки.</p>}
    <div className="demo-tabs">{(sensorPage ? ["Все", "Без прогноза", "С прогнозом", "На проверке"] : page === "archive" ? ["Все"] : ["Все", "Новая", "В работе"]).map(value => <button key={value} aria-pressed={filter === value} onClick={() => { setFilter(value); setIndex(0) }}>{value === "Все" ? "Все записи" : value}</button>)}</div>
    <div className="demo-toolbar"><input aria-label="Поиск" placeholder="Поиск по датчику, объекту или номеру" value={query} onChange={event => { setQuery(event.target.value); setIndex(0) }}/>
      <select aria-label={page === "map" ? "Объект" : sensorPage ? "Система" : "Исполнитель"} value={category} onChange={event => { setCategory(event.target.value); setIndex(0) }}><option value="">{page === "map" ? "Все объекты" : sensorPage ? "Все системы" : "Все исполнители"}</option>
        {page === "map" ? workspace.objects.map(obj => <option key={obj.id} value={obj.id}>{objectName(obj.id)}</option>) : sensorPage ? [...new Set(workspace.sensors.map(row => row.engineering_system).filter(Boolean))].map(name => <option key={name!}>{name}</option>) : workspace.assignees.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}
      </select>
      {sensorPage && <select aria-label="Сортировка" value={sort} onChange={event => { setSort(event.target.value); setIndex(0) }}><option value="id">По номеру датчика</option><option value="risk">По вероятности</option></select>}
      <button onClick={() => { setQuery(""); setCategory(""); setFilter("Все"); setSort("id"); setIndex(0) }}>Сбросить фильтры</button>
    </div>
    <div className="demo-table-scroll" tabIndex={0} aria-label="Список записей"><table className="demo-table"><thead><tr>{(sensorPage ? ["Датчик", "Место", "Показание", "Вероятность", "Статус", "Прогноз"] : ["Проверка / датчик", "Место", "Исполнитель", page === "archive" ? "Завершена" : "Срок", page === "archive" ? "Результат" : "Статус"]).map(title => <th key={title}>{title}</th>)}</tr></thead><tbody>
      {sensorPage ? visibleSensors.slice(start, start + 100).map(sensor => { const forecast = predictions.get(sensor.id), inspection = checksBySensor.get(sensor.id); return <tr key={sensor.id} className={`live-sensor-row${selected?.id === sensor.id ? " is-selected" : ""}`} tabIndex={0} aria-label={`Открыть карточку датчика ${sensor.name}`} onClick={() => open(sensor.id)} onKeyDown={event => { if (event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); open(sensor.id) } }}>
        <td><button className="demo-link" onClick={event => { event.stopPropagation(); open(sensor.id) }}>{sensor.name}</button><small>№{sensor.id} · {sensor.type}</small></td><td>{objectName(sensor.object_id)}<small>{sensor.engineering_system}</small></td><td>{sensor.value ?? "Нет показаний"}<small>{sensor.occurred_at ? formatDate(sensor.occurred_at) : "Нет истории событий"}</small></td>
        <td>{forecast?.result ? <>{percent(forecast.result.probability)}<small>Горизонт: {forecast.result.horizon_hours} ч.</small></> : "—"}</td>
        <td>{inspection ? <button className="demo-link" onClick={event => { event.stopPropagation(); navigate("checks", inspection.id) }}>На проверке</button> : <span className={`demo-badge ${forecast?.status === "error" ? "is-confirmed" : ""}`}>{forecast?.status === "ready" ? "Прогноз готов" : forecast?.status === "skipped" ? "Нет данных для прогноза" : forecast?.status === "error" ? "Ошибка прогноза" : "Без прогноза"}</span>}</td><td>{button(sensor.id)}</td>
      </tr> }) : visibleChecks.slice(start, start + 100).map(row => <tr key={row.id} className={check?.id === row.id ? "is-selected" : undefined}><td><button className="demo-link" onClick={() => open(row.id)}>Проверка №{row.id}</button><small>{sensors.get(row.sensor_id)?.name} · датчик №{row.sensor_id}</small></td><td>{objectName(sensors.get(row.sensor_id)?.object_id ?? null)}</td><td>{assigneeName(row.assignee_id)}</td><td>{formatDate((page === "archive" ? row.completed_at : row.deadline) ?? undefined)}</td><td><span className="demo-badge">{page === "archive" && row.outcome ? outcomes[row.outcome] : row.status}</span>{page !== "archive" && Date.parse(row.deadline) < now && <small className="status-error">Просрочена</small>}</td></tr>)}
    </tbody></table>{!total && <div className="demo-no-results"><h3>{page === "archive" ? "Архив пока пуст" : page === "checks" ? "Проверок пока нет" : "Датчики не найдены"}</h3><p>{page === "checks" ? technician ? "Здесь появятся назначенные вам проверки." : "Выберите датчик на главной и назначьте проверку." : page === "archive" ? "Здесь появятся завершённые проверки с отчётами." : "Измените фильтры или выберите другой объект."}</p></div>}</div>
    <div className="live-pagination"><span>Показано: {total ? start + 1 : 0}–{Math.min(start + 100, total)} из {total.toLocaleString("ru-RU")}</span><button disabled={currentPage === 0} onClick={() => setIndex(currentPage - 1)}>Назад</button><span>{currentPage + 1} / {pages}</span><button disabled={currentPage + 1 >= pages} onClick={() => setIndex(currentPage + 1)}>Далее</button></div>
    {page === "warnings" && <p className="demo-note">Прогноз рассчитывается на момент последнего события датчика в загруженной базе. Вероятность события не подтверждает неисправность оборудования.</p>}
  </section>
  {selectedId && <DetailPanel recordKey={`${page}/${selectedId}`} onClose={() => navigate(page)}>{detailsLoading ? <div className="live-details-loading" role="status"><span className="workspace-spinner"/><p>Загружаем карточку датчика…</p></div> : detailsError ? <><h2>Не удалось открыть датчик</h2><p role="alert">{detailsError}</p><button onClick={onReload}>Повторить</button></> : !selected || !details ? <><h2>Запись не найдена</h2><p>Выберите запись из списка.</p></> : <>
    <small>{check ? `ПРОВЕРКА №${check.id} · ДАТЧИК №${selected.id}` : `ДАТЧИК №${selected.id}`}</small><h2>{selected.name}</h2>
    <span className={`demo-badge ${selectedForecast?.status === "error" ? "is-confirmed" : ""}`}>{check?.status ?? (selectedForecast?.status === "ready" ? "Прогноз готов" : selectedForecast?.status === "skipped" ? "Недостаточно данных для прогноза" : "Прогноз не рассчитан")}</span>
    <p><strong>{details.object?.name ?? objectName(selected.object_id)}</strong><br/>{selected.engineering_system}</p>
    <h3>Прогноз</h3>{selectedForecast?.result ? <div className="demo-probability"><strong>{percent(selectedForecast.result.probability)}</strong><span>вероятность события<br/>Горизонт: {selectedForecast.result.horizon_hours} ч.</span><small>Модель: {selectedForecast.result.model_version}<br/>Рассчитан: {formatDate(selectedForecast.updated_at)}</small></div> : <p>{selectedForecast?.error ?? "Для этого датчика прогноз ещё не рассчитывался."}</p>}{!technician && <div className="demo-action-buttons demo-reload">{button(selected.id)}</div>}
    <h3>Текущие показатели</h3><dl><div><dt>Тип датчика</dt><dd>{selected.type}</dd></div>{details.object?.type && <div><dt>Вид объекта</dt><dd>{details.object.type}</dd></div>}<div><dt>Последнее значение</dt><dd>{displayValue(selected.value)}</dd></div><div><dt>Тип значения</dt><dd>{valueType(selected.value_type)}</dd></div><div><dt>Последнее событие</dt><dd>{selected.occurred_at ? formatDate(selected.occurred_at) : "В БД нет событий"}</dd></div></dl>
    <h3>Последние события</h3>{details.events.length ? <ol className="live-sensor-events">{details.events.map(event => <li key={event.id}><time>{formatDate(event.occurred_at)}</time><strong>{displayValue(event.value)}</strong><span>{valueType(event.value_type)}{alarmType(event.alarm)}</span></li>)}</ol> : <p>В загруженной БД нет событий этого датчика.</p>}
    {!check && !technician && <section className="demo-actions"><h3>Решение по датчику</h3>{checksBySensor.has(selected.id) ? <button onClick={() => navigate("checks", checksBySensor.get(selected.id)!.id)}>Открыть назначенную проверку</button> : <><button disabled={busy} onClick={() => setAssignOpen(value => !value)}>Назначить проверку</button>{assignOpen && <form className="demo-form" onSubmit={event => { event.preventDefault(); void onCreate(selected.id, new FormData(event.currentTarget)) }}><label>Исполнитель<select name="assignee" required>{workspace.assignees.map(person => <option value={person.id} key={person.id}>{person.name}</option>)}</select></label><label>Срок завершения<input name="deadline" type="datetime-local" required/></label><button className="primary" disabled={busy}>Назначить</button></form>}</>}</section>}
    {check && <section className="demo-actions"><h3>Проверка №{check.id}</h3><span className="demo-badge">{check.status}</span><dl><div><dt>Исполнитель</dt><dd>{assigneeName(check.assignee_id)}</dd></div><div><dt>Создана</dt><dd>{formatDate(check.created_at)}</dd></div><div><dt>Срок</dt><dd>{formatDate(check.deadline)}</dd></div></dl>
      {check.work_description && <><h3>Выполненные работы</h3><p className="demo-preserve">{check.work_description}</p></>}{check.result && <><h3>Результат</h3><strong>{check.outcome && outcomes[check.outcome]}</strong><p className="demo-preserve">{check.result}</p>{check.completed_at && <p>Завершена: {formatDate(check.completed_at)}</p>}</>}
      {user.id === check.assignee_id && check.status === "Новая" && <button className="primary" disabled={busy} onClick={() => void onUpdate(check, "start")}>Начать проверку</button>}
      {user.id === check.assignee_id && check.status === "В работе" && <form key={check.id} className="demo-form" onSubmit={event => { event.preventDefault(); void onUpdate(check, "complete", new FormData(event.currentTarget)) }}><h3>Отчёт о проверке</h3><label>Выполненные работы<textarea name="work" required maxLength={10000} defaultValue={check.work_description ?? ""}/></label><label>Заключение<textarea name="result" required maxLength={10000} defaultValue={check.result ?? ""}/></label><label>Результат<select name="outcome" defaultValue={check.outcome ?? "clear"}>{Object.entries(outcomes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label><p className="demo-note">Если неисправность не устранена, проверка останется в работе.</p><button className="primary" disabled={busy}>Сохранить отчёт</button></form>}
    </section>}
    <h3>Связанные проверки</h3>{sensorChecks.length ? sensorChecks.map(related => <p key={related.id}><button className="demo-link" onClick={() => navigate(related.status === "Завершена" ? "archive" : "checks", related.id)}>№{related.id} · {related.status}</button><br/><span className="demo-note">{details.employees[related.assignee_id] ?? related.assignee_id} · срок {formatDate(related.deadline)}</span></p>) : <p>Проверки для датчика не назначались.</p>}
    <h3>История действий</h3>{details.history.length ? <ol className="demo-history">{details.history.map(entry => <li key={entry.id}><time>{formatDate(entry.created_at)}</time><strong>{details.employees[entry.actor_id] ?? entry.actor_id}</strong><p>{entry.action}</p></li>)}</ol> : <p>Действий по этому датчику ещё не было.</p>}
  </>}</DetailPanel>}
  </main>
}
