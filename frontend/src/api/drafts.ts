export interface ReportDraft { outcome: "clear" | "fixed" | "unresolved"; result: string; work: string }
export interface DraftRepository {
  load(key: string): Promise<ReportDraft | null>
  save(key: string, value: ReportDraft): Promise<void>
  remove(key: string): Promise<void>
}
export function createDraftRepository(storage?: Pick<Storage, "getItem" | "setItem" | "removeItem">): DraftRepository {
  const source = () => storage ?? window.localStorage
  const name = (key: string) => `astra.report-draft.v1.${key}`
  return {
    async load(key) {
      const raw = source().getItem(name(key)); if (!raw) return null
      const value = JSON.parse(raw)
      if (!value || !["clear", "fixed", "unresolved"].includes(value.outcome) || typeof value.result !== "string" || typeof value.work !== "string") throw new Error("Не удалось прочитать черновик отчёта.")
      return value
    },
    async save(key, value) { source().setItem(name(key), JSON.stringify(value)) },
    async remove(key) { source().removeItem(name(key)) },
  }
}
export const demoDrafts = createDraftRepository()
