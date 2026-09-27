import { ReportForm } from "./ReportForm"
import { useState, type FormEvent } from "react"
import type { DemoCheck, DemoWarning } from "../state/models"
import { isOpenWarning, type DemoAction, type Workspace } from "../state/workspace"
import { navigate } from "../state/navigation"
import type { Notice } from "./WorkspaceFeedback"

type Common = { act: (action: DemoAction) => Promise<void>; busy: boolean; notify: (message: string, type?: Notice["type"]) => void }
function localDate(hours: number) {
  const date = new Date(Date.now() + hours * 3600000)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
const dateValue = (form: FormData, key: string) => {
  const date = new Date(String(form.get(key)))
  if (!Number.isFinite(date.getTime())) throw new Error("Укажите дату и время.")
  return date.toISOString()
}
const text = (form: FormData, key: string) => String(form.get(key) ?? "")

export function AssignForm({ warning, workspace, act, busy, notify, onCancel }: Common & { warning?: DemoWarning; workspace: Workspace; onCancel: () => void }) {
  const [error, setError] = useState("")
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault(); setError("")
    const f = new FormData(e.currentTarget)
    try {
      await act({ type: "assign", warningId: warning?.id, objectId: Number(f.get("objectId")), title: text(f, "title"), assignee: text(f, "assignee"), plannedAt: dateValue(f, "plannedAt"), deadline: dateValue(f, "deadline") })
      notify("Проверка создана. Она доступна в проверках и на карте."); onCancel()
    } catch (reason) { setError((reason as Error).message) }
  }
  return <form className="demo-form" onSubmit={submit}><h3>Новая проверка</h3><fieldset disabled={busy}>
    {!warning && <label>Место проведения<select required name="objectId">{workspace.data.objects.map(o => <option key={o.id} value={o.id}>{o.name} · {o.system}</option>)}</select></label>}
    <label>Задача<input required name="title" maxLength={200} defaultValue={warning ? `Проверить: ${warning.title.toLowerCase()}` : ""} /></label>
    <label>Исполнитель<select name="assignee">{workspace.assignees.map(name => <option key={name}>{name}</option>)}</select></label>
    <label>Плановое начало<input required name="plannedAt" type="datetime-local" defaultValue={localDate(1)} /></label>
    <label>Срок завершения<input required name="deadline" type="datetime-local" defaultValue={localDate(3)} /></label>
    <div className="demo-action-buttons"><button type="submit" className="primary">{busy ? "Сохранение…" : "Создать проверку"}</button><button type="button" onClick={onCancel}>Отмена</button></div>
  </fieldset>{error && <p role="alert" className="demo-form-error">{error}</p>}</form>
}
export function WarningActions({ warning, workspace, act, busy, notify }: Common & { warning: DemoWarning; workspace: Workspace }) {
  const [form, setForm] = useState<"assign" | "falseAlarm" | null>(null)
  const [error, setError] = useState("")
  const hasActive = workspace.data.checks.some(c => c.warningId === warning.id && c.status !== "Завершена")
  if (!isOpenWarning(warning.status)) return <p>Решение: {warning.status}.</p>
  return <section className="demo-actions"><h3>Решение по событию</h3>{hasActive ? <p>Проверка назначена. Статус выполнения доступен в её карточке.</p> : <>
    {!form && <div className="demo-action-buttons"><button disabled={busy} className="primary" onClick={() => setForm("assign")}>Назначить проверку</button><button disabled={busy} onClick={() => setForm("falseAlarm")}>Ложная тревога</button></div>}
    {form === "assign" && <AssignForm warning={warning} workspace={workspace} act={act} busy={busy} notify={notify} onCancel={() => setForm(null)} />}
    {form === "falseAlarm" && <form className="demo-form" onSubmit={async e => { e.preventDefault(); const f = new FormData(e.currentTarget); try { await act({ type: "falseAlarm", warningId: warning.id, reason: text(f, "reason") }); setForm(null); notify("Решение сохранено.") } catch (reason) { setError((reason as Error).message) } }}>
      <label>Причина решения<textarea required name="reason" maxLength={2000} /></label>{error && <p role="alert">{error}</p>}<div className="demo-action-buttons"><button disabled={busy} type="submit">Сохранить решение</button><button disabled={busy} type="button" onClick={() => setForm(null)}>Отмена</button></div>
    </form>}
  </>}</section>
}
export function CheckActions({ check, act, busy, notify, userId }: Common & { check: DemoCheck; userId: string }) {
  const [showReport, setShowReport] = useState(false)
  const [error, setError] = useState("")
  async function run(action: DemoAction): Promise<boolean> {
    setError("")
    try {
      await act(action)
      setShowReport(false)
      if (action.type === "result") {
        const complete = action.outcome !== "unresolved"
        notify(complete ? "Отчёт сохранён. Проверка автоматически перемещена в архив." : "Результат сохранён. Проверка остаётся в работе до устранения неисправности.")
        if (complete) navigate("archive", check.id)
      } else notify("Проверка начата.")
      return true
    } catch (reason) { setError((reason as Error).message); return false }
  }
  if (check.status === "Завершена") return null
  return <section className="demo-actions"><h3>Выполнение проверки</h3><p className="demo-note">Исполнитель: {check.assignee}</p>
    {check.status === "Новая" ? <button disabled={busy} className="primary" onClick={() => void run({ type: "advance", checkId: check.id })}>Начать проверку</button> : <>
      <button disabled={busy} className="primary" onClick={() => setShowReport(true)}>Заполнить отчёт</button>
      {showReport && <ReportForm check={check} userId={userId} busy={busy} onSubmit={run} onCancel={() => setShowReport(false)}/>}
    </>}{error && <p className="demo-form-error" role="alert">{error}</p>}
  </section>
}
