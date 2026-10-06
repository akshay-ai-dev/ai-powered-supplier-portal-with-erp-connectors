// UI tests with a mocked fetch. No backend, no OpenAI calls, no charges.
// The mocked responses follow the backend's documented shapes (app/api.py).

import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { ExtractionResponse, ShipmentResult } from './api'

const SIX_KEYS = ['shipDate', 'carrier', 'trackingNumbers', 'shippedQuantity', 'lotNumbers', 'serialNumbers']

const EXTRACTION: ExtractionResponse = {
  id: 'a'.repeat(32),
  download_url: `/api/v1/extractions/${'a'.repeat(32)}/download`,
  source_file: 'invoice.png',
  model: 'test-model',
  processed_at: '2026-10-05T12:00:00+00:00',
  result: {
    shipDate: '2026-03-04',
    carrier: 'UPS Ground',
    trackingNumbers: ['1Z999AA10123456784', '0012-3456'],
    shippedQuantity: 120,
    lotNumbers: ['000123', 'LOT-77/B'],
    serialNumbers: ['SN-0001'],
  },
}

const EMPTY_RESULT: ShipmentResult = {
  shipDate: null,
  carrier: null,
  trackingNumbers: [],
  shippedQuantity: null,
  lotNumbers: [],
  serialNumbers: [],
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => (resolve = r))
  return { promise, resolve }
}

type Handler = (init?: RequestInit) => Response | Promise<Response>

/** Routes fetch calls by URL. Unrouted URLs fail the test. */
function mockBackend(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const handler = routes[url]
    if (!handler) throw new Error(`Unexpected fetch: ${url}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  const calls = (url: string) => fetchMock.mock.calls.filter(([u]) => u === url)
  return { fetchMock, calls }
}

const health: Handler = () => json({ status: 'ok', model: 'test-model', api_key_configured: true })

function png(name = 'invoice.png', size = 2048, type = 'image/png') {
  return new File([new Uint8Array(size)], name, { type })
}

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>

beforeEach(() => {
  let n = 0
  createObjectURL = vi.fn(() => `blob:mock-${++n}`)
  revokeObjectURL = vi.fn()
  Object.assign(URL, { createObjectURL, revokeObjectURL })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

async function selectImage(user: ReturnType<typeof userEvent.setup>, file = png()) {
  await user.upload(screen.getByLabelText('Image file'), file)
}

describe('Image to JSON', () => {
  it('shows the title, backend status, and a disabled Extract button before an image is chosen', async () => {
    mockBackend({ '/health': health })
    render(<App />)
    expect(screen.getByRole('heading', { level: 1, name: 'Image to JSON' })).toBeInTheDocument()
    expect(await screen.findByText(/Backend connected · model test-model/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extract JSON' })).toBeDisabled()
    expect(screen.getByText(/sent through your local backend to OpenAI/)).toBeInTheDocument()
  })

  it('selecting an image shows a preview, name, and size without starting extraction', async () => {
    const { calls } = mockBackend({ '/health': health })
    const user = userEvent.setup()
    render(<App />)

    await selectImage(user, png('scan one.png', 2048))

    expect(screen.getByRole('img', { name: 'Preview of scan one.png' })).toHaveAttribute('src', 'blob:mock-1')
    expect(screen.getByText('scan one.png')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extract JSON' })).toBeEnabled()
    expect(calls('/api/v1/extractions')).toHaveLength(0)
  })

  it('uploads the image as multipart field "file", shows progress, then renders the six fields and JSON', async () => {
    const pending = deferred<Response>()
    const { calls } = mockBackend({ '/health': health, '/api/v1/extractions': () => pending.promise })
    const user = userEvent.setup()
    render(<App />)
    const file = png()
    await selectImage(user, file)

    const extract = screen.getByRole('button', { name: 'Extract JSON' })
    await user.click(extract)

    // While waiting: indicator shown, no percentages, duplicate submissions blocked.
    expect(screen.getByText(/Extracting… OpenAI is reading the image/)).toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
    const busyButton = screen.getByRole('button', { name: 'Extracting…' })
    expect(busyButton).toBeDisabled()
    await user.click(busyButton)
    expect(screen.getByRole('button', { name: 'Clear' })).toBeDisabled()
    expect(calls('/api/v1/extractions')).toHaveLength(1)

    const [, init] = calls('/api/v1/extractions')[0]
    expect(init?.method).toBe('POST')
    const body = init?.body as FormData
    expect(body.get('file')).toBeInstanceOf(File)
    expect((body.get('file') as File).name).toBe('invoice.png')

    await act(async () => pending.resolve(json(EXTRACTION, 201)))

    // The JSON panel shows only the six-key result, never the envelope metadata.
    const output = await screen.findByTestId('json-output')
    const shown = JSON.parse(output.textContent ?? '')
    expect(shown).toEqual(EXTRACTION.result)
    expect(Object.keys(shown)).toEqual(SIX_KEYS)
    expect(output.textContent).not.toContain('test-model')

    // All six fields are listed, with identifiers (leading zeros intact) as list items.
    const fields = screen.getByRole('region', { name: 'Shipment fields' })
    expect(within(fields).getAllByRole('term')).toHaveLength(6)
    expect(screen.getByTestId('field-shipDate')).toHaveTextContent('2026-03-04')
    expect(screen.getByTestId('field-carrier')).toHaveTextContent('UPS Ground')
    expect(screen.getByTestId('field-shippedQuantity')).toHaveTextContent('120')
    expect(within(screen.getByTestId('field-lotNumbers')).getAllByRole('listitem').map((li) => li.textContent)).toEqual(
      ['000123', 'LOT-77/B'],
    )
    expect(within(screen.getByTestId('field-trackingNumbers')).getAllByRole('listitem')).toHaveLength(2)
    // Metadata is shown separately from the result.
    expect(screen.getByText('Model: test-model')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extract JSON' })).toBeEnabled()
  })

  it('shows every field even when values are missing', async () => {
    mockBackend({
      '/health': health,
      '/api/v1/extractions': () => json({ ...EXTRACTION, result: EMPTY_RESULT }, 201),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))

    const output = await screen.findByTestId('json-output')
    expect(JSON.parse(output.textContent ?? '')).toEqual(EMPTY_RESULT)
    for (const key of ['shipDate', 'carrier', 'shippedQuantity']) {
      expect(screen.getByTestId(`field-${key}`)).toHaveTextContent('Not found')
    }
    for (const key of ['trackingNumbers', 'lotNumbers', 'serialNumbers']) {
      expect(screen.getByTestId(`field-${key}`)).toHaveTextContent('None found')
    }
  })

  it('rejects a backend response that does not match the six-key contract', async () => {
    mockBackend({
      '/health': health,
      '/api/v1/extractions': () => json({ ...EXTRACTION, result: { ...EXTRACTION.result, warnings: [] } }, 201),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('did not have the expected shape')
    expect(screen.queryByTestId('json-output')).not.toBeInTheDocument()
  })

  it('shows the backend error message and does not retry automatically', async () => {
    const { calls } = mockBackend({
      '/health': health,
      '/api/v1/extractions': () =>
        json({ error: { code: 'invalid_image', message: 'The image could not be used: animated images are not supported.' } }, 422),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('animated images are not supported')
    expect(screen.queryByTestId('json-output')).not.toBeInTheDocument()
    expect(calls('/api/v1/extractions')).toHaveLength(1)
  })

  it('handles non-JSON error responses (e.g. proxy error page)', async () => {
    mockBackend({
      '/health': health,
      '/api/v1/extractions': () => new Response('<html>Bad Gateway</html>', { status: 502 }),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('HTTP 502')
    expect(alert).toHaveTextContent('python -m uvicorn app.api:app')
  })

  it('handles network failures', async () => {
    const { calls } = mockBackend({
      '/health': health,
      '/api/v1/extractions': () => Promise.reject(new TypeError('Failed to fetch')),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the backend')
    expect(calls('/api/v1/extractions')).toHaveLength(1)
  })

  it('warns when the backend is unreachable or has no API key', async () => {
    mockBackend({ '/health': () => Promise.reject(new TypeError('Failed to fetch')) })
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the backend')
    cleanup()

    mockBackend({ '/health': () => json({ status: 'ok', model: 'm', api_key_configured: false }) })
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent("Add OPENAI_API_KEY to the project's .env")
  })

  it('rejects unsupported and oversized files without calling the backend', async () => {
    const { calls } = mockBackend({ '/health': health })
    const user = userEvent.setup({ applyAccept: false })
    render(<App />)

    await selectImage(user, new File(['GIF89a'], 'anim.gif', { type: 'image/gif' }))
    expect(screen.getByRole('alert')).toHaveTextContent('not a supported image')

    await selectImage(user, png('huge.png', 21 * 1024 * 1024))
    expect(screen.getByRole('alert')).toHaveTextContent('The limit is 20.0 MB')

    expect(screen.getByRole('button', { name: 'Extract JSON' })).toBeDisabled()
    expect(calls('/api/v1/extractions')).toHaveLength(0)
  })

  it('selecting a different image clears stale results and revokes the old preview URL', async () => {
    mockBackend({ '/health': health, '/api/v1/extractions': () => json(EXTRACTION, 201) })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user, png('first.png'))
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    await screen.findByTestId('json-output')

    await selectImage(user, png('second.jpg', 100, 'image/jpeg'))

    expect(screen.queryByTestId('json-output')).not.toBeInTheDocument()
    expect(screen.getByText('Results will appear here after you click Extract JSON.')).toBeInTheDocument()
    expect(screen.getByText('second.jpg')).toBeInTheDocument()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-1')
  })

  it('accepts a single dropped image and rejects multiple', async () => {
    mockBackend({ '/health': health })
    render(<App />)
    const dropzone = screen.getByTestId('dropzone')

    fireEvent.drop(dropzone, { dataTransfer: { files: [png('a.png'), png('b.png')] } })
    expect(screen.getByRole('alert')).toHaveTextContent('Drop one image at a time.')

    fireEvent.drop(dropzone, { dataTransfer: { files: [png('dropped.webp', 10, 'image/webp')] } })
    expect(screen.getByText('dropped.webp')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('Download JSON fetches the backend download URL and saves it with the source file name', async () => {
    const { calls } = mockBackend({
      '/health': health,
      '/api/v1/extractions': () => json(EXTRACTION, 201),
      [EXTRACTION.download_url]: () => json(EXTRACTION.result),
    })
    const clicked: HTMLAnchorElement[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    await user.click(await screen.findByRole('button', { name: 'Download JSON' }))

    await waitFor(() => expect(clicked).toHaveLength(1))
    expect(calls(EXTRACTION.download_url)).toHaveLength(1)
    expect(clicked[0].download).toBe('invoice.png.json')
    expect(clicked[0].href).toMatch(/^blob:mock-/)
    expect(await screen.findByText('Downloaded invoice.png.json.')).toBeInTheDocument()

    // The saved file is the backend's six-key result, with no metadata.
    const blob = createObjectURL.mock.calls.at(-1)?.[0] as Blob
    const saved = JSON.parse(await blob.text())
    expect(saved).toEqual(EXTRACTION.result)
    expect(Object.keys(saved)).toEqual(SIX_KEYS)
  })

  it('shows an error when the download fails', async () => {
    mockBackend({
      '/health': health,
      '/api/v1/extractions': () => json(EXTRACTION, 201),
      [EXTRACTION.download_url]: () => json({ error: { code: 'not_found', message: 'No saved extraction has this ID.' } }, 404),
    })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    await user.click(await screen.findByRole('button', { name: 'Download JSON' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('No saved extraction has this ID.')
  })

  it('Copy JSON writes the formatted result to the clipboard', async () => {
    mockBackend({ '/health': health, '/api/v1/extractions': () => json(EXTRACTION, 201) })
    const user = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    await user.click(await screen.findByRole('button', { name: 'Copy JSON' }))

    expect(writeText).toHaveBeenCalledWith(JSON.stringify(EXTRACTION.result, null, 2))
    const copied = JSON.parse(writeText.mock.calls[0][0])
    expect(Object.keys(copied)).toEqual(SIX_KEYS)
    expect(copied).not.toHaveProperty('model')
    expect(copied).not.toHaveProperty('source_file')
    expect(await screen.findByText('JSON copied to the clipboard.')).toBeInTheDocument()
  })

  it('Clear removes the image and results and is keyboard operable', async () => {
    mockBackend({ '/health': health, '/api/v1/extractions': () => json(EXTRACTION, 201) })
    const user = userEvent.setup()
    render(<App />)
    await selectImage(user)
    await user.click(screen.getByRole('button', { name: 'Extract JSON' }))
    await screen.findByTestId('json-output')

    screen.getByRole('button', { name: 'Clear' }).focus()
    await user.keyboard('{Enter}')

    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.queryByTestId('json-output')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Extract JSON' })).toBeDisabled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock-1')
  })
})
