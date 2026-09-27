import { useEffect, useRef } from "react"

export interface Notice { id: number; type: "success" | "info" | "error"; message: string }
export function Toast({ notice, onClose }: { notice: Notice | null; onClose: () => void }) {
  useEffect(() => {
    if (!notice || notice.type === "error") return
    const timer = window.setTimeout(onClose, 7000)
    return () => window.clearTimeout(timer)
  }, [notice, onClose])
  return <div className="workspace-toast-host" aria-live="polite" aria-atomic="true">
    {notice && <div className={`workspace-toast ${notice.type}`} role={notice.type === "error" ? "alert" : "status"}>
      <span>{notice.message}</span><button type="button" aria-label="Закрыть уведомление" onClick={onClose}>×</button>
    </div>}
  </div>
}

export function ResetDemoDialog({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => { dialog.current?.showModal() }, [])
  return <dialog ref={dialog} className="workspace-dialog" aria-labelledby="reset-demo-title" onCancel={onCancel}>
    <h2 id="reset-demo-title">Сбросить демо?</h2>
    <p>Будут удалены созданные вами проверки, решения и история действий в этом браузере. Данные и фильтры вернутся к исходному демонстрационному набору.</p>
    <div className="workspace-dialog-actions"><button type="button" autoFocus onClick={onCancel}>Отмена</button><button type="button" className="danger" onClick={onConfirm}>Сбросить данные</button></div>
  </dialog>
}
