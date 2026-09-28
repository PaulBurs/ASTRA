import { useState } from "react"
import type { DatasetImportController } from "../hooks/useDatasetImport"
import { navigate, routeHref } from "../state/navigation"
import "./DatasetImportPanel.css"

const number = (value: number) => value.toLocaleString("ru-RU")
const size = (bytes: number) => bytes >= 1024 ** 3
  ? `${(bytes / 1024 ** 3).toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ГБ`
  : bytes >= 1024 ** 2
    ? `${(bytes / 1024 ** 2).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} МБ`
    : `${number(Math.ceil(bytes / 1024))} КБ`

const roleNames: Record<string, string> = {
  channels: "Справочник каналов", objects: "Справочник объектов",
  events: "Журнал событий", prepared_events: "Подготовленный журнал", states: "Справочник состояний",
}

export default function DatasetImportPanel({ controller }: { controller: DatasetImportController }) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const { files, setFiles, dataset, busy, preparing, percent, currentFile, error,
    setError, importFiles, retryPreparation, retryML, discardUpload, clearDataset } = controller
  const ready = dataset?.status === "ready" || dataset?.status === "prepared"
  const allFilesUploaded = dataset?.status === "uploading"
    && dataset.files.length > 0
    && dataset.files.every(file => file.uploaded)
  const canRetryPreparation = allFilesUploaded
  const displayedFiles = files.length ? files : dataset?.files ?? []
  const totalSize = displayedFiles.reduce((sum, file) => sum + file.size, 0)
  return (
    <main className="warnings-page data-page">
      <div className="warnings-page-heading">
        <h1>Данные</h1>
        <p>Загрузите таблицы и подготовьте набор для ML.</p>
      </div>

      <div className="dataset-layout">
        <div className="dataset-main">
          <section className="dataset-import" aria-labelledby="dataset-import-title">
            <div className="dataset-card-heading">
              <h2 id="dataset-import-title">Таблицы из архива</h2>
              <span className="dataset-format">CSV · 2019–2026</span>
            </div>
            <p className="dataset-description">Выберите журналы событий, справочник каналов и справочник объектов из распакованного архива.</p>
            <label className={`dataset-file-label ${busy || preparing ? "is-disabled" : ""}`}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" /></svg>
              <strong>Выбрать таблицы</strong>
              <span>Можно выбрать несколько CSV-файлов одновременно</span>
              <input type="file" multiple accept=".csv,text/csv" aria-label="Выбрать таблицы" disabled={busy || preparing}
                onChange={event => { setFiles(Array.from(event.target.files ?? [])); setError(null) }} />
            </label>
            {displayedFiles.length > 0 && <>
              <div className="dataset-selection-summary">
                <strong>Файлов: {displayedFiles.length}</strong><span>{size(totalSize)}</span>
              </div>
              <ul className="dataset-file-list" aria-label="Выбранные таблицы">
                {displayedFiles.map(file => <li key={file.name}>
                  <span className="dataset-file-icon" aria-hidden="true">CSV</span>
                  <div><strong>{file.name}</strong>{"role" in file && file.role && <small>{roleNames[file.role] ?? file.role}</small>}</div>
                  <span>{size(file.size)}</span>
                </li>)}
              </ul>
            </>}
            {busy && currentFile && <div className="dataset-progress" aria-live="polite">
              <div><span>Загружается {currentFile}</span><strong>{percent}%</strong></div>
              <progress max={100} value={percent} aria-label="Общий прогресс загрузки" />
            </div>}
            <div className="dataset-actions">
              <button className="dataset-primary" type="button" disabled={busy || preparing || (!canRetryPreparation && files.length < 3)} onClick={() => void importFiles()}>
                {preparing
                  ? "Подготовка данных…"
                  : busy
                    ? "Загрузка…"
                    : canRetryPreparation
                      ? "Повторить запуск подготовки"
                      : "Загрузить и подготовить"}
              </button>
              <span>Обучение запускается отдельно</span>
            </div>
            {error && <p className="dataset-error" role="alert">{error}</p>}
          </section>

          {dataset && <section className="dataset-result" aria-labelledby="dataset-result-title" aria-live="polite">
            <div className="dataset-card-heading">
              <h2 id="dataset-result-title">Подготовка набора</h2>
              <span className={`dataset-badge ${dataset.status === "ready" ? "is-ready" : dataset.status === "error" ? "is-error" : ""}`}>
                {dataset.status === "ready" ? "Готово" : dataset.status === "error" ? "Ошибка" : ready ? "Данные подготовлены" : preparing ? "Обработка" : "Загрузка"}
              </span>
            </div>
            <p className="dataset-stage">{dataset.stage}</p>
            {preparing && <p className="dataset-note">Можно переходить между разделами. После завершения загрузки страницу можно закрыть: подготовка продолжится на сервере. Большой архив может обрабатываться несколько часов.</p>}
            <dl className="dataset-counts">
              {dataset.counts.source_rows !== undefined && <div><dt>Исходных строк</dt><dd>{number(dataset.counts.source_rows)}</dd></div>}
              {dataset.counts.feature_rows !== undefined && <div><dt>Строк для ML</dt><dd>{number(dataset.counts.feature_rows)}</dd></div>}
              {dataset.counts.channels !== undefined && <div><dt>Датчиков в справочнике</dt><dd>{number(dataset.counts.channels)}</dd></div>}
              {dataset.counts.objects !== undefined && <div><dt>Объектов</dt><dd>{number(dataset.counts.objects)}</dd></div>}
            </dl>
            {dataset.counts.duplicate_rows !== undefined && <p className="dataset-note">Удалено дублей: {number(dataset.counts.duplicate_rows)}. Событий без канала в справочнике: {number(dataset.counts.orphan_rows ?? 0)}.</p>}
            {dataset.status === "ready" && <p className="dataset-ready">ML-движок прочитал подготовленные признаки. Обучение не запускалось.</p>}
            {dataset.error && <p role="alert" className="dataset-error">{dataset.error}</p>}
            {dataset.status === "uploading" && !busy && (allFilesUploaded
              ? <p className="dataset-ready">Все файлы загружены. Повторная загрузка не требуется. Запустите подготовку, когда завершится обработка предыдущего набора.</p>
              : <p className="dataset-note">Загрузка файлов не завершена. Удалите этот набор перед новой загрузкой.</p>)}
            <div className="dataset-actions">
              {ready && <a className="dataset-secondary" href={routeHref("warnings")} onClick={event => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
                event.preventDefault(); navigate("warnings")
              }}>Открыть датчики</a>}
              {allFilesUploaded && <button type="button" disabled={busy} onClick={() => void retryPreparation()}>Запустить подготовку</button>}
              {dataset.status === "prepared" && dataset.error && <button type="button" disabled={busy} onClick={() => void retryML()}>Повторить проверку ML</button>}
              {["uploading", "error"].includes(dataset.status) && !busy && <button type="button" onClick={() => void discardUpload()}>Удалить незавершённую загрузку</button>}
              {ready && <button className="dataset-danger" type="button" disabled={busy} onClick={() => setConfirmDelete(true)}>Очистить базу датчиков</button>}
            </div>
            {ready && confirmDelete && <div className="dataset-delete-confirm" role="alertdialog" aria-labelledby="dataset-delete-title" aria-describedby="dataset-delete-description">
              <strong id="dataset-delete-title">Удалить всю загруженную базу?</strong>
              <p id="dataset-delete-description">Будут удалены датчики, события, подготовленные признаки, прогнозы, проверки и загруженные файлы. Восстановить их можно будет только повторной загрузкой таблиц.</p>
              <div className="dataset-actions">
                <button className="dataset-danger-confirm" type="button" disabled={busy} onClick={() => { setConfirmDelete(false); void clearDataset() }}>{busy ? "Удаление…" : "Да, удалить базу"}</button>
                <button type="button" disabled={busy} onClick={() => setConfirmDelete(false)}>Отмена</button>
              </div>
            </div>}
          </section>}
        </div>

        <aside className="dataset-help" aria-labelledby="dataset-help-title">
          <h2 id="dataset-help-title">Что нужно выбрать</h2>
          <ol>
            <li><strong>Журналы событий</strong><span>Один или несколько файлов за нужные годы. Можно использовать уже объединённый журнал.</span></li>
            <li><strong>Справочник каналов</strong><span>Связывает события с датчиками.</span></li>
            <li><strong>Справочник объектов</strong><span>Указывает, где расположены датчики.</span></li>
          </ol>
          <div className="dataset-help-note"><strong>После загрузки</strong><p>Система объединит таблицы, удалит дубли, подготовит признаки и проверит доступ ML-движка к данным.</p></div>
          <p className="dataset-note">Объём базы зависит от выбранных таблиц. Исходные и очищенные события используют общее хранилище. Перед загрузкой проверяется запас места для данных и временных файлов обработки.</p>
        </aside>
      </div>
    </main>
  )
}
