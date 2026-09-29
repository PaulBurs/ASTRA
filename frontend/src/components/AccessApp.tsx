import { DraftContext } from "./DraftContext"
import { demoDrafts, type DraftRepository } from "../api/drafts"
import { useEffect, useMemo, useState } from "react"
import App from "../App"
import { demoAuth, demoUsers, type AuthRepository, type User } from "../api/auth"
import { createDemoRepository, type WorkspaceRepository } from "../api/workspace"
import { useRoute } from "../state/navigation"
import "./LoginPage.css"

function replacePath(path: string) {
  window.history.replaceState(null, "", path)
  window.dispatchEvent(new PopStateEvent("popstate"))
}
export function AccessApp({ auth = demoAuth, repositoryFor = defaultRepository, drafts = demoDrafts }: { drafts?: DraftRepository; auth?: AuthRepository; repositoryFor?: (user: User) => WorkspaceRepository }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const route = useRoute()
  useEffect(() => {
    let active = true
    void auth.current().then(value => { if (active) setUser(value) }).catch(() => { if (active) setError("Не удалось восстановить вход. Введите ID повторно.") }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [auth])
  useEffect(() => {
    if (loading) return
    if (!user) { if (window.location.pathname !== "/login") replacePath("/login"); return }
    if (window.location.pathname === "/login" || (user.role === "technician" && !["checks", "map", "archive"].includes(route.page))) replacePath(user.role === "technician" ? "/checks" : "/home")
  }, [loading, user, route.page])
  const repository = useMemo(() => user ? repositoryFor(user) : undefined, [user, repositoryFor])
  async function logout() {
    setBusy(true); setError("")
    try { await auth.signOut(); setUser(null); replacePath("/login") }
    catch { setError("Не удалось выйти. Повторите попытку.") }
    finally { setBusy(false) }
  }
  if (loading) return <main className="login-screen"><section className="login-card" role="status"><strong>ASTRA</strong><h1>Восстанавливаем вход…</h1></section></main>
  if (!user) return <main className="login-screen"><section className="login-intro"><strong className="login-brand">ASTRA</strong><span>Контроль инфраструктуры</span><h1>Все задачи.<br/>Один рабочий процесс.</h1><p>Проверки, результаты и история работ — в рабочем пространстве вашей команды.</p><div className="login-steps"><span>01 · Получить задачу</span><span>02 · Выполнить проверку</span><span>03 · Сохранить отчёт</span></div></section><section className="login-card" aria-labelledby="login-title"><span className="login-badge">{auth.kind === "demo" ? "Демонстрационный вход" : "Вход сотрудника"}</span><h2 id="login-title">Вход в ASTRA</h2><p>Введите ID сотрудника, чтобы открыть своё рабочее пространство.</p><form onSubmit={async e => {
      e.preventDefault(); const id = String(new FormData(e.currentTarget).get("employeeId") ?? ""); setBusy(true); setError("")
      try { const next = await auth.signIn(id); setUser(next); replacePath(next.role === "technician" ? "/checks" : "/home") }
      catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось войти. Попробуйте ещё раз.") }
      finally { setBusy(false) }
    }}><label htmlFor="employee-id">ID сотрудника</label><input id="employee-id" name="employeeId" autoComplete="username" autoFocus required maxLength={64} placeholder="Например, 2001" aria-describedby={error ? "login-error" : undefined} aria-invalid={!!error} disabled={busy}/>{error && <p id="login-error" className="login-error" role="alert">{error}</p>}<button disabled={busy} type="submit">{busy ? "Входим…" : "Войти"}</button></form>{auth.kind === "demo" && <div className="login-demo"><h3>Доступные демосотрудники</h3>{demoUsers.map(u=><div key={u.id}><code>{u.id}</code><span>{u.name}<small>{u.role === "dispatcher" ? "Диспетчер" : "Техспециалист"}</small></span></div>)}<p>Вход без пароля. Только тестовые данные.</p></div>}</section></main>
  const shell = <App key={user.id} user={user} repository={repository!} onLogout={logout} logoutBusy={busy}/>
  return <DraftContext.Provider value={drafts}>{shell}{error && <div className="auth-error" role="alert">{error}<button onClick={() => setError("")}>Закрыть</button></div>}</DraftContext.Provider>
}
function defaultRepository(user: User) { return createDemoRepository(undefined, user) }
