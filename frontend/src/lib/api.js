// Small helper for calling our FastAPI backend.
// By default requests go to /api/..., which Vite forwards to http://127.0.0.1:8000 (see vite.config.js).

export const API_URL = import.meta.env.VITE_API_URL || '/api'

export async function apiPost(path, body) {
  const res = await fetch(API_URL + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    // FastAPI puts the message in "detail"
    throw new Error(data.detail || `Request failed (${res.status})`)
  }
  return data
}
