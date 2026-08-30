// PRAVAAH API client.
//
// Every URL here is RELATIVE. Dev = Vite proxy -> :8000. Prod = FastAPI serves
// ui/dist from the same origin. No absolute URLs anywhere, so the app is
// airplane-mode safe.
//
// Artefacts are immutable per (event, t), so we cache aggressively. That is
// what makes the replay scrubber feel instant on the second pass.

const cache = new Map()
const inflight = new Map()

export function qs(params) {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

async function request(url, { method = 'GET', cacheable = true } = {}) {
  const key = `${method} ${url}`
  if (cacheable && cache.has(key)) return cache.get(key)
  if (inflight.has(key)) return inflight.get(key)

  const p = (async () => {
    let res
    try {
      res = await fetch(url, { method, headers: { Accept: 'application/json' } })
    } catch {
      throw new Error(`Cannot reach the PRAVAAH API (${url}). Is uvicorn running on :8000?`)
    }
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`
      try {
        const body = await res.json()
        if (body && body.detail) detail = body.detail
      } catch {
        /* non-JSON error body — keep the status line */
      }
      throw new Error(detail)
    }
    const data = await res.json()
    if (cacheable) cache.set(key, data)
    return data
  })()

  inflight.set(key, p)
  try {
    return await p
  } finally {
    inflight.delete(key)
  }
}

export const api = {
  events: () => request('/api/events'),
  health: () => request('/api/health', { cacheable: false }),
  state: (event, t) => request(`/api/state${qs({ event, t })}`),
  wards: (event, t) => request(`/api/wards${qs({ event, t })}`),
  rain: (event, t, kind, lead) => request(`/api/rain${qs({ event, t, kind, lead })}`),
  ward: (wardId, event, t) => request(`/api/ward/${wardId}${qs({ event, t })}`),
  metrics: () => request('/api/verify/metrics'),
  frames: (event, t) => request(`/api/frames${qs({ event, t })}`),
  advisory: (wardId, event, t) =>
    request(`/api/advisory/${wardId}${qs({ event, t })}`, { method: 'POST' }),
}

/** Warm the cache for a timestamp so the replay step does not stutter. */
export function prefetch(event, t) {
  if (!event || !t) return
  api.wards(event, t).catch(() => {})
  api.state(event, t).catch(() => {})
}
