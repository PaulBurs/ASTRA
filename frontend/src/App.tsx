import { useSyncExternalStore } from "react"
import type { User } from "./api/auth"
import type { WorkspaceRepository } from "./api/workspace"
import { WarningsPage } from "./components/WarningsPage"
import { DemoMode } from "./components/DemoMode"
import { LiveMode } from "./components/LiveMode"
import { useRoute } from "./state/navigation"
import "./App.css"

const MODE_KEY = "astra.application.mode.v1"
const DEMO_READY_KEY = "astra.demo.loaded.v1"
function subscribe(change: () => void) {
  window.addEventListener("storage", change)
  window.addEventListener("astra-mode", change)
  return () => { window.removeEventListener("storage", change); window.removeEventListener("astra-mode", change) }
}
function save(key: string, value: string) {
  localStorage.setItem(key, value)
  window.dispatchEvent(new Event("astra-mode"))
}
export default function App({ user, repository, onLogout, logoutBusy }: {
  user: User; repository: WorkspaceRepository; onLogout: () => Promise<void>; logoutBusy: boolean
}) {
  const route = useRoute()
  const mode = useSyncExternalStore(subscribe, () => localStorage.getItem(MODE_KEY) === "live" ? "live" : "demo")
  const demoReady = useSyncExternalStore(subscribe, () => localStorage.getItem(DEMO_READY_KEY) === "true")
  const activeRoute = route.page === "sensors" ? { page: "warnings" as const } : route
  return <WarningsPage route={activeRoute} user={user} onLogout={onLogout} logoutBusy={logoutBusy}
    mode={mode} onMode={next => save(MODE_KEY, next)}>
    {mode === "demo"
      ? <DemoMode user={user} repository={repository} route={activeRoute} ready={demoReady} setReady={ready => save(DEMO_READY_KEY, String(ready))}/>
      : <LiveMode user={user} route={activeRoute}/>}
  </WarningsPage>
}
