import { demoUsers, type User } from "./auth.ts"
import { reopenUnresolved, assignees, applyAction, mergeLegacyData, createWorkspace, type DemoAction, type Workspace } from "../state/workspace.ts"

export const WORKSPACE_KEY = "astra.demo.workspace.v2"
type StorageAccess = Pick<Storage, "getItem" | "setItem">
const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value)
const string = (value: unknown) => typeof value === "string"
const number = (value: unknown) => typeof value === "number" && Number.isFinite(value)
const id = (value: unknown) => number(value) && Number.isInteger(value) && (value as number) > 0
const arrayOf = (value: unknown, test: (row: Record<string, unknown>) => boolean) => Array.isArray(value) && value.every((row) => record(row) && test(row))

export function validateWorkspace(value: unknown): value is Workspace {
  if (!record(value) || value.version !== 2 || !number(value.revision) || !record(value.data) || !record(value.preferences)) return false
  if (!Array.isArray(value.assignees) || !value.assignees.length || !value.assignees.every(string)) return false
  const d = value.data
  if (!arrayOf(d.objects, (o) => id(o.id) && string(o.name) && string(o.system) && string(o.updated) && Array.isArray(o.position) && o.position.length === 2 && o.position.every(number) && arrayOf(o.channels, (c) => string(c.name) && string(c.value)))) return false
  if (!arrayOf(d.warnings, (w) => id(w.id) && id(w.objectId) && string(w.title) && number(w.probability) && number(w.minutesOpen) && ["Новое", "На проверке", "Ложная тревога", "Подтверждено"].includes(String(w.status)))) return false
  if (!arrayOf(d.checks, (c) => id(c.id) && id(c.objectId) && (c.warningId === undefined || id(c.warningId)) && string(c.title) && string(c.assignee) && string(c.deadline) && ["Новая", "В работе", "Завершена"].includes(String(c.status)) && (c.result === undefined || string(c.result)) && string(c.plannedAt) && Number.isFinite(Date.parse(String(c.plannedAt))) && Number.isFinite(Date.parse(String(c.deadline))) && (c.status !== "Завершена" || (string(c.result) && !!String(c.result).trim() && string(c.workDescription) && !!String(c.workDescription).trim() && ["clear", "fixed", "unresolved"].includes(String(c.outcome)) && string(c.completedAt))))) return false
  if (!arrayOf(d.workOrders, (w) => string(w.id) && id(w.objectId) && string(w.title) && string(w.date) && ["В работе", "Запланировано", "Согласовано", "Завершена"].includes(String(w.status)) && (w.warningId === undefined || id(w.warningId)))) return false
  const data = d as unknown as Workspace["data"]
  for (const rows of [data.objects, data.warnings, data.checks, data.workOrders]) if (new Set(rows.map((r) => r.id)).size !== rows.length) return false
  for (const row of [...data.warnings, ...data.checks, ...data.workOrders]) if (!data.objects.some((o) => o.id === row.objectId)) return false
  for (const row of [...data.checks, ...data.workOrders]) if (row.warningId !== undefined && !data.warnings.some((w) => w.id === row.warningId && w.objectId === row.objectId)) return false
  if (!arrayOf(value.history, (e) => string(e.id) && string(e.at) && string(e.actor) && string(e.action) && id(e.objectId) && (e.warningId === undefined || id(e.warningId)) && (e.checkId === undefined || id(e.checkId)))) return false
  if (!["demo", "empty"].includes(String(value.preferences.mode)) || !record(value.preferences.filters)) return false
  return Object.entries(value.preferences.filters).every(([key, f]) => ["warnings", "map", "checks", "archive"].includes(key) && record(f) && [f.query, f.filter, f.category, f.sort].every(string))
}

export async function loadWorkspace(storage: StorageAccess = window.localStorage): Promise<Workspace> {
  const raw = storage.getItem(WORKSPACE_KEY)
  if (!raw) {
    const old = storage.getItem("astra.demo.workspace.v1")
    if (!old) { const initial = createWorkspace(); storage.setItem(WORKSPACE_KEY, JSON.stringify(initial)); return initial }
    try {
      const previous = JSON.parse(old)
      if (previous.version !== 1 || !Array.isArray(previous.data?.checks) || !Array.isArray(previous.history)) throw new Error()
      previous.version = 2
      previous.assignees ??= [...assignees]
      previous.preferences.filters = {}
      mergeLegacyData(previous.data, previous.history, new Date())
      if (!validateWorkspace(previous)) throw new Error()
      reopenUnresolved(previous)
      storage.setItem(WORKSPACE_KEY, JSON.stringify(previous))
      return previous
    } catch { throw new Error("Не удалось перенести старые демоданные. Исходная копия сохранена; можно сбросить демо.") }
  }
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error("Сохранённые демоданные повреждены. Повторите загрузку или сбросьте демо.") }
  if (!validateWorkspace(value)) throw new Error("Формат сохранённых демоданных не поддерживается. Можно сбросить демо к исходному набору.")
  if (reopenUnresolved(value)) { value.revision++; storage.setItem(WORKSPACE_KEY, JSON.stringify(value)) }
  return value
}

export function saveWorkspace(next: Workspace, expectedRevision: number, storage: StorageAccess = window.localStorage): Workspace {
  const raw = storage.getItem(WORKSPACE_KEY)
  if (raw) {
    const saved: unknown = JSON.parse(raw)
    if (!validateWorkspace(saved) || saved.revision !== expectedRevision) throw new Error("Демоданные изменились в другой вкладке. Перезагрузите данные перед сохранением.")
  }
  const result = { ...next, revision: expectedRevision + 1 }
  storage.setItem(WORKSPACE_KEY, JSON.stringify(result))
  return result
}

export function resetWorkspace(storage: StorageAccess = window.localStorage): Workspace {
  const initial = createWorkspace()
  try {
    const previous: unknown = JSON.parse(storage.getItem(WORKSPACE_KEY) ?? "null")
    initial.revision = validateWorkspace(previous) ? previous.revision + 1 : 1
  } catch { initial.revision = 1 }
  storage.setItem(WORKSPACE_KEY, JSON.stringify(initial))
  return initial
}

// Screen code depends only on this asynchronous boundary. A backend adapter can
// implement the same methods with HTTP, including server-side authorization.
export interface WorkspaceRepository {
  kind: "demo" | "remote"
  subscribe?(onChange: () => void): () => void
  load(): Promise<Workspace>
  execute(action: DemoAction, expectedRevision: number): Promise<Workspace>
  preferences(preferences: Workspace["preferences"], expectedRevision: number): Promise<Workspace>
  reset(): Promise<Workspace>
}
export function visibleWorkspace(full: Workspace, user?: User): Workspace {
  if (!user || user.role === "dispatcher") return full
  const checks = full.data.checks.filter(c => (c.assigneeId ?? demoUsers.find(u => u.name === c.assignee)?.id) === user.id)
  const checkIds = new Set(checks.map(c => c.id)), objectIds = new Set(checks.map(c => c.objectId)), warningIds = new Set(checks.map(c => c.warningId))
  return { ...full, assignees: [user.name], data: { ...full.data, checks, objects: full.data.objects.filter(o => objectIds.has(o.id)), warnings: full.data.warnings.filter(w => warningIds.has(w.id)), workOrders: [] }, history: full.history.filter(h => h.checkId ? checkIds.has(h.checkId) : warningIds.has(h.warningId)) }
}
export function createDemoRepository(storage?: StorageAccess, user?: User): WorkspaceRepository {
  const source = () => storage ?? window.localStorage
  const preferencesKey = `astra.preferences.v1.${user?.id ?? "default"}`
  async function load() {
    const full = await loadWorkspace(storage)
    // Migrate legacy display-name assignments to stable employee IDs at the boundary.
    full.data.checks = full.data.checks.map(c => ({ ...c, assigneeId: c.assigneeId ?? demoUsers.find(u => u.name === c.assignee)?.id }))
    return full
  }
  function view(full: Workspace) {
    const result = visibleWorkspace(full, user)
    if (user) {
      const raw = source().getItem(preferencesKey)
      try { result.preferences = raw ? JSON.parse(raw) : { mode: "demo", filters: {} }; if (!result.preferences || !["demo", "empty"].includes(result.preferences.mode) || typeof result.preferences.filters !== "object") throw new Error() }
      catch { result.preferences = {mode:"demo",filters:{}} }
    }
    return result
  }
  return {
    kind: "demo",
    subscribe(onChange) {
      if (typeof window === "undefined") return () => {}
      const listener = (event: StorageEvent) => { if (event.key === WORKSPACE_KEY) onChange() }
      window.addEventListener("storage", listener)
      return () => window.removeEventListener("storage", listener)
    },
    load: async () => view(await load()),
    async execute(action, revision) {
      const current = await load()
      if (current.revision !== revision) throw new Error("Данные изменились в другой вкладке. Перезагрузите данные.")
      if (action.type === "planWork") throw new Error("Изменение плана работ недоступно. Диспетчер наблюдает за выполнением.")
      if (action.type === "assign" && action.warningId === undefined) throw new Error("Назначьте проверку из предупреждения на главной.")
      if (user?.role === "dispatcher" && action.type !== "assign" && action.type !== "falseAlarm") throw new Error("Выполнение и отчёт доступны только назначенному техспециалисту.")
      if (user?.role === "technician") {
        if (action.type !== "advance" && action.type !== "result") throw new Error("Это действие доступно диспетчеру.")
        if (!current.data.checks.some(c => c.id === action.checkId && c.assigneeId === user.id)) throw new Error("Эта проверка вам не назначена. Обновите список.")
      }
      const next = applyAction(current, action, new Date(), user?.name)
      // Dispatcher may change the executor by display name; keep the ID synchronized.
      next.data.checks = next.data.checks.map(c => ({ ...c, assigneeId: demoUsers.find(u => u.name === c.assignee)?.id }))
      return view(saveWorkspace(next, revision, storage))
    },
    async preferences(preferences, revision) {
      const current = await load()
      if (current.revision !== revision) throw new Error("Данные изменились в другой вкладке. Перезагрузите данные.")
      if (user) { source().setItem(preferencesKey, JSON.stringify(preferences)); return view(current) }
      return saveWorkspace({ ...current, preferences }, revision, storage)
    },
    async reset() {
      if (user?.role === "technician") throw new Error("Сброс доступен только диспетчеру.")
      const next = resetWorkspace(storage)
      if (user) for (const employee of demoUsers) source().setItem(`astra.preferences.v1.${employee.id}`, JSON.stringify(next.preferences))
      return view(next)
    },
  }
}
export const demoRepository = createDemoRepository()
