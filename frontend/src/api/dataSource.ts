export interface DataSourceFile {
  name: string
  path?: string
  size_bytes: number
}


export interface DataSourceFiles {
  channels?: DataSourceFile
  events?: DataSourceFile
  objects?: DataSourceFile
}


export type DataSourceState =
  | "disconnected"
  | "preparing"
  | "connected"
  | "error"


export interface DataSourceStatus {
  state: DataSourceState
  connected: boolean
  path: string | null
  files: DataSourceFiles
  error?: string | null
  sensor_count?: number | null
}


export type DataSourceConnectResult =
  DataSourceStatus


const DATA_SOURCE_API =
  "/api/data-source"


function normalizeStatus(
  value: Partial<DataSourceStatus>,
): DataSourceStatus {
  const connected =
    value.connected === true

  return {
    state:
      value.state ??
      (
        connected
          ? "connected"
          : "disconnected"
      ),
    connected,
    path:
      typeof value.path === "string"
        ? value.path
        : null,
    files:
      value.files ?? {},
    error:
      value.error ?? null,
    sensor_count:
      value.sensor_count ?? null,
  }
}


async function readError(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const body = await response.json()

    if (
      body &&
      typeof body.detail === "string"
    ) {
      return body.detail
    }

    if (
      body &&
      body.detail &&
      typeof body.detail.message === "string"
    ) {
      return body.detail.message
    }
  } catch {
    // Use the fallback below.
  }

  return fallback
}


export async function getDataSourceStatus():
Promise<DataSourceStatus> {
  const response = await fetch(
    `${DATA_SOURCE_API}/status`,
  )

  if (!response.ok) {
    throw new Error(
      await readError(
        response,
        `Не удалось проверить источник данных: ${response.status}`,
      ),
    )
  }

  return normalizeStatus(
    await response.json(),
  )
}


export async function connectDataSource(
  path: string,
): Promise<DataSourceConnectResult> {
  const response = await fetch(
    `${DATA_SOURCE_API}/connect`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        path,
      }),
    },
  )

  if (!response.ok) {
    throw new Error(
      await readError(
        response,
        `Не удалось подключить источник: ${response.status}`,
      ),
    )
  }

  return normalizeStatus(
    await response.json(),
  )
}

