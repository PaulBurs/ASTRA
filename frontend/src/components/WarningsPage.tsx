import { useState, type ReactNode } from "react"
import type { User } from "../api/auth"
import { navigate, routeHref, type Route } from "../state/navigation"
import { ApplicationStatus } from "./ApplicationStatus"
import "./WarningsPage.css"

const pages = [
  { id: "warnings", label: "Главная" }, { id: "map", label: "Карта" },
  { id: "checks", label: "Проверки" }, { id: "archive", label: "Архив" }, { id: "data", label: "Данные" },
] as const
export function WarningsPage({ route, user, onLogout, logoutBusy, mode, onMode, children }: {
  route: Route; user: User; onLogout: () => Promise<void>; logoutBusy: boolean
  mode: "demo" | "live"; onMode: (mode: "demo" | "live") => void; children: ReactNode
}) {
  const technician = user.role === "technician"
  const [statusOpen, setStatusOpen] = useState(false)
  const visiblePages = technician ? [pages[2], pages[1], pages[3]] : pages
  return <div className="warnings-screen">
    <header className="warnings-topbar">
      <div className="warnings-brand"><strong>ASTRA</strong><span>{technician ? "Кабинет техспециалиста" : "Диспетчерская"}</span></div>
      <div className="warnings-userbar">
        <time dateTime={new Date().toISOString()}>{new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</time>
        <select className="warnings-mode" aria-label="Режим данных" value={mode} onChange={event => onMode(event.target.value as "demo" | "live")}>
          <option value="demo">Демо</option><option value="live">v1.0.1</option>
        </select>
        <svg className="warnings-bell" viewBox="0 0 24 24" aria-label="Уведомления" role="img"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg>
        <strong className="workspace-user">{user.name} · ID {user.id}</strong>
        <button className="workspace-logout" disabled={logoutBusy} onClick={() => void onLogout()}>{logoutBusy ? "Выходим…" : "Выйти"}</button>
      </div>
    </header>
    <aside className="warnings-sidebar">
      <nav aria-label="Разделы приложения" className="warnings-navigation">{visiblePages.map(page => <a key={page.id} href={routeHref(page.id)} className={route.page === page.id ? "warnings-nav-active" : undefined} aria-current={route.page === page.id ? "page" : undefined} onClick={event => {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
        event.preventDefault(); navigate(page.id)
      }}>{technician && page.id === "checks" ? "Мои проверки" : page.label}</a>)}</nav>
      <div className="application-sidebar-bottom"><button className="application-status-button" onClick={() => setStatusOpen(true)}>Состояние приложения</button><div className="warnings-role"><span>{technician ? "Техспециалист" : "Диспетчер"}</span><span>{user.name} · {user.id}</span></div></div>
    </aside>
    {children}
    <footer className="warnings-statusbar"><span className="warnings-updated">{mode === "demo" ? "● Деморежим" : "● v1.0.1"}</span><span>{mode === "demo" ? "Тестовые данные · без загрузки файлов" : "Данные из загруженной базы"}</span></footer>
    {statusOpen && <ApplicationStatus onClose={() => setStatusOpen(false)}/>}
  </div>
}
