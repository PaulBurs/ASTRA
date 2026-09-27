export interface User { id: string; name: string; role: "dispatcher" | "technician" }
export interface AuthRepository {
  kind: "demo" | "remote"
  current(): Promise<User | null>
  signIn(employeeId: string): Promise<User>
  signOut(): Promise<void>
}
export const demoUsers: readonly User[] = [
  { id: "1001", name: "Егор В.", role: "dispatcher" },
  { id: "2001", name: "Алексей К.", role: "technician" },
  { id: "2002", name: "Дмитрий П.", role: "technician" },
]
export const SESSION_KEY = "astra.demo.session.v1"
type SessionStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">
// Per-tab session permits dispatcher and technician demos in separate tabs.
export function createDemoAuth(storage?: SessionStorage): AuthRepository {
  const source = () => storage ?? window.sessionStorage
  return {
    kind: "demo",
    async current() { const id = source().getItem(SESSION_KEY); return demoUsers.find(u => u.id === id) ?? null },
    async signIn(employeeId) {
      const user = demoUsers.find(u => u.id === employeeId.trim())
      if (!user) throw new Error("Сотрудник с таким ID не найден. Проверьте ID и повторите вход.")
      try { source().setItem(SESSION_KEY, user.id) } catch { throw new Error("Не удалось сохранить вход. Разрешите хранение данных в браузере.") }
      return user
    },
    async signOut() { source().removeItem(SESSION_KEY) },
  }
}
export const demoAuth = createDemoAuth()
