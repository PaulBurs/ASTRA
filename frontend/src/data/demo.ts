import type { DemoData } from "../state/models.ts"
export type { Section, DemoObject, DemoWarning, DemoCheck, DemoWorkOrder, DemoData } from "../state/models.ts"

// UI fixtures are separate from the existing backend sensor contract.
export const demoData: DemoData = {
  objects: [
    { id: 1, name: "Коллектор 01", system: "Вентиляция", updated: "15:19", position: [21, 29], channels: [{ name: "Вентилятор 01", value: "Норма" }, { name: "Температура воздуха", value: "18,6 °C" }, { name: "Дверь 01", value: "Закрыта" }] },
    { id: 3, name: "Коллектор 03", system: "Водоотведение", updated: "15:18", position: [48, 43], channels: [{ name: "Насос 01", value: "Выключен" }, { name: "Уровень воды", value: "0,12 м" }] },
    { id: 7, name: "Коллектор 07", system: "Пожарная безопасность", updated: "15:19", position: [73, 24], channels: [{ name: "Датчик дыма", value: "Норма" }, { name: "Температура воздуха", value: "24,1 °C" }] },
    { id: 12, name: "Коллектор 12", system: "Телеметрия", updated: "15:14", position: [77, 70], channels: [{ name: "Канал связи", value: "Нестабильно" }] },
    { id: 9, name: "Коллектор 09", system: "Водоотведение", updated: "15:19", position: [32, 73], channels: [{ name: "Уровень воды", value: "0,18 м" }] },
    { id: 5, name: "Коллектор 05", system: "Вентиляция", updated: "15:17", position: [54, 18], channels: [{ name: "Вентилятор 01", value: "Норма" }] },
    { id: 11, name: "Коллектор 11", system: "Водоотведение", updated: "15:19", position: [59, 79], channels: [{ name: "Насос 01", value: "Включён" }] },
    { id: 16, name: "Коллектор 16", system: "Электроснабжение", updated: "15:18", position: [15, 55], channels: [{ name: "Напряжение", value: "220 В" }] },
  ],
  warnings: [
    { id: 1042, objectId: 1, title: "Риск отказа вентилятора", probability: 78, minutesOpen: 160, status: "На проверке" },
    { id: 1039, objectId: 3, title: "Риск подтопления", probability: 65, minutesOpen: 135, status: "Ложная тревога" },
    { id: 1037, objectId: 7, title: "Риск возгорания", probability: 81, minutesOpen: 118, status: "На проверке" },
    { id: 1045, objectId: 12, title: "Нестабильная работа канала", probability: 56, minutesOpen: 80, status: "Новое" },
    { id: 1046, objectId: 3, title: "Риск отказа насоса", probability: 72, minutesOpen: 58, status: "На проверке" },
    { id: 1048, objectId: 9, title: "Риск подтопления", probability: 61, minutesOpen: 42, status: "Ложная тревога" },
    { id: 1051, objectId: 5, title: "Риск отказа вентилятора", probability: 68, minutesOpen: 26, status: "Подтверждено" },
    { id: 1053, objectId: 11, title: "Риск отказа насоса", probability: 54, minutesOpen: 14, status: "Ложная тревога" },
  ],
  checks: [
    { id: 209, objectId: 3, warningId: 1046, title: "Осмотреть насос 01", assignee: "Дмитрий П.", deadline: "2026-09-27T16:00:00Z", status: "В работе" },
    { id: 208, objectId: 1, warningId: 1042, title: "Проверить вентилятор 01", assignee: "Алексей К.", deadline: "2026-09-27T14:00:00Z", status: "Новая" },
    { id: 207, objectId: 7, warningId: 1037, title: "Проверить датчик дыма", assignee: "Дмитрий П.", deadline: "2026-09-27T13:00:00Z", status: "В работе" },
    { id: 204, objectId: 3, warningId: 1039, title: "Проверить уровень воды", assignee: "Алексей К.", deadline: "2026-09-27T15:00:00Z", status: "Завершена", result: "Уровень воды в норме. Признаки подтопления не обнаружены." },
    { id: 198, objectId: 5, warningId: 1051, title: "Осмотреть вентилятор", assignee: "Алексей К.", deadline: "2026-09-27T11:00:00Z", status: "Завершена", result: "Посторонний шум при работе. Требуется дополнительная диагностика." },
    { id: 195, objectId: 11, warningId: 1053, title: "Осмотреть насос", assignee: "Дмитрий П.", deadline: "2026-09-27T09:00:00Z", status: "Завершена", result: "Оборудование работает штатно. Следов утечки нет." },
  ],
  workOrders: [
    { id: "Р-031", objectId: 1, warningId: 1042, title: "Диагностика вентилятора", status: "В работе", date: "25.09.2026" },
    { id: "Р-028", objectId: 3, title: "Обслуживание насоса", status: "Запланировано", date: "26.09.2026" },
    { id: "Р-023", objectId: 11, warningId: 1053, title: "Замена оборудования", status: "Согласовано", date: "27.09.2026" },
    { id: "Р-019", objectId: 16, title: "Проверка электроснабжения", status: "Завершена", date: "23.09.2026" },
  ],
}
