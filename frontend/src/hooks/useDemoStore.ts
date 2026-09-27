import { useCallback, useEffect, useRef, useState } from "react"
import { demoRepository, type WorkspaceRepository } from "../api/workspace"
import type { DemoAction, Workspace } from "../state/workspace"

export function useDemoStore(repository: WorkspaceRepository = demoRepository) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const current = useRef<Workspace | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const [error, setError] = useState<string | null>(null)
  const request = useRef(0)
  const accept = (next: Workspace) => { current.current = next; setWorkspace(next) }
  const reload = useCallback(async () => {
    if (locked.current) return
    const ticket = ++request.current
    setLoading(true); setError(null)
    try { const value = await repository.load(); if (ticket === request.current) accept(value) }
    catch (reason) { if (ticket === request.current) setError(reason instanceof Error ? reason.message : "Не удалось загрузить данные.") }
    finally { if (ticket === request.current) setLoading(false) }
  }, [repository])
  // Synchronize the UI with an external repository; the ref is a request counter, not a DOM node.
  // eslint-disable-next-line react/set-state-in-effect, react-hooks/exhaustive-deps
  useEffect(() => { void reload(); return () => { request.current++ } }, [reload])
  async function mutate(operation: () => Promise<Workspace>) {
    if (locked.current) throw new Error("Дождитесь сохранения предыдущего действия.")
    locked.current = true; setBusy(true); request.current++
    try { const next = await operation(); accept(next); setError(null); setLoading(false) }
    finally { locked.current = false; setBusy(false) }
  }
  function ready() { if (!current.current) throw new Error("Данные ещё не загружены."); return current.current }
  return { workspace, loading, busy, error, reload,
    reset: () => mutate(() => repository.reset()),
    preferences: (preferences: Workspace["preferences"]) => mutate(() => repository.preferences(preferences, ready().revision)),
    act: (action: DemoAction) => mutate(() => repository.execute(action, ready().revision)),
  }
}
