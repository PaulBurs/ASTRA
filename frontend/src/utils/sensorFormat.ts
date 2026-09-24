import type { Sensor } from "../api/sensors"


export function formatSensorValue(
  sensor: Sensor,
): string {
  if (sensor.value === null) {
    return "Нет данных"
  }

  switch (sensor.value_type) {
    case "numeric":
      if (typeof sensor.value === "number") {
        return new Intl.NumberFormat(
          "ru-RU",
          {
            maximumFractionDigits: 4,
          },
        ).format(sensor.value)
      }

      return String(sensor.value)

    case "binary":
      if (typeof sensor.value === "number") {
        if (sensor.value === 1) {
          return "1"
        }

        if (sensor.value === 0) {
          return "0"
        }
      }

      return String(sensor.value)

    case "datetime":
      return formatDateTime(
        String(sensor.value),
      )

    case "text":
      return String(sensor.value)

    default:
      return String(sensor.value)
  }
}


export function formatOccurredAt(
  occurredAt: string | null,
): string {
  if (!occurredAt) {
    return "Нет данных"
  }

  return formatDateTime(occurredAt)
}


function formatDateTime(
  value: string,
): string {
  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat(
    "ru-RU",
    {
      dateStyle: "short",
      timeStyle: "medium",
    },
  ).format(date)
}
