export type Section = "warnings" | "map" | "checks" | "archive"
export interface DemoObject {
  id: number
  name: string
  system: string
  updated: string
  position: [number, number]
  channels: { name: string; value: string }[]
}
export interface DemoWarning {
  id: number
  objectId: number
  title: string
  probability: number
  minutesOpen: number
  status: "Новое" | "Ложная тревога" | "На проверке" | "Подтверждено"
}
export interface DemoCheck {
  id: number
  objectId: number
  warningId?: number
  title: string
  assignee: string
  deadline: string
  status: "Новая" | "В работе" | "Завершена"
  plannedAt?: string
  workDescription?: string
  outcome?: "clear" | "fixed" | "unresolved"
  completedAt?: string
  result?: string
}
export interface DemoWorkOrder {
  id: string
  objectId: number
  warningId?: number
  title: string
  status: "В работе" | "Запланировано" | "Согласовано" | "Завершена"
  date: string
}
export interface DemoData {
  objects: DemoObject[]
  warnings: DemoWarning[]
  checks: DemoCheck[]
  workOrders: DemoWorkOrder[]
}

