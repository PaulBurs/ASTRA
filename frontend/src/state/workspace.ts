import { demoData, type DemoData, type DemoCheck, type Section } from "../data/demo.ts"

export const assignees = ["Алексей К.", "Дмитрий П."] as const
export const outcomes = { clear: "Неисправность не обнаружена", fixed: "Неисправность устранена", unresolved: "Неисправность не устранена" } as const
export interface HistoryEntry {
  id: string; at: string; actor: string; action: string; objectId: number; warningId?: number; checkId?: number
}
export interface Filters { query: string; filter: string; category: string; sort: string; period?: string; from?: string; to?: string }
export interface Workspace {
  version: 2
  revision: number
  assignees: string[]
  data: DemoData
  history: HistoryEntry[]
  preferences: { mode: "demo" | "empty"; filters: Partial<Record<Section, Filters>> }
}
export const defaultFilters: Filters = { query: "", filter: "Все", category: "Все", sort: "newest", period: "Все" }
export const isOpenWarning = (status: string) => status === "Новое" || status === "На проверке"
export const isArchived = (check: DemoCheck) => check.status === "Завершена" && !!check.result?.trim()
export const isOverdue = (check: DemoCheck, now = new Date()) => check.status !== "Завершена" && new Date(check.deadline) < now
export function formatDate(value?: string) {
  if (!value) return "Не указано"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
}

// v1 work orders become tasks in the same check record; original titles stay in history.
export function mergeLegacyData(data: DemoData, history: HistoryEntry[], now: Date) {
  for (const c of data.checks) {
    const status = c.status as string
    c.status = status === "Новое" ? "Новая" : status === "Принято" ? "В работе" : c.status
    c.plannedAt ??= new Date(new Date(c.deadline).getTime() - 3600000).toISOString()
    if (c.status === "Завершена") {
      if (!c.result?.trim()) { c.status = "В работе"; continue }
      c.outcome ??= data.warnings.find(w => w.id === c.warningId)?.status === "Подтверждено" ? "unresolved" : "clear"
      c.workDescription ??= "Работы не требовались; выполнен осмотр."
      c.completedAt ??= c.deadline
    }
  }
  for (const order of data.workOrders) {
    let check = data.checks.find(c => order.warningId !== undefined && c.warningId === order.warningId && c.status !== "Завершена")
    if (!check) {
      check = { id: Math.max(0, ...data.checks.map(c => c.id)) + 1, objectId: order.objectId, warningId: order.warningId,
        title: order.title, assignee: assignees[0], plannedAt: now.toISOString(), deadline: new Date(now.getTime()+86400000).toISOString(), status: order.status === "В работе" ? "В работе" : "Новая" }
      data.checks.push(check)
      const warning = data.warnings.find(w => w.id === order.warningId)
      if (warning) warning.status = "На проверке"
    }
    check.workDescription = [check.workDescription, order.title].filter(Boolean).join("\n")
    history.push({ id: `legacy-${order.id}`, at: now.toISOString(), actor: "ASTRA · перенос демо", objectId: order.objectId, warningId: order.warningId, checkId: check.id,
      action: `Заявка ${order.id} объединена с проверкой: ${order.title}. Прежний статус: ${order.status}. ${order.status === "Завершена" ? "Итоговый отчёт отсутствует — требуется проверка и отчёт перед архивированием." : ""}` })
  }
  data.workOrders = []
}
export function createWorkspace(now = new Date()): Workspace {
  const data = structuredClone(demoData)
  // Relative dates keep the demonstration useful when opened on another day.
  data.checks.forEach((c, i) => {
    c.deadline = new Date(now.getTime() + (c.status === "Завершена" ? -24 : i === 0 ? -1 : i + 1) * 3600000).toISOString()
  })
  const history: HistoryEntry[] = data.warnings.map(w => ({ id: `warning-${w.id}`, at: new Date(now.getTime()-7200000).toISOString(), actor: "ASTRA · демо", objectId: w.objectId, warningId: w.id, action: `Получено предупреждение №${w.id}.` }))
  mergeLegacyData(data, history, now)
  for (const c of data.checks) history.push({ id: `check-${c.id}`, at: c.completedAt ?? now.toISOString(), actor: c.assignee, objectId: c.objectId, warningId: c.warningId, checkId: c.id, action: `Проверка №${c.id}: ${c.status}.${c.result ? " Отчёт: " + c.result : ""}` })
  return { version: 2, revision: 0, assignees: [...assignees], data, history, preferences: { mode: "demo", filters: {} } }
}
export type DemoAction =
  | { type: "assign"; warningId?: number; objectId?: number; title: string; assignee: string; plannedAt: string; deadline: string }
  | { type: "falseAlarm"; warningId: number; reason: string }
  | { type: "advance"; checkId: number }
  | { type: "planWork"; checkId: number; workDescription: string; assignee: string; deadline: string }
  | { type: "result"; checkId: number; outcome: keyof typeof outcomes; result: string; workDescription: string }

export function applyAction(current: Workspace, action: DemoAction, now = new Date()): Workspace {
  const next = structuredClone(current)
  const { data } = next
  const event = (record: Omit<HistoryEntry, "id" | "at">) => next.history.push({ ...record, id: `${now.getTime()}-${next.history.length}`, at: now.toISOString() })
  const future = (value: string) => { const date = new Date(value); if (!Number.isFinite(date.getTime()) || date <= now) throw new Error("Срок завершения должен быть в будущем."); return date.toISOString() }
  const validAssignee = (value: string) => { if (!current.assignees.includes(value)) throw new Error("Выберите исполнителя.") }
  if (action.type === "assign" || action.type === "falseAlarm") {
    const warning = data.warnings.find(w => w.id === action.warningId)
    if (action.warningId !== undefined && !warning) throw new Error("Предупреждение не найдено.")
    if (warning && (!isOpenWarning(warning.status) || data.checks.some(c => c.warningId === warning.id && !isArchived(c)))) throw new Error("Предупреждение закрыто или проверка уже назначена.")
    if (action.type === "falseAlarm") {
      if (!warning || !action.reason.trim()) throw new Error("Укажите причину решения.")
      warning.status = "Ложная тревога"
      event({ objectId: warning.objectId, warningId: warning.id, actor: "Егор В.", action: `Ложная тревога. Причина: ${action.reason.trim()}` })
    } else {
      const objectId = warning?.objectId ?? action.objectId
      if (!data.objects.some(o => o.id === objectId) || !action.title.trim()) throw new Error("Укажите место и задачу проверки.")
      validAssignee(action.assignee)
      const deadline = future(action.deadline)
      const planned = new Date(action.plannedAt)
      if (!Number.isFinite(planned.getTime()) || planned < new Date(now.getTime()-60000) || planned >= new Date(deadline)) throw new Error("Начало должно быть не раньше текущего времени и раньше срока завершения.")
      const id = Math.max(0, ...data.checks.map(c => c.id)) + 1
      data.checks.push({ id, objectId: objectId!, warningId: warning?.id, title: action.title.trim(), assignee: action.assignee, plannedAt: planned.toISOString(), deadline, status: "Новая" })
      if (warning) warning.status = "На проверке"
      event({ objectId: objectId!, warningId: warning?.id, checkId: id, actor: "Егор В.", action: `Назначена проверка №${id}: ${action.title.trim()}. Исполнитель: ${action.assignee} Начало: ${formatDate(planned.toISOString())}. Срок: ${formatDate(deadline)}.` })
    }
  } else {
    const check = data.checks.find(c => c.id === action.checkId)
    if (!check) throw new Error("Проверка не найдена.")
    const warning = data.warnings.find(w => w.id === check.warningId)
    const base = { objectId: check.objectId, warningId: check.warningId, checkId: check.id, actor: check.assignee }
    if (action.type === "advance") {
      if (check.status !== "Новая") throw new Error("Начать можно только новую проверку.")
      check.status = "В работе"
      event({ ...base, action: "Проверка начата. Статус: В работе." })
    } else if (action.type === "planWork") {
      if (check.status !== "В работе") throw new Error("Сначала начните проверку.")
      if (!action.workDescription.trim()) throw new Error("Опишите необходимые работы.")
      validAssignee(action.assignee)
      const deadline = future(action.deadline)
      if (check.plannedAt && new Date(deadline) <= new Date(check.plannedAt)) throw new Error("Срок завершения должен быть позже планового начала.")
      check.deadline = deadline
      check.assignee = action.assignee
      check.workDescription = action.workDescription.trim()
      event({ ...base, actor: "Егор В.", action: `План работ: ${check.workDescription}
Исполнитель: ${check.assignee} Срок: ${formatDate(check.deadline)}.` })
    } else {
      if (check.status !== "В работе") throw new Error("Перед завершением начните проверку.")
      if (!action.result.trim() || !action.workDescription.trim() || !(action.outcome in outcomes)) throw new Error("Заполните итог, отчёт и выполненные работы (или укажите, что работы не требовались).")
      check.status = "Завершена"
      check.result = action.result.trim()
      check.workDescription = action.workDescription.trim()
      check.outcome = action.outcome
      check.completedAt = now.toISOString()
      if (warning) warning.status = action.outcome === "clear" ? "Ложная тревога" : "Подтверждено"
      event({ ...base, action: `Проверка завершена и перемещена в архив. ${outcomes[action.outcome]}. Отчёт: ${check.result}
Работы: ${check.workDescription}` })
    }
  }
  return next
}
