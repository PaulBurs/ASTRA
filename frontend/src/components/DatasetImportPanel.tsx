import { useEffect, useRef, useState } from "react"
import {
  createDataset, discardDataset, getDataset, prepareDataset, uploadDatasetFile,
  validateDatasetML, type Dataset,
} from "../api/datasets"
import "./DatasetImportPanel.css"

const SAVED_DATASET = "astra.preparedDataset"
const number = (value: number) => value.toLocaleString("ru-RU")

interface Props {
  onReady: (datasetId: string) => void
}

export default function DatasetImportPanel({ onReady }: Props) {
  const [files, setFiles] = useState<File[]>([])
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [busy, setBusy] = useState(false)
  const [percent, setPercent] = useState(0)
  const [currentFile, setCurrentFile] = useState("")
  const [error, setError] = useState<string | null>(null)
  const callback = useRef(onReady)
  callback.current = onReady
  const notified = useRef<string | null>(null)
  const checkingML = dataset?.status === "prepared" && !dataset.error

  useEffect(() => {
    const id = localStorage.getItem(SAVED_DATASET)
    if (id) {
      getDataset(id).then(setDataset).catch(() => {
        localStorage.removeItem(SAVED_DATASET)
      })
    }
  }, [])

  useEffect(() => {
    if (!dataset || (dataset.status !== "preparing" && !checkingML)) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const updated = await getDataset(dataset.id)
        if (!disposed) { setDataset(updated); setError(null) }
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : "Не удалось проверить подготовку")
      } finally {
        if (!disposed) timer = setTimeout(poll, 2000)
      }
    }
    timer = setTimeout(poll, 1000)
    return () => { disposed = true; clearTimeout(timer) }
  }, [dataset?.id, dataset?.status, checkingML])

  useEffect(() => {
    if (dataset && ["prepared", "ready"].includes(dataset.status) && notified.current !== dataset.id) {
      notified.current = dataset.id
      callback.current(dataset.id)
    }
  }, [dataset])

  async function importFiles() {
    setBusy(true)
    setError(null)
    setPercent(0)
    try {
      if (dataset && ["uploading", "error"].includes(dataset.status)) {
        await discardDataset(dataset.id)
        localStorage.removeItem(SAVED_DATASET)
        setDataset(null)
      }
      let job = await createDataset(files)
      setDataset(job)
      localStorage.setItem(SAVED_DATASET, job.id)
      const total = files.reduce((sum, file) => sum + file.size, 0)
      let completed = 0
      for (const [index, file] of files.entries()) {
        setCurrentFile(file.name)
        job = await uploadDatasetFile(job.id, index, file, bytes => {
          setPercent(Math.min(100, Math.round((completed + bytes) / total * 100)))
        })
        completed += file.size
        setDataset(job)
      }
      setCurrentFile("")
      setDataset(await prepareDataset(job.id))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось подготовить данные")
    } finally {
      setCurrentFile("")
      setBusy(false)
    }
  }

  async function discardUpload() {
    if (!dataset) return
    setBusy(true)
    try {
      await discardDataset(dataset.id)
      localStorage.removeItem(SAVED_DATASET)
      setDataset(null)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось удалить загрузку")
    } finally { setBusy(false) }
  }

  async function retryML() {
    if (!dataset) return
    setBusy(true)
    setError(null)
    try { setDataset(await validateDatasetML(dataset.id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : "ML-сервис недоступен") }
    finally { setBusy(false) }
  }

  const preparing = dataset?.status === "preparing" || checkingML
  return (
    <section className="dataset-import" aria-labelledby="dataset-import-title">
      <h2 id="dataset-import-title">Подготовить данные для ML</h2>
      <p>Выберите CSV-журналы событий за нужные годы, справочник каналов и справочник объектов из распакованного архива.</p>
      <label className="dataset-file-label">
        Выбрать таблицы
        <input type="file" multiple accept=".csv,text/csv" disabled={busy || preparing}
          onChange={event => { setFiles(Array.from(event.target.files ?? [])); setError(null) }} />
      </label>
      {files.length > 0 && (
        <ul className="dataset-file-list">
          {files.map(file => <li key={file.name}>{file.name} <span>{number(Math.ceil(file.size / 1024))} КБ</span></li>)}
        </ul>
      )}
      <button disabled={busy || preparing || files.length < 3} onClick={() => void importFiles()}>
        {preparing ? "Подготовка данных…" : busy ? "Загрузка…" : "Загрузить и подготовить"}
      </button>
      <p className="dataset-note">Журналы будут объединены, очищены от дублей и преобразованы в признаки. Обучение запускается отдельно.</p>
      {busy && currentFile && (
        <div aria-live="polite">
          <p>Загружается {currentFile}: {percent}% общего объёма</p>
          <progress max={100} value={percent} aria-label="Загрузка файлов" />
        </div>
      )}
      {dataset && (
        <div className="dataset-status" aria-live="polite">
          <strong>{dataset.stage}</strong>
          {preparing && <p>Большой архив может обрабатываться несколько часов. Страницу можно закрыть и открыть снова.</p>}
          <dl>
            {dataset.counts.source_rows !== undefined && <><dt>Обработано исходных строк</dt><dd>{number(dataset.counts.source_rows)}</dd></>}
            {dataset.counts.event_rows !== undefined && <><dt>Очищенных событий</dt><dd>{number(dataset.counts.event_rows)}</dd></>}
            {dataset.counts.duplicate_rows !== undefined && <><dt>Удалено дублей</dt><dd>{number(dataset.counts.duplicate_rows)}</dd></>}
            {dataset.counts.orphan_rows !== undefined && <><dt>Событий без канала в справочнике</dt><dd>{number(dataset.counts.orphan_rows)}</dd></>}
            {dataset.counts.feature_rows !== undefined && <><dt>Строк для ML</dt><dd>{number(dataset.counts.feature_rows)}</dd></>}
          </dl>
          {dataset.status === "ready" && <p className="dataset-ready">ML-движок прочитал подготовленные признаки. Обучение не запускалось.</p>}
          {dataset.status === "prepared" && dataset.error && <button disabled={busy} onClick={() => void retryML()}>Повторить проверку ML</button>}
          {dataset.error && <p role="alert" className="error-message">{dataset.error}</p>}
          {dataset.status === "uploading" && !busy && <p>Загрузка не завершена. Выберите файлы заново для новой загрузки.</p>}
          {["uploading", "error"].includes(dataset.status) && !busy && (
            <button onClick={() => void discardUpload()}>Удалить незавершённую загрузку</button>
          )}
        </div>
      )}
      {error && <p className="error-message" role="alert">{error}</p>}
    </section>
  )
}
