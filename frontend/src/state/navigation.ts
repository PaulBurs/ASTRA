import { useSyncExternalStore } from "react"
import type { Section } from "../state/models"

export type AppPage = Section | "sensors" | "data" | "notFound"
export interface Route { page: AppPage; id?: string }
const paths: Record<Exclude<AppPage, "notFound">, string> = {
  warnings: "/home", map: "/map",
  checks: "/checks", archive: "/archive", sensors: "/sensors", data: "/data",
}

export function routeHref(page: Exclude<AppPage, "notFound">, id?: string | number) {
  return paths[page] + (id === undefined ? "" : "/" + encodeURIComponent(id))
}

export function parseRoute(pathname: string): Route {
  if (pathname === "/") return { page: "warnings" }
  pathname = pathname.replace(/^\/warnings(?=\/|$)/, "/home").replace(/^\/work-orders(?=\/|$)/, "/archive")
  const parts = pathname.replace(/\/$/, "").split("/").filter(Boolean)
  const page = (Object.keys(paths) as (keyof typeof paths)[]).find((key) => paths[key] === "/" + parts[0])
  if (!page || parts.length > 2 || (parts.length === 2 && (page === "sensors" || page === "data"))) return { page: "notFound" }
  try { return { page, id: parts[1] ? decodeURIComponent(parts[1]) : undefined } }
  catch { return { page: "notFound" } }
}

export function navigate(page: Exclude<AppPage, "notFound">, id?: string | number) {
  const href = routeHref(page, id)
  if (window.location.pathname === href) return
  window.history.pushState(null, "", href)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

function subscribe(onChange: () => void) {
  window.addEventListener("popstate", onChange)
  return () => window.removeEventListener("popstate", onChange)
}

export function useRoute() {
  const pathname = useSyncExternalStore(subscribe, () => window.location.pathname)
  return parseRoute(pathname)
}
