import { useState, type FormEvent } from "react"
import type { DemoCheck, DemoWarning } from "../state/models"
import { isOpenWarning, outcomes, type DemoAction, type Workspace } from "../state/workspace"
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
  return <section className="demo-actions"><h3>Решение по событию</h3>{hasActive ? <p>Проверка уже назначена — продолжите работу в её карточке.</p> : <>
    {!form && <div className="demo-action-buttons"><button disabled={busy} className="primary" onClick={() => setForm("assign")}>Назначить проверку</button><button disabled={busy} onClick={() => setForm("falseAlarm")}>Ложная тревога</button></div>}
    {form === "assign" && <AssignForm warning={warning} workspace={workspace} act={act} busy={busy} notify={notify} onCancel={() => setForm(null)} />}
    {form === "falseAlarm" && <form className="demo-form" onSubmit={async e => { e.preventDefault(); const f = new FormData(e.currentTarget); try { await act({ type: "falseAlarm", warningId: warning.id, reason: text(f, "reason") }); setForm(null); notify("Решение сохранено.") } catch (reason) { setError((reason as Error).message) } }}>
      <label>Причина решения<textarea required name="reason" maxLength={2000} /></label>{error && <p role="alert">{error}</p>}<div className="demo-action-buttons"><button disabled={busy} type="submit">Сохранить решение</button><button disabled={busy} type="button" onClick={() => setForm(null)}>Отмена</button></div>
    </form>}
  </>}</section>
}
export function CheckActions({ check, act, busy, notify, assignees }: Common & { check: DemoCheck; assignees: string[] }) {
  const [form, setForm] = useState<"work" | "report" | null>(null)
  const [error, setError] = useState("")
  async function run(action: DemoAction) {
    setError("")
    try { await act(action); setForm(null); notify(action.type === "result" ? "Отчёт сохранён. Проверка перемещена в архив." : "Проверка обновлена."); if (action.type === "result") navigate("archive", check.id) }
    catch (reason) { setError((reason as Error).message) }
  }
  if (check.status === "Завершена") return null
  return <section className="demo-actions"><h3>Выполнение</h3><p className="demo-note">Демодействия исполнителя: {check.assignee}</p>
    {check.status === "Новая" ? <button disabled={busy} className="primary" onClick={() => void run({ type: "advance", checkId: check.id })}>Начать проверку</button> : <>
      <div className="demo-action-buttons"><button disabled={busy} onClick={() => setForm("work")}>Запланировать работы</button><button disabled={busy} className="primary" onClick={() => setForm("report")}>Завершить проверку</button></div>
      {form && <form key={form} className="demo-form" onSubmit={e => { e.preventDefault(); const f = new FormData(e.currentTarget); try { void run(form === "work" ? { type: "planWork", checkId: check.id, workDescription: text(f, "work"), assignee: text(f, "assignee"), deadline: dateValue(f, "deadline") } : { type: "result", checkId: check.id, outcome: text(f, "outcome") as keyof typeof outcomes, result: text(f, "result"), workDescription: text(f, "work") }) } catch (reason) { setError((reason as Error).message) } }}>
        <h3>{form === "work" ? "Необходимые работы" : "Итоговый отчёт"}</h3><fieldset disabled={busy}>
        {form === "work" ? <><label>Исполнитель<select name="assignee" defaultValue={check.assignee}>{assignees.map(name => <option key={name}>{name}</option>)}</select></label><label>Новый срок завершения<input required name="deadline" type="datetime-local" defaultValue={localDate(3)} /></label></> : <>
          <label>Результат<select name="outcome">{Object.entries(outcomes).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>Отчёт об обследовании<textarea name="result" required maxLength={4000} /></label>
        </>}
        <label>{form === "work" ? "Что необходимо выполнить" : "Выполненные работы или причина, почему не требовались"}<textarea name="work" required maxLength={4000} defaultValue={check.workDescription ?? ""} /></label>
        <div className="demo-action-buttons"><button className="primary" type="submit">{busy ? "Сохранение…" : form === "work" ? "Сохранить план" : "Сохранить отчёт и завершить"}</button><button type="button" onClick={() => setForm(null)}>Отмена</button></div></fieldset>
      </form>}
    </>}{error && <p className="demo-form-error" role="alert">{error}</p>}
  </section>
}
