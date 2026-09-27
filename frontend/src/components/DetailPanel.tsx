import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react"

const query = "(max-width: 1000px)"
function subscribe(callback: () => void) {
  const media = window.matchMedia(query)
  media.addEventListener("change", callback)
  return () => media.removeEventListener("change", callback)
}
export function DetailPanel({ children, recordKey, onClose }: { children: ReactNode; recordKey: string; onClose: () => void }) {
  const mobile = useSyncExternalStore(subscribe, () => window.matchMedia(query).matches)
  const aside = useRef<HTMLElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const modal = dialog.current
    if (mobile) modal?.showModal()
    else aside.current?.focus({ preventScroll: true })
    return () => { modal?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }) }
  }, [mobile, recordKey])
  const content = <><div className="demo-detail-header"><strong>Карточка записи</strong><button type="button" onClick={onClose} aria-label="Закрыть карточку">Закрыть ×</button></div>{children}</>
  return mobile ? <dialog ref={dialog} className="demo-details demo-detail-drawer" aria-label="Карточка записи" onCancel={e => { e.preventDefault(); onClose() }} onClick={e => { if (e.target === e.currentTarget) { const rect=e.currentTarget.getBoundingClientRect(); if (e.clientX<rect.left || e.clientX>rect.right || e.clientY<rect.top || e.clientY>rect.bottom) onClose() } }}>{content}</dialog> : <aside ref={aside} tabIndex={-1} className="demo-details" aria-label="Карточка записи" onKeyDown={e => { if (e.key === "Escape") { e.preventDefault(); onClose() } }}>{content}</aside>
}
