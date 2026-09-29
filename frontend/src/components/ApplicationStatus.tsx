import { useEffect, useRef, useState } from "react"
import { getSystemHealth, type SystemHealth } from "../api/health"

export function ApplicationStatus({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [error, setError] = useState("")
  useEffect(() => { dialog.current?.showModal() }, [])
  useEffect(() => {
    let active = true
    void getSystemHealth().then(value => { if (active) setHealth(value) }).catch(() => { if (active) setError("Backend недоступен. Состояние PostgreSQL и ML неизвестно.") })
    return () => { active = false }
  }, [])
  return <dialog ref={dialog} className="workspace-dialog application-status" aria-labelledby="application-status-title" onCancel={onClose}>
    <h2 id="application-status-title">Состояние приложения</h2>
    {error ? <p role="alert">{error}</p> : !health ? <p role="status">Проверяем подключение…</p> : <dl>{[
      ["Backend", "Работает", true], ["PostgreSQL", health.database === "connected" ? "Подключена" : "Недоступна", health.database === "connected"],
      ["ML-модель", health.ml === "available" ? "Доступна" : "Недоступна", health.ml === "available"],
    ].map(([name, value, ok]) => <div key={String(name)}><dt>{name}</dt><dd className={ok ? "status-ok" : "status-error"}>● {value}</dd></div>)}</dl>}
    <div className="workspace-dialog-actions"><button autoFocus onClick={onClose}>Закрыть</button></div>
  </dialog>
}
