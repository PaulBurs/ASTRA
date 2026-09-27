import { useEffect, useRef, useState, type ReactNode } from "react"
import { defaultFilters, formatDate, isArchived, isOverdue, outcomes, type DemoAction, type Filters, type Workspace } from "../state/workspace"
import { navigate, routeHref } from "../state/navigation"
import { AssignForm, CheckActions, WarningActions } from "./DemoActions"
import type { Notice } from "./WorkspaceFeedback"
import type { DemoCheck, Section } from "../state/models"
import "./DemoWorkspace.css"

const titles: Record<Section, string> = { warnings: "Главная", map: "Карта", checks: "Проверки", archive: "Архив" }
const subtitles: Record<Section, string> = { warnings: "Новые предупреждения и решения диспетчера", map: "Текущие проверки: место и расписание", checks: "Обследование и необходимые работы в одной карточке", archive: "Завершённые проверки и итоговые отчёты" }
function inPeriod(c: DemoCheck, period: string) {
  const now = new Date(), start = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const date = new Date(c.plannedAt ?? c.deadline)
  if (period === "Просроченные") return isOverdue(c)
  if (period === "Все") return true
  const from = new Date(start); const to = new Date(start)
  if (period === "Завтра") from.setDate(from.getDate()+1)
  to.setDate(to.getDate() + (period === "Неделя" ? 7 : period === "Завтра" ? 2 : 1))
  return date >= from && date < to
}
export function DemoWorkspace({ page, selectedId, workspace, preferences, act, busy, notify, onOpenJournal, onReload }: {
  page: Section; selectedId?: string; workspace: Workspace; busy: boolean
  preferences: (value: Workspace["preferences"]) => Promise<void>
  act: (action: DemoAction) => Promise<void>
  notify: (message: string, type?: Notice["type"]) => void
  onOpenJournal: () => void; onReload: () => void
}) {
  const data = workspace.data
  const saved = workspace.preferences.filters[page] ?? defaultFilters
  const filters = saved
  const [queryDraft, setQueryDraft] = useState(saved.query)
  const [, tick] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => tick(v => v + 1), 60000); return () => window.clearInterval(timer) }, [])
  const [creating, setCreating] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const drag = useRef<{ x: number; y: number; startX: number; startY: number } | null>(null)
  const detail = useRef<HTMLElement>(null)
  useEffect(() => { if (selectedId && page !== "map") detail.current?.focus() }, [selectedId, page])
  const update = async (patch: Partial<Filters>) => {
    const next = { ...filters, ...patch }
    try { await preferences({ ...workspace.preferences, filters: { ...workspace.preferences.filters, [page]: next } }) }
    catch (e) { notify((e as Error).message, "error") }
  }
  const openFiltered = async (target: Section, patch: Partial<Filters>) => {
    try { await preferences({ ...workspace.preferences, filters: { ...workspace.preferences.filters, [target]: { ...defaultFilters, ...patch } } }); navigate(target) }
    catch (e) { notify((e as Error).message, "error") }
  }
  const object = (id: number) => data.objects.find(o => o.id === id)!
  const matches = (...values: unknown[]) => values.join(" ").toLowerCase().includes(filters.query.trim().toLowerCase())
  const active = data.checks.filter(c => !isArchived(c)), archived = data.checks.filter(isArchived)
  const checkPage = (c: DemoCheck): Section => isArchived(c) ? "archive" : "checks"
  const link = (target: Section, id: number | undefined, label: string) => <a className="demo-link" href={routeHref(target, id)} onClick={e => { e.stopPropagation(); if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return; e.preventDefault(); navigate(target, id) }}>{label}</a>
  const badge = (status: string) => <span className={`demo-badge ${status === "Ложная тревога" ? "is-dismissed" : ""}`}>{status}</span>
  const overdue = (c: DemoCheck) => isOverdue(c) && <span className="demo-badge is-confirmed">Просрочена</span>
  const visibleWarnings = data.warnings.filter(w => matches(w.id, w.title, object(w.objectId).name) && (filters.filter === "Все" || filters.filter === w.status) && (filters.category === "Все" || filters.category === object(w.objectId).system)).sort((a,b) => filters.sort === "risk" ? b.probability-a.probability : a.minutesOpen-b.minutesOpen)
  const visibleChecks = (page === "archive" ? archived : active).filter(c => matches(c.id, c.title, object(c.objectId).name, c.workDescription) && (filters.filter === "Все" || filters.filter === c.status) && (filters.category === "Все" || filters.category === c.assignee) && (page === "archive" ? (!filters.from || (c.completedAt ?? "") >= new Date(filters.from).toISOString()) && (!filters.to || new Date(c.completedAt ?? 0) < new Date(new Date(filters.to).getTime()+86400000)) && (filters.period === "Все" || !filters.period || c.outcome === filters.period) : inPeriod(c, filters.period ?? "Все"))).sort((a,b) => page === "archive" ? (b.completedAt ?? "").localeCompare(a.completedAt ?? "") : a.deadline.localeCompare(b.deadline))
  const warning = page === "warnings" ? data.warnings.find(w => String(w.id) === selectedId) : undefined
  const check = page !== "warnings" ? (page === "archive" ? archived : active).find(c => String(c.id) === selectedId) : undefined
  const moved = selectedId && !check && page !== "warnings" ? data.checks.find(c => String(c.id) === selectedId) : undefined
  const selectedObject = warning ? object(warning.objectId) : check ? object(check.objectId) : undefined
  const history = workspace.history.filter(h => warning ? h.warningId === warning.id : check ? h.checkId === check.id : false).sort((a,b) => b.at.localeCompare(a.at))
  const headings = page === "warnings" ? ["Предупреждение", "Место", "Вероятность", "Статус"] : ["Проверка / задача", "Место", "Исполнитель", page === "archive" ? "Завершена" : "Начало / срок", page === "archive" ? "Результат" : "Статус"]
  const rows: { id: number; cells: ReactNode[] }[] = page === "warnings" ? visibleWarnings.map(w => ({ id: w.id, cells: [<>{link("warnings", w.id, w.title)}<small>№{w.id} · {w.minutesOpen} мин назад</small></>, object(w.objectId).name, `${w.probability}%`, badge(w.status)] })) : visibleChecks.map(c => ({ id: c.id, cells: [<>{link(page, c.id, c.title)}<small>№{c.id}</small></>, object(c.objectId).name, c.assignee, page === "archive" ? formatDate(c.completedAt) : <>{formatDate(c.plannedAt)}<small>До {formatDate(c.deadline)}</small></>, page === "archive" ? <span key="outcome" className={c.outcome === "unresolved" ? "demo-unresolved" : ""}>{c.outcome ? outcomes[c.outcome] : "—"}</span> : <div key="status" className="demo-statuses">{badge(c.status)}{overdue(c)}</div>] }))
  return <main className="warnings-page demo-workspace"><section className="demo-main">
    <div className="warnings-page-heading"><h1>{titles[page]}</h1><p>{subtitles[page]}</p></div>
    {page === "warnings" && <div className="demo-summary"><button onClick={() => void update({ filter: "Новое" })}><strong>{data.warnings.filter(w => w.status === "Новое").length}</strong>Новых предупреждений</button><button disabled={busy} onClick={() => void openFiltered("checks", { filter: "Все" })}><strong>{active.length}</strong>Текущих проверок</button><button disabled={busy} onClick={() => void openFiltered("map", { period: "Просроченные" })}><strong>{active.filter(c => isOverdue(c)).length}</strong>Просроченных проверок</button></div>}
    <div className="demo-action-buttons demo-reload"><button disabled={busy} onClick={onReload}>Перезагрузить данные</button>{page === "checks" && <button className="primary" disabled={busy} onClick={() => setCreating(!creating)}>Новая проверка</button>}</div>
    {creating && <AssignForm workspace={workspace} act={act} busy={busy} notify={notify} onCancel={() => setCreating(false)} />}
    <div className="demo-tabs">{(page === "warnings" ? ["Все", "Новое", "На проверке", "Ложная тревога", "Подтверждено"] : page === "archive" ? ["Все"] : ["Все", "Новая", "В работе"]).map(status => <button key={status} disabled={busy} aria-pressed={filters.filter === status} onClick={() => void update({ filter: status })}>{status === "Все" ? "Все записи" : status}</button>)}</div>
    <form className="demo-toolbar" onSubmit={e => { e.preventDefault(); void update({ query: String(new FormData(e.currentTarget).get("query") ?? "") }) }}>
      <input name="query" aria-label="Поиск" placeholder="Поиск по задаче, месту или номеру" value={queryDraft} onChange={e => setQueryDraft(e.target.value)} /><button disabled={busy} type="submit">Найти</button>
      <select disabled={busy} aria-label={page === "warnings" ? "Система" : "Исполнитель"} value={filters.category} onChange={e => void update({ category: e.target.value })}><option value="Все">{page === "warnings" ? "Все системы" : "Все исполнители"}</option>{(page === "warnings" ? [...new Set(data.objects.map(o => o.system))] : [...new Set(data.checks.map(c => c.assignee))]).map(v => <option key={v}>{v}</option>)}</select>
      {page === "warnings" ? <select disabled={busy} aria-label="Сортировка" value={filters.sort} onChange={e => void update({ sort: e.target.value })}><option value="newest">Сначала новые</option><option value="risk">По вероятности</option></select> : page === "archive" ? <><select aria-label="Результат проверки" value={filters.period ?? "Все"} onChange={e => void update({ period: e.target.value })}><option value="Все">Все результаты</option>{Object.entries(outcomes).map(([key,value]) => <option key={key} value={key}>{value}</option>)}</select><label>С<input aria-label="Архив с даты" type="date" value={filters.from ?? ""} onChange={e => void update({ from: e.target.value })} /></label><label>По<input aria-label="Архив по дату" type="date" value={filters.to ?? ""} onChange={e => void update({ to: e.target.value })} /></label></> : <select disabled={busy} aria-label="Период" value={filters.period ?? "Все"} onChange={e => void update({ period: e.target.value })}>{["Все", "Сегодня", "Завтра", "Неделя", "Просроченные"].map(v => <option key={v}>{v}</option>)}</select>}
      <button disabled={busy} type="button" onClick={() => { setQueryDraft(""); void update(defaultFilters) }}>Сбросить фильтры</button>
    </form>
    <div className={page === "map" ? "demo-map-layout" : undefined}>
    {page === "map" && <section className="demo-map-panel"><p className="demo-note">Интерактивная демосхема · условные координаты. Синий — новая, зелёный — в работе, красный — просрочена. Выберите метку или строку списка.</p><div className="demo-action-buttons"><button onClick={() => setZoom(z => Math.min(3,z+.25))} aria-label="Увеличить карту">+</button><button onClick={() => setZoom(z => Math.max(1,z-.25))} aria-label="Уменьшить карту">−</button><button onClick={() => { setZoom(1); setPan({x:0,y:0}) }}>Показать все</button></div>
      <div className="demo-map" aria-label="Карта текущих проверок" onPointerDown={e => { if ((e.target as HTMLElement).closest("button")) return; drag.current={x:e.clientX,y:e.clientY,startX:pan.x,startY:pan.y}; e.currentTarget.setPointerCapture(e.pointerId) }} onPointerMove={e => { if (drag.current) setPan({x:drag.current.startX+e.clientX-drag.current.x,y:drag.current.startY+e.clientY-drag.current.y}) }} onPointerUp={() => { drag.current=null }} onPointerCancel={() => { drag.current=null }}>
        <div className="demo-map-layer" style={{transform:`translate(${pan.x}px, ${pan.y}px) scale(${zoom})`}}><svg viewBox="0 0 100 100" preserveAspectRatio="none"><path d="M0 20L100 80M0 75L100 25M30 0L60 100" /></svg>{visibleChecks.map(c => { const o=object(c.objectId); const siblings=visibleChecks.filter(v=>v.objectId===c.objectId); const offset=siblings.findIndex(v=>v.id===c.id)*5; return <button key={c.id} className={`demo-marker ${isOverdue(c)?"late":c.status==="В работе"?"working":"new"} ${selectedId===String(c.id)?"selected":""}`} style={{left:`${o.position[0]+offset}%`,top:`${o.position[1]}%`}} aria-label={`Проверка ${c.id}, ${o.name}, ${c.status}`} aria-pressed={selectedId===String(c.id)} title={`${o.name} · ${formatDate(c.plannedAt)}`} onClick={() => navigate("map",c.id)}>{c.id}</button> })}</div>
        {!visibleChecks.length && <p className="demo-map-empty">Проверок по выбранным условиям нет</p>}
      </div></section>}
    <div className="demo-table-scroll" tabIndex={0} aria-label="Список записей"><table className="demo-table"><thead><tr>{headings.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.id} tabIndex={0} aria-label={`Открыть запись ${row.id}`} aria-selected={selectedId === String(row.id)} className={selectedId === String(row.id) ? "is-selected" : undefined} onClick={() => navigate(page,row.id)} onKeyDown={e => { if (e.target !== e.currentTarget) return; if (e.key === "Enter" || e.key === " ") {e.preventDefault();navigate(page,row.id)} }}>{row.cells.map((cell,i)=><td key={i}>{cell}</td>)}</tr>)}</tbody></table>{!rows.length && <div className="demo-no-results"><h3>{page === "archive" ? "Нет завершённых проверок по выбранным условиям" : "Записей не найдено"}</h3><p>Измените фильтры или создайте проверку из нового предупреждения.</p></div>}</div>
    </div>
    <p className="demo-note">Показано записей: {rows.length}</p>{page === "warnings" && <><p className="demo-note">Вероятность прогноза не подтверждает неисправность оборудования.</p><button onClick={onOpenJournal}>Открыть журнал прогнозов</button></>}
  </section>
  {selectedId && <aside ref={detail} tabIndex={-1} className="demo-details" aria-label="Карточка записи"><button onClick={() => navigate(page)}>Закрыть карточку ×</button>{!warning && !check ? <><h2>{moved ? "Проверка перемещена" : "Запись не найдена"}</h2>{moved ? link(checkPage(moved),moved.id,isArchived(moved)?"Открыть в архиве":"Открыть проверку") : <p>Проверьте адрес или выберите запись из списка.</p>}</> : <>
    <small>{warning ? "ПРЕДУПРЕЖДЕНИЕ" : "ПРОВЕРКА"} №{warning?.id ?? check?.id}</small><h2>{warning?.title ?? check?.title}</h2>{badge(warning?.status ?? check!.status)} {check && overdue(check)}<p><strong>{selectedObject?.name}</strong><br/>{selectedObject?.system}</p>
    {warning && <><div className="demo-probability"><strong>{warning.probability}%</strong><span>вероятность события</span></div><h3>Текущие показатели</h3><dl>{selectedObject?.channels.map(c=><div key={c.name}><dt>{c.name}</dt><dd>{c.value}</dd></div>)}</dl><p className="demo-note">Демонстрационные показатели. Обоснование прогноза будет поступать с сервера.</p><WarningActions key={warning.id} warning={warning} workspace={workspace} act={act} busy={busy} notify={notify}/><h3>Связанные проверки</h3>{data.checks.filter(c=>c.warningId===warning.id).map(c=><p key={c.id}>{link(checkPage(c),c.id,`№${c.id} · ${c.title}`)}<br/>{c.status}</p>)}</>}
    {check && <><dl><div><dt>Исполнитель</dt><dd>{check.assignee}</dd></div><div><dt>Плановое начало</dt><dd>{formatDate(check.plannedAt)}</dd></div><div><dt>Срок завершения</dt><dd>{formatDate(check.deadline)}</dd></div></dl><p>{check.warningId ? link("warnings",check.warningId,`Исходное предупреждение №${check.warningId}`) : "Создана вручную"}</p>{page === "map" && <p>{link("checks",check.id,"Открыть полную карточку проверки")}</p>}
      {check.workDescription && <><h3>{isArchived(check)?"Выполненные работы":"План работ"}</h3><p className="demo-preserve">{check.workDescription}</p></>}
      {isArchived(check) && <><h3>Итоговый отчёт</h3><strong className={check.outcome==="unresolved"?"demo-unresolved":""}>{check.outcome && outcomes[check.outcome]}</strong><p className="demo-preserve">{check.result}</p><p>Завершена: {formatDate(check.completedAt)}</p></>}
      <CheckActions assignees={workspace.assignees} key={check.id} check={check} act={act} busy={busy} notify={notify}/>
    </>}
    <h3>История действий</h3><ol className="demo-history">{history.map(h=><li key={h.id}><time>{formatDate(h.at)}</time><strong>{h.actor}</strong><p>{h.action}</p></li>)}</ol>
  </>}</aside>}
  </main>
}
