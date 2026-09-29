import type { User } from "../api/auth"
import { useDatasetImport } from "../hooks/useDatasetImport"
import type { Route } from "../state/navigation"
import DatasetImportPanel from "./DatasetImportPanel"
import { EmptyWorkspace } from "./EmptyWorkspace"
import { LiveWorkspace } from "./LiveWorkspace"

const prepared = () => {}
export function LiveMode({ user, route }: { user: User; route: Route }) {
  const controller = useDatasetImport(prepared, user.id)
  const dataset = controller.dataset
  const datasetId = dataset && ["prepared", "ready"].includes(dataset.status) ? dataset.id : undefined
  // The dataset identity keys every live query and UI state; a replacement
  // upload can never display cached sensors/checks from the preceding database.
  return <>
    {datasetId && <LiveWorkspace key={datasetId} datasetId={datasetId} user={user} route={route}/>}
    {route.page === "data" && user.role === "dispatcher" ? <DatasetImportPanel controller={controller} userId={user.id}/>
      : !datasetId ? controller.restoring ? <main className="warnings-page"><section className="section-empty" role="status">Проверяем загруженные данные…</section></main>
        : controller.error ? <main className="warnings-page"><section className="section-empty" role="alert"><h2>Не удалось открыть базу данных</h2><p>{controller.error}</p><button onClick={() => window.location.reload()}>Повторить</button></section></main>
          : <EmptyWorkspace page={route.page} technician={user.role === "technician"}/>
      : null}
  </>
}
