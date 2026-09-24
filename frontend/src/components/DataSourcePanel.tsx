import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react"

import {
  connectDataSource,
  getDataSourceStatus,
  type DataSourceFiles,
  type DataSourceState,
  type DataSourceStatus,
} from "../api/dataSource"


interface DataSourcePanelProps {
  onConnected: () => void
}


function formatSize(bytes: number): string {
  if (bytes >= 1024 ** 3) {
    return `${(
      bytes / 1024 ** 3
    ).toFixed(2)} GB`
  }

  if (bytes >= 1024 ** 2) {
    return `${(
      bytes / 1024 ** 2
    ).toFixed(2)} MB`
  }

  if (bytes >= 1024) {
    return `${(
      bytes / 1024
    ).toFixed(1)} KB`
  }

  return `${bytes} B`
}


function DataSourcePanel({
  onConnected,
}: DataSourcePanelProps) {
  const [path, setPath] = useState("")

  const [connectedPath, setConnectedPath] =
    useState<string | null>(null)

  const [files, setFiles] =
    useState<DataSourceFiles>({})

  const [sourceState, setSourceState] =
    useState<DataSourceState>(
      "disconnected",
    )

  const [checking, setChecking] =
    useState(true)

  const [connecting, setConnecting] =
    useState(false)

  const [error, setError] =
    useState<string | null>(null)

  const connectedNotifiedRef =
    useRef(false)


  const notifyConnected = useCallback(() => {
    if (
      connectedNotifiedRef.current
    ) {
      return
    }

    connectedNotifiedRef.current = true
    onConnected()
  }, [onConnected])


  const applyStatus = useCallback((
    status: DataSourceStatus,
  ) => {
    setSourceState(
      status.state
    )

    setFiles(
      status.files
    )

    if (status.path) {
      setPath(
        status.path
      )
    }

    if (
      status.state === "connected"
      && status.connected
      && status.path
    ) {
      setConnectedPath(
        status.path
      )

      setError(null)
      notifyConnected()
      return
    }

    setConnectedPath(null)

    if (status.state === "error") {
      setError(
        status.error
        || "Не удалось подготовить источник данных"
      )
    }
  }, [notifyConnected])


  useEffect(() => {
    getDataSourceStatus()
      .then((status) => {
        applyStatus(
          status
        )

        if (
          status.state !== "error"
        ) {
          setError(null)
        }
      })
      .catch((requestError: unknown) => {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Не удалось проверить источник данных"
        )
      })
      .finally(() => {
        setChecking(false)
      })
  }, [applyStatus])


  useEffect(() => {
    if (
      sourceState !== "preparing"
    ) {
      return
    }

    const intervalId =
      window.setInterval(() => {
        getDataSourceStatus()
          .then((status) => {
            applyStatus(
              status
            )
          })
          .catch((requestError: unknown) => {
            setError(
              requestError instanceof Error
                ? requestError.message
                : "Не удалось проверить подготовку источника"
            )
          })
      }, 1500)

    return () => {
      window.clearInterval(
        intervalId
      )
    }
  }, [
    sourceState,
    applyStatus,
  ])


  async function handleConnect() {
    const normalizedPath =
      path.trim()

    if (!normalizedPath) {
      setError(
        "Укажите путь к каталогу с данными"
      )
      return
    }

    setConnecting(true)
    setError(null)

    connectedNotifiedRef.current =
      false

    try {
      const result =
        await connectDataSource(
          normalizedPath
        )

      applyStatus(
        result
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Не удалось подключить источник данных"
      )
    } finally {
      setConnecting(false)
    }
  }


  const preparing =
    sourceState === "preparing"

  const busy =
    connecting
    || checking
    || preparing

  const shownPath =
    connectedPath
    || (
      preparing
        ? path.trim()
        : null
    )


  return (
    <section className="data-source-panel">
      <div className="data-source-header">
        <div>
          <h2>Источник данных</h2>

          <p>
            Укажите каталог, в котором находятся
            таблицы каналов, объектов и журнал событий.
          </p>
        </div>

        {sourceState === "connected" ? (
          <span className="data-source-connected">
            ● Подключено
          </span>
        ) : sourceState === "preparing" ? (
          <span className="data-source-disconnected">
            ● Подготовка данных
          </span>
        ) : sourceState === "error" ? (
          <span className="data-source-disconnected">
            ● Ошибка
          </span>
        ) : (
          <span className="data-source-disconnected">
            ● Не подключено
          </span>
        )}
      </div>

      <div className="data-source-controls">
        <input
          type="text"
          value={path}
          placeholder="/home/user/data"
          disabled={busy}
          onChange={(event) =>
            setPath(event.target.value)
          }
          onKeyDown={(event) => {
            if (
              event.key === "Enter"
              && !busy
            ) {
              void handleConnect()
            }
          }}
        />

        <button
          type="button"
          disabled={busy}
          onClick={() =>
            void handleConnect()
          }
        >
          {preparing
            ? "Подготовка..."
            : connecting
              ? "Подключение..."
              : connectedPath
                ? "Переподключить"
                : "Подключить"}
        </button>
      </div>

      {checking && (
        <p>
          Проверка текущего источника...
        </p>
      )}

      {preparing && (
        <p>
          ASTRA подготавливает кэш журнала событий.
          На первом запуске большого источника
          это может занять около минуты.
        </p>
      )}

      {error && (
        <div className="data-source-error">
          {error}
        </div>
      )}

      {shownPath && (
        <div className="data-source-info">
          <p>
            <strong>Каталог:</strong>{" "}
            {shownPath}
          </p>

          <div className="data-source-files">
            <SourceFile
              title="Каналы"
              file={files.channels}
            />

            <SourceFile
              title="Объекты"
              file={files.objects}
            />

            <SourceFile
              title="Журнал событий"
              file={files.events}
            />
          </div>
        </div>
      )}
    </section>
  )
}


function SourceFile({
  title,
  file,
}: {
  title: string
  file: DataSourceFiles[
    keyof DataSourceFiles
  ]
}) {
  return (
    <div className="data-source-file">
      <span>{title}</span>

      {file ? (
        <>
          <strong>
            {file.name}
          </strong>

          <small>
            {formatSize(
              file.size_bytes
            )}
          </small>
        </>
      ) : (
        <strong>
          Не найден
        </strong>
      )}
    </div>
  )
}


export default DataSourcePanel

