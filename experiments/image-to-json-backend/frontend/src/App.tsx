import { useEffect, useRef, useState, type DragEvent } from 'react'
import {
  ApiError,
  downloadExtraction,
  extractImage,
  getHealth,
  SHIPMENT_FIELDS,
  type ExtractionResponse,
  type HealthResponse,
  type ShipmentResult,
} from './api'
import { ACCEPT_ATTRIBUTE, checkImageFile, formatBytes } from './files'

type Health = { state: 'checking' } | { state: 'ok'; data: HealthResponse } | { state: 'unreachable'; message: string }

function messageFor(err: unknown): string {
  return err instanceof ApiError ? err.message : 'Something went wrong. Please try again.'
}

export default function App() {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [response, setResponse] = useState<ExtractionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [health, setHealth] = useState<Health>({ state: 'checking' })

  const inputRef = useRef<HTMLInputElement>(null)
  const resultsHeadingRef = useRef<HTMLHeadingElement>(null)
  const inFlight = useRef(false) // blocks double-clicks before React re-renders
  const selection = useRef(0) // ignores responses for an image that is no longer selected

  // One object URL per selected file, revoked when the file changes or on unmount.
  // Creating it inside the effect (not useMemo) keeps create/revoke paired, even
  // when StrictMode mounts twice; the object URL is an external resource.
  useEffect(() => {
    if (!file) {
      // oxlint-disable-next-line react/set-state-in-effect
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    // oxlint-disable-next-line react/set-state-in-effect
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  useEffect(() => {
    const controller = new AbortController()
    getHealth(controller.signal)
      .then((data) => setHealth({ state: 'ok', data }))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) setHealth({ state: 'unreachable', message: messageFor(err) })
      })
    return () => controller.abort()
  }, [])

  // Stop the browser from opening an image that is dropped outside the drop area.
  useEffect(() => {
    const prevent = (e: Event) => e.preventDefault()
    window.addEventListener('dragover', prevent)
    window.addEventListener('drop', prevent)
    return () => {
      window.removeEventListener('dragover', prevent)
      window.removeEventListener('drop', prevent)
    }
  }, [])

  function showError(message: string) {
    setNotice(null)
    setError(message)
  }

  function showNotice(message: string) {
    setError(null)
    setNotice(message)
  }

  function selectFile(next: File) {
    if (inFlight.current) return
    const problem = checkImageFile(next)
    if (problem) {
      showError(problem)
      return
    }
    selection.current += 1
    setFile(next)
    setResponse(null)
    setError(null)
    setNotice(null)
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragActive(false)
    if (inFlight.current) return
    const dropped = e.dataTransfer.files
    if (dropped.length === 0) return
    if (dropped.length > 1) {
      showError('Drop one image at a time.')
      return
    }
    selectFile(dropped[0])
  }

  function handleClear() {
    if (inFlight.current) return
    selection.current += 1
    setFile(null)
    setResponse(null)
    setError(null)
    setNotice(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function handleExtract() {
    if (!file || inFlight.current) return
    inFlight.current = true
    const current = selection.current
    setExtracting(true)
    setResponse(null)
    setError(null)
    setNotice(null)
    try {
      const result = await extractImage(file)
      if (current === selection.current) {
        setResponse(result)
        setNotice('Extraction finished. Check the values against the original image.')
        requestAnimationFrame(() => resultsHeadingRef.current?.focus())
      }
    } catch (err) {
      if (current === selection.current) showError(messageFor(err))
    } finally {
      inFlight.current = false
      setExtracting(false)
    }
  }

  async function handleCopy() {
    if (!response) return
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable')
      await navigator.clipboard.writeText(JSON.stringify(response.result, null, 2))
      showNotice('JSON copied to the clipboard.')
    } catch {
      showError('Could not copy automatically. Click inside the JSON panel, select all, and copy manually.')
    }
  }

  async function handleDownload() {
    if (!response || downloading) return
    setDownloading(true)
    try {
      const blob = await downloadExtraction(response.download_url)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${response.source_file}.json`
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      showNotice(`Downloaded ${link.download}.`)
    } catch (err) {
      showError(messageFor(err))
    } finally {
      setDownloading(false)
    }
  }

  const json = response ? JSON.stringify(response.result, null, 2) : ''

  return (
    <div className="page">
      <header className="header">
        <h1>Image to JSON</h1>
        <p className="lede">
          Extract six shipment fields (ship date, carrier, tracking numbers, shipped quantity, lot numbers, and
          serial numbers) from one image. When you click{' '}
          <strong>Extract JSON</strong>, the selected image is sent through your local backend to OpenAI for
          processing, which may incur API charges.
        </p>
        <HealthBanner health={health} />
      </header>

      <div className="messages">
        {error && (
          <div className="message message-error" role="alert">
            {error}
          </div>
        )}
        {/* Always rendered so screen readers announce changes to it. */}
        <div className={notice ? 'message message-notice' : 'visually-hidden'} role="status" aria-live="polite">
          {notice}
        </div>
      </div>

      <main className="layout">
        <section className="panel" aria-labelledby="image-heading">
          <h2 id="image-heading">Image</h2>

          <div
            className={`dropzone${dragActive ? ' dropzone-active' : ''}${extracting ? ' dropzone-disabled' : ''}`}
            data-testid="dropzone"
            onDragEnter={(e) => {
              e.preventDefault()
              if (!extracting) setDragActive(true)
            }}
            onDragOver={(e) => e.preventDefault()}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragActive(false)
            }}
            onDrop={handleDrop}
          >
            {previewUrl && file ? (
              <img className="preview" src={previewUrl} alt={`Preview of ${file.name}`} />
            ) : (
              <p className="dropzone-text">Drag and drop an image here, or</p>
            )}
            <button
              type="button"
              className="button button-secondary"
              onClick={() => inputRef.current?.click()}
              disabled={extracting}
            >
              {file ? 'Choose a different image' : 'Choose image'}
            </button>
            <input
              ref={inputRef}
              className="visually-hidden"
              type="file"
              accept={ACCEPT_ATTRIBUTE}
              aria-label="Image file"
              tabIndex={-1}
              disabled={extracting}
              onChange={(e) => {
                const chosen = e.target.files?.[0]
                e.target.value = '' // allow choosing the same file again later
                if (chosen) selectFile(chosen)
              }}
            />
            <p className="hint">PNG, JPEG, or static WEBP · up to 20 MB · one image at a time</p>
          </div>

          {file && (
            <dl className="file-info">
              <div>
                <dt>File</dt>
                <dd className="filename">{file.name}</dd>
              </div>
              <div>
                <dt>Size</dt>
                <dd>{formatBytes(file.size)}</dd>
              </div>
            </dl>
          )}

          <div className="actions">
            <button
              type="button"
              className="button button-primary"
              onClick={handleExtract}
              disabled={!file || extracting}
              aria-describedby="extract-note"
            >
              {extracting ? 'Extracting…' : 'Extract JSON'}
            </button>
            <button
              type="button"
              className="button button-secondary"
              onClick={handleClear}
              disabled={extracting || (!file && !response && !error)}
            >
              Clear
            </button>
          </div>
          <p id="extract-note" className="hint">
            Extraction starts only when you click Extract JSON. Each extraction is a paid OpenAI request.
          </p>
        </section>

        <section className="panel" aria-labelledby="results-heading" aria-busy={extracting}>
          <h2 id="results-heading" ref={resultsHeadingRef} tabIndex={-1}>
            Results
          </h2>

          {extracting && (
            <div className="processing" role="status">
              <span className="spinner" aria-hidden="true" />
              <span>Extracting… OpenAI is reading the image. This can take up to a minute; please keep this page open.</span>
            </div>
          )}

          {!extracting && !response && (
            <p className="placeholder">Results will appear here after you click Extract JSON.</p>
          )}

          {response && (
            <>
              <p className="meta">
                <span>{response.source_file}</span>
                <span>Model: {response.model}</span>
                <span>Processed: {new Date(response.processed_at).toLocaleString()}</span>
              </p>

              <div className="actions">
                <button type="button" className="button button-secondary" onClick={handleCopy}>
                  Copy JSON
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={handleDownload}
                  disabled={downloading}
                >
                  {downloading ? 'Downloading…' : 'Download JSON'}
                </button>
              </div>

              <ShipmentFields result={response.result} />
              <p className="hint check-note">
                The model can misread or miss values. Always check them against the original image.
              </p>

              <section aria-labelledby="json-heading">
                <h3 id="json-heading">JSON</h3>
                <pre className="json" tabIndex={0} aria-label="Extracted JSON" data-testid="json-output">
                  {json}
                </pre>
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  )
}

const FIELD_LABELS: Record<(typeof SHIPMENT_FIELDS)[number], string> = {
  shipDate: 'Ship date',
  carrier: 'Carrier',
  trackingNumbers: 'Tracking numbers',
  shippedQuantity: 'Shipped quantity',
  lotNumbers: 'Lot numbers',
  serialNumbers: 'Serial numbers',
}

/** All six fields, always shown, including missing values. */
function ShipmentFields({ result }: { result: ShipmentResult }) {
  return (
    <section className="fields-section" aria-labelledby="fields-heading">
      <h3 id="fields-heading">Shipment fields</h3>
      <dl className="shipment-fields">
        {SHIPMENT_FIELDS.map((key) => {
          const value = result[key]
          let content
          if (Array.isArray(value)) {
            content =
              value.length > 0 ? (
                <ul className="identifiers">
                  {value.map((id) => (
                    <li key={id}>
                      <code>{id}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="missing">None found</span>
              )
          } else if (value === null) {
            content = <span className="missing">Not found</span>
          } else {
            content = key === 'carrier' ? value : <code>{value}</code>
          }
          return (
            <div key={key} className="shipment-field" data-testid={`field-${key}`}>
              <dt>
                {FIELD_LABELS[key]} <span className="field-key">{key}</span>
              </dt>
              <dd>{content}</dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}

function HealthBanner({ health }: { health: Health }) {
  if (health.state === 'checking') {
    return <p className="health">Checking the backend…</p>
  }
  if (health.state === 'unreachable') {
    return (
      <p className="health health-warn" role="alert">
        {health.message}
      </p>
    )
  }
  if (!health.data.api_key_configured) {
    return (
      <p className="health health-warn" role="alert">
        The backend is running, but no OpenAI API key is configured. Add OPENAI_API_KEY to the project's .env
        file, then restart the backend.
      </p>
    )
  }
  return <p className="health health-ok">Backend connected · model {health.data.model}</p>
}
