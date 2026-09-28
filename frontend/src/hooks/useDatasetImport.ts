import { useEffect, useRef, useState } from "react"
import {
  createDataset, deletePreparedDataset, discardDataset, getDataset, prepareDataset, uploadDatasetFile,
  validateDatasetML, type Dataset,
} from "../api/datasets"

const SAVED_DATASET = "astra.preparedDataset"

// Mounted in App so uploads and status polling survive navigation between pages.
export function useDatasetImport(onReady: (datasetId: string) => void, employeeId = "") {
  const [files, setFiles] = useState<File[]>([])
  const [dataset, setDataset] = useState<Dataset | null>(null)
  const [busy, setBusy] = useState(false)
  const [percent, setPercent] = useState(0)
  const [currentFile, setCurrentFile] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(() => !!localStorage.getItem(SAVED_DATASET))
  const callback = useRef(onReady)
  useEffect(() => { callback.current = onReady }, [onReady])
  const notified = useRef<string | null>(null)
  const checkingML = dataset?.status === "prepared" && !dataset.error
  const pollingId = dataset?.id
  const shouldPoll = dataset?.status === "preparing" || checkingML

  useEffect(() => {
    let active = true
    const id = localStorage.getItem(SAVED_DATASET)
    if (id) {
      getDataset(id).then(value => { if (active) setDataset(value) }).catch(cause => {
        if (active) setError(cause instanceof Error ? cause.message : "Не удалось открыть загруженную базу")
      }).finally(() => { if (active) setRestoring(false) })
    }
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!pollingId || !shouldPoll) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const updated = await getDataset(pollingId)
        if (!disposed) { setDataset(updated); setError(null) }
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : "Не удалось проверить подготовку")
      } finally {
        if (!disposed) timer = setTimeout(poll, 2000)
      }
    }
    timer = setTimeout(poll, 1000)
    return () => { disposed = true; clearTimeout(timer) }
  }, [pollingId, shouldPoll])

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
      const uploadedDataset = dataset?.status === "uploading"
        && dataset.files.length > 0
        && dataset.files.every(file => file.uploaded)
      if (uploadedDataset) {
        setDataset(await prepareDataset(dataset.id))
        return
      }
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
      // The server now owns complete copies. Clearing browser File objects makes
      // a later click retry preparation instead of uploading gigabytes again.
      setFiles([])
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

  async function clearDataset() {
    if (!dataset || !["prepared", "ready"].includes(dataset.status)) return
    setBusy(true)
    setError(null)
    try {
      await deletePreparedDataset(dataset.id, employeeId)
      localStorage.removeItem(SAVED_DATASET)
      notified.current = null
      setDataset(null)
      setFiles([])
      setPercent(0)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось удалить базу датчиков")
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

  async function retryPreparation() {
    if (!dataset || dataset.status !== "uploading") return
    setBusy(true)
    setError(null)
    try { setDataset(await prepareDataset(dataset.id)) }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось запустить подготовку") }
    finally { setBusy(false) }
  }

  const preparing = dataset?.status === "preparing" || checkingML

  return {
    files, setFiles, dataset, busy, preparing, restoring, percent, currentFile, error,
    setError, importFiles, retryPreparation, retryML, discardUpload, clearDataset,
  }
}

export type DatasetImportController = ReturnType<typeof useDatasetImport>
