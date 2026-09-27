import { useState } from "react"
import checksScreen from "../assets/screens/D08.png"
import "./WarningsPage.css"

const pages = [
  { id: "warnings", label: "Предупреждения" },
  { id: "objects", label: "Объекты" },
  { id: "map", label: "Карта" },
  { id: "checks", label: "Проверки" },
  { id: "workOrders", label: "Заявки на работы" },
] as const

type Page = (typeof pages)[number]["id"]

const emptyPages = {
  objects: {
    subtitle: "Реестр инфраструктуры",
    title: "Объектов пока нет",
    description: "Объекты появятся здесь после загрузки данных об инфраструктуре.",
  },
  map: {
    subtitle: "Расположение объектов",
    title: "Нет объектов для отображения на карте",
    description: "Объекты появятся на карте, когда будут доступны данные об их расположении.",
  },
  workOrders: {
    subtitle: "Данные из системы учёта работ",
    title: "Заявок на работы пока нет",
    description: "Заявки появятся здесь после получения данных из системы учёта работ.",
  },
}

interface WarningsPageProps {
  onOpenJournal: () => void
  onOpenObjects: () => void
}

export function WarningsPage({
  onOpenJournal,
  onOpenObjects,
}: WarningsPageProps) {
  const [activePage, setActivePage] = useState<Page>("warnings")
  const pageTitle = pages.find((page) => page.id === activePage)!.label

  return (
    <div className="warnings-screen">
      <header className="warnings-topbar">
        <div className="warnings-brand">
          <strong>ASTRA</strong>
          <span>Диспетчерская</span>
        </div>
        <div className="warnings-userbar">
          <time dateTime="2026-09-24T15:20:00">24 сентября 2026 · 15:20</time>
          <span className="warnings-demo">Демо</span>
          <svg className="warnings-bell" viewBox="0 0 24 24" aria-label="Уведомления" role="img">
            <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
          </svg>
          <strong>ЕВ · Егор В.</strong>
        </div>
      </header>

      <aside className="warnings-sidebar">
        <nav aria-label="Разделы диспетчера" className="warnings-navigation">
          {pages.map((page) => (
            <button
              key={page.id}
              type="button"
              className={activePage === page.id ? "warnings-nav-active" : undefined}
              aria-current={activePage === page.id ? "page" : undefined}
              onClick={() => setActivePage(page.id)}
            >
              {page.label}
            </button>
          ))}
        </nav>
        <div className="warnings-role">
          <span>Диспетчер</span>
          <span>Смена 08:00–20:00</span>
        </div>
      </aside>

      {activePage === "warnings" ? (
      <main className="warnings-page">
        <div className="warnings-page-heading">
          <h1>Предупреждения</h1>
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
      ) : activePage === "checks" ? (
        <main className="screen-placeholder" aria-label={pageTitle}>
          <h1 className="screen-placeholder-title">{pageTitle}</h1>
          <div className="screen-placeholder-preview">
            <img
              src={checksScreen}
              alt={`Макет раздела «${pageTitle}». Элементы внутри изображения неактивны.`}
            />
          </div>
          <div className="screen-placeholder-note">
            <span>Страница-заглушка · демонстрационный макет</span>
          </div>
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
            {activePage === "objects" && (
              <button type="button" onClick={onOpenObjects}>
                Открыть панель датчиков
              </button>
            )}
            {activePage === "map" && (
              <button type="button" onClick={() => setActivePage("objects")}>
                Перейти к объектам
              </button>
            )}
          </section>
        </main>
      )}

      <footer className="warnings-statusbar">
        <span className="warnings-updated">●&nbsp; Данные обновлены в 15:19</span>
        <span>Демонстрационные данные</span>
      </footer>
    </div>
  )
}
