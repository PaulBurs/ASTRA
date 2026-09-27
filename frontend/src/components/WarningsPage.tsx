import type { User } from "../api/auth"
import { useCallback, useState, type ReactNode } from "react"
import type { WorkspaceRepository } from "../api/workspace"
import { useDemoStore } from "../hooks/useDemoStore"
import { navigate, routeHref, type Route } from "../state/navigation"
import { ResetDemoDialog, Toast, type Notice } from "./WorkspaceFeedback"
import { DemoWorkspace } from "./DemoWorkspace"
import "./WarningsPage.css"

const pages = [
  { id: "warnings", label: "Главная" },
  { id: "map", label: "Карта" },
  { id: "checks", label: "Проверки" },
  { id: "archive", label: "Архив" },
  { id: "data", label: "Данные" },
  { id: "sensors", label: "Датчики" },
] as const

type Page = (typeof pages)[number]["id"]

const emptyPages = {
  checks: {
    subtitle: "Назначения и результаты осмотров",
    title: "Проверок пока нет",
    description: "Здесь появятся назначенные проверки и результаты осмотров.",
  },
  map: {
    subtitle: "Текущие проверки: где и когда",
    title: "Нет текущих проверок",
    description: "Назначенные проверки с местом проведения появятся на карте.",
  },
  archive: {
    subtitle: "Завершённые проверки с отчётами",
    title: "Архив пока пуст",
    description: "После завершения проверки и сохранения отчёта её карточка появится здесь.",
  },
}

interface Props {
  route: Route
  repository?: WorkspaceRepository
  user: User
  onLogout: () => Promise<void>
  logoutBusy: boolean
  dataContent?: ReactNode
  sensorsContent?: ReactNode
  dataStatus?: string
}

export function WarningsPage({ route, repository, user, onLogout, logoutBusy, dataContent, sensorsContent, dataStatus }: Props) {
  const technician = user.role === "technician"
  const visiblePages = (technician ? [pages[2], pages[1], pages[3]] : pages).map(p => ({ ...p, label: technician && p.id === "checks" ? "Мои проверки" : p.label }))
  const store = useDemoStore(repository)
  const activePage = route.page as Page
  const sourcePage = activePage === "data" || activePage === "sensors"
  const isDemo = repository?.kind !== "remote"
  const mode = isDemo ? store.workspace?.preferences.mode ?? "demo" : "demo"
  const [notice, setNotice] = useState<Notice | null>(null)
  const [resetOpen, setResetOpen] = useState(false)
  const closeNotice = useCallback(() => setNotice(null), [])
  const notify = (message: string, type: Notice["type"] = "success") => setNotice({ id: Date.now(), message, type })
  const onOpenJournal = () => notify("Журнал прогнозов пока не подключён. История действий доступна в карточках предупреждений и проверок.", "info")
  const pageTitle = visiblePages.find((page) => page.id === activePage)?.label
  const onNavigate = (page: Page) => navigate(page)

  return (
    <div className="warnings-screen">
      <header className="warnings-topbar">
        <div className="warnings-brand">
          <strong>ASTRA</strong>
          <span>{technician ? "Кабинет техспециалиста" : "Диспетчерская"}</span>
        </div>
        <div className="warnings-userbar">
          <time dateTime={new Date().toISOString()}>{new Date().toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</time>
          {sourcePage && <span className="warnings-demo">Данные сервера</span>}
          {!sourcePage && isDemo && !technician && <><select className="warnings-mode" aria-label="Режим данных" value={mode} disabled={store.loading || store.busy || !!store.error} onChange={async (event) => {
            const nextMode = event.target.value as "demo" | "empty"
            try { await store.preferences({ ...store.workspace!.preferences, mode: nextMode }) }
            catch (error) { notify((error as Error).message, "error") }
          }}>
            <option value="demo">Демо</option>
            <option value="empty">Нет данных</option>
          </select>
          <button className="workspace-reset" type="button" disabled={store.busy} onClick={() => setResetOpen(true)}>Сбросить демо</button></>}
          <svg className="warnings-bell" viewBox="0 0 24 24" aria-label="Уведомления" role="img">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
          </svg>
          <strong className="workspace-user">{user.name} · ID {user.id}</strong><button className="workspace-logout" disabled={store.busy || logoutBusy} onClick={() => void onLogout()}>{logoutBusy ? "Выходим…" : "Выйти"}</button>
        </div>
      </header>

      <aside className="warnings-sidebar">
        <nav aria-label="Разделы приложения" className="warnings-navigation">
          {visiblePages.map((page) => (
            <a
              key={page.id}
              href={routeHref(page.id)}
              className={activePage === page.id ? "warnings-nav-active" : undefined}
              aria-current={activePage === page.id ? "page" : undefined}
              onClick={(event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                event.preventDefault()
                onNavigate(page.id)
              }}
            >
              {page.label}
            </a>
          ))}
        </nav>
        <div className="warnings-role">
          <span>{technician ? "Техспециалист" : "Диспетчер"}</span>
          <span>{user.name} · {user.id}</span>
        </div>
      </aside>

      {activePage === "data" ? dataContent : activePage === "sensors" ? sensorsContent : store.loading ? (
        <main className="warnings-page"><section className="section-empty" role="status" aria-busy="true"><span className="workspace-spinner" aria-hidden="true" /><h1>Загрузка данных…</h1></section></main>
      ) : store.error || !store.workspace ? (
        <main className="warnings-page"><section className="section-empty" role="alert"><h1>Не удалось загрузить данные</h1><p>{store.error}</p><button type="button" onClick={() => void store.reload()}>Повторить загрузку</button></section></main>
      ) : !pageTitle ? (
        <main className="warnings-page"><section className="section-empty"><h1>Страница не найдена</h1><p>Проверьте адрес или выберите раздел в меню.</p><button type="button" onClick={() => navigate("warnings")}>На главную</button></section></main>
      ) : mode === "demo" ? (
        <DemoWorkspace user={user} key={activePage} page={activePage} selectedId={route.id} workspace={store.workspace} busy={store.busy} preferences={store.preferences} act={store.act} notify={notify} onOpenJournal={onOpenJournal} onReload={() => void store.reload()} />
      ) : activePage === "warnings" ? (
      <main className="warnings-page">
        <div className="warnings-page-heading">
          <h1>Главная</h1>
          <p>Все открытые</p>
        </div>
        <section className="warnings-empty" aria-labelledby="warnings-empty-title">
          <h2 id="warnings-empty-title">Открытых предупреждений нет</h2>
          <p>Новые прогнозы появятся здесь после обработки данных.</p>
          <button type="button" onClick={onOpenJournal}>
            Открыть журнал прогнозов
          </button>
        </section>
      </main>
      ) : (
        <main className="warnings-page">
          <div className="warnings-page-heading">
            <h1>{pageTitle}</h1>
            <p>{emptyPages[activePage].subtitle}</p>
          </div>
          <section className="section-empty" aria-labelledby="section-empty-title">
            <h2 id="section-empty-title">{emptyPages[activePage].title}</h2>
            <p>{emptyPages[activePage].description}</p>
          </section>
        </main>
      )}

      <Toast notice={notice} onClose={closeNotice} />
      {resetOpen && <ResetDemoDialog onCancel={() => setResetOpen(false)} onConfirm={async () => {
        try { await store.reset(); setResetOpen(false); navigate("warnings"); notify("Демоданные и фильтры восстановлены.") }
        catch (error) { setResetOpen(false); notify((error as Error).message, "error") }
      }} />}
      <footer className="warnings-statusbar">
        <span className="warnings-updated">{sourcePage ? dataStatus ?? "Импорт таблиц" : !isDemo ? "● Данные сервера" : mode === "demo" ? "● Деморежим · без подключения к серверу" : "Нет данных"}</span>
        <span>{sourcePage ? "Подготовка данных без запуска обучения" : !isDemo ? "Рабочее пространство ASTRA" : mode === "demo" ? "Тестовые данные · изменения сохраняются в этом браузере" : "Пустые стартовые экраны"}</span>
      </footer>
    </div>
  )
}
