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

/** FastAPI puts the useful sentence in `detail`; fall back to the status line. */
async function detailOf(res) {
  try {
    const body = await res.json()
    if (body && body.detail) return String(body.detail)
  } catch {
    /* non-JSON error body — keep the status line */
  }
  return `${res.status} ${res.statusText}`
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
    if (!res.ok) throw new Error(await detailOf(res))
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

/**
 * POST with a JSON body, NEVER cached and never de-duplicated.
 *
 * The cache above exists because a historical artefact is immutable per
 * (event, t). Neither endpoint that uses this helper is an artefact: the
 * sandbox answers a storm the operator invented half a second ago, and the
 * chat endpoint is a conversation. Caching either one would serve a stale
 * answer to a new question, which is the sandbox's single worst failure mode.
 */
async function postJson(url, body) {
  let res
  try {
    res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(`Cannot reach the PRAVAAH API (${url}). Is uvicorn running on :8000?`)
  }
  if (!res.ok) throw new Error(await detailOf(res))
  return res.json()
}

/** Same shape as request(), for endpoints that answer with text (the CAP XML). */
async function requestText(url) {
  const key = `TEXT ${url}`
  if (cache.has(key)) return cache.get(key)
  if (inflight.has(key)) return inflight.get(key)

  const p = (async () => {
    let res
    try {
      res = await fetch(url, { headers: { Accept: 'application/xml' } })
    } catch {
      throw new Error(`Cannot reach the PRAVAAH API (${url}). Is uvicorn running on :8000?`)
    }
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    const text = await res.text()
    cache.set(key, text)
    return text
  })()

  inflight.set(key, p)
  try {
    return await p
  } finally {
    inflight.delete(key)
  }
}

/**
 * Drop cached responses whose URL contains `needle`.
 *
 * The cache exists because a historical artefact is immutable per (event, t).
 * The LIVE event breaks that assumption: /api/wards?event=live&t=2300 returns
 * different bytes after every refresh, so the live pump calls this with
 * 'event=live' before it refetches. Without it the "refresh" button would poll
 * a 30-second pipeline and then serve the operator the old snapshot from
 * memory — the single most misleading bug this app could have.
 */
export function invalidate(needle) {
  for (const key of [...cache.keys()]) {
    if (key.includes(needle)) cache.delete(key)
  }
}

export const api = {
  events: () => request('/api/events', { cacheable: false }),
  health: () => request('/api/health', { cacheable: false }),
  state: (event, t) => request(`/api/state${qs({ event, t })}`),
  wards: (event, t) => request(`/api/wards${qs({ event, t })}`),
  rain: (event, t, kind, lead) => request(`/api/rain${qs({ event, t, kind, lead })}`),
  ward: (wardId, event, t) => request(`/api/ward/${wardId}${qs({ event, t })}`),
  metrics: () => request('/api/verify/metrics'),
  frames: (event, t) => request(`/api/frames${qs({ event, t })}`),
  advisory: (wardId, event, t) =>
    request(`/api/advisory/${wardId}${qs({ event, t })}`, { method: 'POST' }),

  // Alerting layer. Both are plain reads — generating a CAP document transmits
  // nothing, and status is always "Exercise" (see serve/cap.py).
  capPreview: (wardId, event, t) => request(`/api/cap/${wardId}/preview${qs({ event, t })}`),
  capXml: (wardId, event, t) => requestText(`/api/cap/${wardId}${qs({ event, t })}`),
  capXmlUrl: (wardId, event, t) => `/api/cap/${wardId}${qs({ event, t })}`,

  // ------------------------------------------------------------------ live
  // Never cached: the whole point of these two is that the answer changes.
  liveStatus: () => request('/api/live/status', { cacheable: false }),
  liveRefresh: () => request('/api/live/refresh', { method: 'POST', cacheable: false }),

  /** Real IMD Delhi DWR captures, written by the live pipeline. Same origin,
   *  served off the static mount — no radar host is ever contacted. */
  radarManifest: () => request('/static/live/frames/manifest.json', { cacheable: false }),

  // --------------------------------------------------------------- sandbox
  // The ONE route in the service that runs inference rather than reading a
  // precomputed artefact. Its answers are hypotheticals, never forecasts, and
  // every response says so in `label` and `is_forecast`.
  //
  // `centre` is [lat, lon] or null. Null is a real value here, not a missing
  // one — it means uniform city-wide rain — so it is sent explicitly rather
  // than dropped, and qs()'s empty-value pruning is deliberately not involved.
  sandbox: ({ rain_sum, rain_max, rain_prev3d, rain_prev7d, centre = null, radius_km = 12 }) =>
    postJson('/api/sandbox', {
      rain_sum,
      rain_max,
      rain_prev3d,
      rain_prev7d,
      lat: centre ? centre[0] : null,
      lon: centre ? centre[1] : null,
      radius_km,
    }),

  /** Max P(flood) and ward count over 60% as event rainfall is swept, holding
   *  the two antecedent-wetness features fixed. */
  sandboxCurve: (rain_prev3d, rain_prev7d) =>
    request(`/api/sandbox/curve${qs({ rain_prev3d, rain_prev7d })}`),

  // ------------------------------------------------------------------ chat
  // Cannot fail by construction: with no key, or on any provider error, the
  // endpoint answers 200 with ok=false and a deterministic answer built from
  // the same context. The UI labels that case rather than hiding it.
  chat: (question, event, t, wardId) =>
    postJson('/api/chat', { question, event, t, ward_id: wardId || null }),
  chatStatus: () => request('/api/chat/status'),
}

/** Warm the cache for a timestamp so the replay step does not stutter. */
export function prefetch(event, t) {
  if (!event || !t) return
  api.wards(event, t).catch(() => {})
  api.state(event, t).catch(() => {})
}
