import type { ForecastJob } from "../api/liveWorkspace"

const duration = (seconds: number) => {
  const s = Math.max(0, Math.round(seconds)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60)
  return h ? `${h} ч ${m} мин` : m ? `${m} мин ${s % 60} с` : `${s % 60} с`
}
/** "Прошло 3 мин 10 с · 120 датчиков/мин · осталось ≈ 5 мин" — so a slow run is visible, not guessed. */
export function forecastTiming(job: ForecastJob, now = Date.now()): string {
  if (!job.created_at) return ""
  const start = Date.parse(job.created_at)
  const end = ["running", "stopping"].includes(job.status) ? now : Date.parse(job.updated_at ?? job.created_at)
  const seconds = (end - start) / 1000
  if (!Number.isFinite(seconds) || seconds <= 0) return ""
  const parts = [`${["running", "stopping"].includes(job.status) ? "Прошло" : "Заняло"} ${duration(seconds)}`]
  if (job.completed > 0) {
    const rate = job.completed / seconds
    parts.push(`${Math.round(rate * 60).toLocaleString("ru-RU")} датчиков/мин`)
    if (job.status === "running" && job.completed < job.total) parts.push(`осталось ≈ ${duration((job.total - job.completed) / rate)}`)
  }
  return parts.join(" · ")
}
