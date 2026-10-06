// Client-side checks that mirror the backend (app/image_processing.py, app/config.py).
// The backend still validates everything; these just give faster feedback.

export const ACCEPTED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp']
export const ACCEPTED_MIME_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const ACCEPT_ATTRIBUTE = [...ACCEPTED_EXTENSIONS, ...ACCEPTED_MIME_TYPES].join(',')
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024

/** Returns an error message, or null if the file looks acceptable. */
export function checkImageFile(file: File): string | null {
  const name = file.name.toLowerCase()
  const hasExtension = ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))
  const mimeOk = file.type === '' || ACCEPTED_MIME_TYPES.includes(file.type)
  if (!hasExtension || !mimeOk) {
    return `"${file.name}" is not a supported image. Choose a PNG, JPEG, or static (non-animated) WEBP file.`
  }
  if (file.size === 0) return `"${file.name}" is empty. Choose a different image.`
  if (file.size > MAX_IMAGE_BYTES) {
    return `"${file.name}" is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_IMAGE_BYTES)}; use a smaller image.`
  }
  return null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
