import { useCallback, useState } from "react"
import type { User } from "../api/auth"
import type { WorkspaceRepository } from "../api/workspace"
import { useDemoStore } from "../hooks/useDemoStore"
import { navigate, type Route } from "../state/navigation"
import { DemoWorkspace } from "./DemoWorkspace"
import { EmptyWorkspace } from "./EmptyWorkspace"
import { ResetDemoDialog, Toast, type Notice } from "./WorkspaceFeedback"
import "./DatasetImportPanel.css"

export function DemoMode({ user, repository, route, ready, setReady }: {
  user: User; repository: WorkspaceRepository; route: Route; ready: boolean; setReady: (value: boolean) => void
}) {
  const store = useDemoStore(repository)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const notify = (message: string, type: Notice["type"] = "success") => setNotice({ id: Date.now(), message, type })
  const closeNotice = useCallback(() => setNotice(null), [])
  const loadDemo = async () => {
    try { await store.reset(); setReady(true); notify("Демонстрационные данные готовы. Откройте главную или другой раздел.") }
    catch (cause) { notify((cause as Error).message, "error") }
  }
  return <>
    {route.page === "data" ? <main className="warnings-page data-page"><div className="warnings-page-heading"><h1>Данные</h1><p>Загрузите демонстрационный набор, чтобы познакомиться с приложением.</p></div>
      <div className="dataset-layout"><section className="dataset-import"><div className="dataset-card-heading"><h2>Таблицы из архива</h2><span className="dataset-format">Демо</span></div>
        <p className="dataset-description">Готовый набор датчиков, прогнозов и проверок.</p><div className="dataset-file-label"><strong>{ready ? "Демонстрационные данные загружены" : "Демонстрационный набор готов к загрузке"}</strong><span>Выбирать файлы не нужно</span></div>
        <div className="dataset-actions"><button className="dataset-primary" disabled={store.busy || ready} onClick={() => void loadDemo()}>{ready ? "Данные подготовлены" : "Загрузить и подготовить"}</button>{ready && <button onClick={() => navigate("warnings")}>На главную</button>}</div>
        {ready && <div className="dataset-actions"><button onClick={() => setResetOpen(true)}>Сбросить демо</button></div>}
      </section><aside className="dataset-help"><h2>Как работает демо</h2><p className="dataset-note">Нажмите «Загрузить и подготовить». Данные появятся на главной, карте, в проверках и архиве. Для работы со своей базой выберите режим v1.0.1.</p></aside></div></main>
    : !ready ? <EmptyWorkspace page={route.page} technician={user.role === "technician"}/>
    : store.loading ? <main className="warnings-page"><section className="section-empty" role="status">Загрузка данных…</section></main>
    : store.error || !store.workspace ? <main className="warnings-page"><section className="section-empty" role="alert"><h2>Не удалось загрузить демо</h2><p>{store.error}</p><button onClick={() => void store.reload()}>Повторить</button><button onClick={() => setResetOpen(true)}>Сбросить демо</button></section></main>
    : route.page === "warnings" || route.page === "map" || route.page === "checks" || route.page === "archive"
      ? <DemoWorkspace key={route.page} user={user} page={route.page} selectedId={route.id} workspace={store.workspace} busy={store.busy} preferences={store.preferences} act={store.act} notify={notify} onOpenJournal={() => notify("Демонстрационные прогнозы приведены в таблице на главной.", "info")} onReload={() => void store.reload()}/>
      : <EmptyWorkspace page={route.page}/>}
    <Toast notice={notice} onClose={closeNotice}/>
    {resetOpen && <ResetDemoDialog onCancel={() => setResetOpen(false)} onConfirm={async () => {
      try { await store.reset(); setReady(false); setResetOpen(false); navigate("data") }
      catch (cause) { notify((cause as Error).message, "error") }
    }}/>}
  </>
}
