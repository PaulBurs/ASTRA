import { DraftContext } from "./DraftContext"
import { useContext, useEffect, useRef, useState, type FormEvent } from "react"
import type { DemoCheck } from "../state/models"
import { type DraftRepository, type ReportDraft } from "../api/drafts"
import { outcomes, type DemoAction } from "../state/workspace"

export function ReportForm({ check, userId, busy, onSubmit, onCancel, drafts: suppliedDrafts }: {
  check: DemoCheck; userId: string; busy: boolean; onSubmit: (action: DemoAction) => Promise<boolean>; onCancel: () => void; drafts?: DraftRepository
}) {
  const inheritedDrafts = useContext(DraftContext)
  const drafts = suppliedDrafts ?? inheritedDrafts
  const key = `${userId}.${check.id}.${check.plannedAt ?? check.deadline}`
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState<ReportDraft>({ outcome: check.outcome ?? "clear", result: check.result ?? "", work: check.workDescription ?? "" })
  const [message, setMessage] = useState("")
  const [failed, setFailed] = useState(false)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const generation = useRef(0)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true; let active = true
    void drafts.load(key).then(value => { if (active && value) { setDraft(value); setMessage("Черновик восстановлен.") } }).catch(() => { if (active) { setFailed(true); setMessage("Черновик недоступен. Можно заполнить отчёт заново.") } }).finally(() => { if (active) setLoading(false) })
    return () => { active = false; mounted.current = false }
  }, [drafts, key])
  function change(patch: Partial<ReportDraft>) {
    const next = { ...draft, ...patch }; setDraft(next); setMessage("Сохраняем черновик…"); setFailed(false)
    const ticket = ++generation.current
    // Serialize writes so slower HTTP draft adapters cannot overwrite newer text.
    queue.current = queue.current.catch(() => {}).then(() => drafts.save(key, next)).then(() => { if (mounted.current && ticket === generation.current) setMessage("Черновик сохранён.") }).catch(() => { if (mounted.current && ticket === generation.current) { setFailed(true); setMessage("Черновик не сохранён. Не закрывайте форму; повторите сохранение.") } })
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    await queue.current
    if (await onSubmit({ type:"result", checkId:check.id, outcome:draft.outcome, result:draft.result, workDescription:draft.work })) {
      try { await drafts.remove(key) } catch { /* The submitted result is already saved in the check. */ }
    }
  }
  return <form className="demo-form" onSubmit={submit}><h3>Отчёт о проверке</h3>{loading ? <p role="status">Загружаем черновик…</p> : <><fieldset disabled={busy}>
    <label>Результат<select name="outcome" value={draft.outcome} onChange={e => change({outcome:e.target.value as ReportDraft["outcome"]})}>{Object.entries(outcomes).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <label>Отчёт об обследовании<textarea name="result" required maxLength={4000} value={draft.result} onChange={e=>change({result:e.target.value})}/></label>
    <label>Выполненные работы или причина, почему не требовались<textarea name="work" required maxLength={4000} value={draft.work} onChange={e=>change({work:e.target.value})}/></label>
    <div className="demo-action-buttons"><button type="submit" className="primary">{busy ? "Сохранение…" : draft.outcome === "unresolved" ? "Сохранить результат и продолжить работу" : "Сохранить отчёт и завершить"}</button><button type="button" onClick={onCancel}>Закрыть черновик</button></div>
  </fieldset>{draft.outcome === "unresolved" && <p className="demo-note">Проверка останется в работе. После устранения неисправности добавьте новый результат.</p>}<p className={failed ? "demo-form-error" : "demo-note"} role="status">{message || "Черновик сохраняется автоматически в этом браузере."}</p>{failed && <button type="button" disabled={busy} onClick={()=>change({})}>Повторить сохранение черновика</button>}</>}</form>
}
