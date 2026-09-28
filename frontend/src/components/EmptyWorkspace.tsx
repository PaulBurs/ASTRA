import { navigate, type Route } from "../state/navigation"

const copy = {
  warnings: ["Главная", "Все датчики и прогнозы", "База данных не загружена", "Загрузите и подготовьте данные, чтобы увидеть датчики и получить прогноз."],
  map: ["Карта", "Объекты и датчики", "Нет данных об объектах", "Объекты и датчики появятся после загрузки базы данных."],
  checks: ["Проверки", "Назначения и результаты осмотров", "Проверок пока нет", "Здесь появятся назначенные проверки и результаты осмотров."],
  archive: ["Архив", "Завершённые проверки с отчётами", "Архив пока пуст", "После завершения проверки и сохранения отчёта её карточка появится здесь."],
}
export function EmptyWorkspace({ page, technician = false }: { page: Route["page"]; technician?: boolean }) {
  const content = copy[page as keyof typeof copy] ?? ["Страница не найдена", "", "Страница не найдена", "Выберите раздел в меню."]
  return <main className="warnings-page"><div className="warnings-page-heading"><h1>{content[0]}</h1><p>{content[1]}</p></div>
    <section className="section-empty"><h2>{content[2]}</h2><p>{content[3]}</p>{!technician && page === "warnings" && <button onClick={() => navigate("data")}>Перейти к загрузке данных</button>}</section>
  </main>
}
