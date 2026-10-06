// Client for the local Python backend (app/api.py). All URLs are relative; in
// development Vite proxies them to http://127.0.0.1:8000. The browser never
// talks to OpenAI and never sees the API key.

/**
 * The six-key shipment result (app/schemas.py). This is exactly what is shown
 * in the JSON panel, copied, and downloaded — nothing else.
 */
export interface ShipmentResult {
  shipDate: string | null // YYYY-MM-DD
  carrier: string | null
  trackingNumbers: string[]
  shippedQuantity: number | null
  lotNumbers: string[]
  serialNumbers: string[]
}

export const SHIPMENT_FIELDS = [
  'shipDate',
  'carrier',
  'trackingNumbers',
  'shippedQuantity',
  'lotNumbers',
  'serialNumbers',
] as const satisfies readonly (keyof ShipmentResult)[]

/** 201 response of POST /api/v1/extractions: operational metadata + the result. */
export interface ExtractionResponse {
  id: string
  download_url: string
  source_file: string
  model: string
  processed_at: string
  result: ShipmentResult
}

/** True only for an object with exactly the six keys and the right value types. */
export function isShipmentResult(value: unknown): value is ShipmentResult {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const v = value as Record<string, unknown>
  const keys = Object.keys(v)
  const isStringList = (x: unknown) => Array.isArray(x) && x.every((item) => typeof item === 'string')
  return (
    keys.length === SHIPMENT_FIELDS.length &&
    SHIPMENT_FIELDS.every((k) => k in v) &&
    (v.shipDate === null || typeof v.shipDate === 'string') &&
    (v.carrier === null || typeof v.carrier === 'string') &&
    (v.shippedQuantity === null || typeof v.shippedQuantity === 'number') &&
    isStringList(v.trackingNumbers) &&
    isStringList(v.lotNumbers) &&
    isStringList(v.serialNumbers)
  )
}

export interface HealthResponse {
  status: string
  model: string
  api_key_configured: boolean
}

export const EXTRACTIONS_URL = '/api/v1/extractions'
export const HEALTH_URL = '/health'

const BACKEND_START_HINT =
  'Start it in a terminal from the project folder with: ' +
  'python -m uvicorn app.api:app --host 127.0.0.1 --port 8000'

/** Any failed request, with a message that is safe and useful to show the user. */
export class ApiError extends Error {
  readonly status: number | null
  readonly code: string

  constructor(message: string, code: string, status: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request(input: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(input, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(`Could not reach the backend. Is the Python server running? ${BACKEND_START_HINT}`, 'network_error')
  }
  if (!response.ok) throw await errorFromResponse(response)
  return response
}

/** Builds an ApiError from a failed response, whether or not its body is JSON. */
export async function errorFromResponse(response: Response): Promise<ApiError> {
  const text = await response.text().catch(() => '')
  try {
    const body = JSON.parse(text) as { error?: { code?: unknown; message?: unknown } }
    if (typeof body.error?.message === 'string' && typeof body.error.code === 'string') {
      return new ApiError(body.error.message, body.error.code, response.status)
    }
  } catch {
    // Not JSON (e.g. an HTML error page from a proxy); fall through.
  }
  if ([500, 502, 503, 504].includes(response.status) && !text.trim().startsWith('{')) {
    return new ApiError(
      `The backend did not respond properly (HTTP ${response.status}). It may not be running. ${BACKEND_START_HINT}`,
      'backend_unavailable',
      response.status,
    )
  }
  return new ApiError(`The request failed (HTTP ${response.status}).`, 'http_error', response.status)
}

async function readJson<T>(response: Response): Promise<T> {
  try {
    return (await response.json()) as T
  } catch {
    throw new ApiError('The backend sent a response that was not valid JSON.', 'invalid_response', response.status)
  }
}

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return readJson<HealthResponse>(await request(HEALTH_URL, { signal }))
}

/** Uploads one image and waits for the (paid) extraction. Never retried automatically. */
export async function extractImage(file: File): Promise<ExtractionResponse> {
  const form = new FormData()
  form.append('file', file, file.name)
  const body = await readJson<ExtractionResponse>(await request(EXTRACTIONS_URL, { method: 'POST', body: form }))
  if (
    typeof body?.id !== 'string' ||
    typeof body.download_url !== 'string' ||
    typeof body.source_file !== 'string' ||
    !isShipmentResult(body.result)
  ) {
    throw new ApiError('The backend response did not have the expected shape.', 'invalid_response')
  }
  return body
}

/** Fetches the saved JSON file from the backend's download endpoint. */
export async function downloadExtraction(downloadUrl: string): Promise<Blob> {
  return (await request(downloadUrl)).blob()
}
