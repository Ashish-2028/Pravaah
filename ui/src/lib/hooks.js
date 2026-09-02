import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { useLive } from './live'
import { useStore } from './store'

/**
 * Generic async resource hook.
 *
 * Keeps the previous payload on screen while the next one loads, so scrubbing
 * the replay clock never flashes an empty panel — a hard requirement of the
 * "never render a blank screen" rule.
 */
export function useResource(fn, deps, { enabled = true } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: enabled })
  const alive = useRef(true)
  const call = useRef(fn)
  call.current = fn

  const reload = useCallback(() => {
    if (!enabled) {
      setState({ data: null, error: null, loading: false })
      return
    }
    setState((s) => ({ ...s, loading: true, error: null }))
    call
      .current()
      .then((data) => {
        if (alive.current) setState({ data, error: null, loading: false })
      })
      .catch((err) => {
        if (alive.current) {
          setState((s) => ({ data: s.data, error: err.message || String(err), loading: false }))
        }
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps])

  useEffect(() => {
    alive.current = true
    reload()
    return () => {
      alive.current = false
    }
  }, [reload])

  return { ...state, reload }
}

/**
 * The live pump bumps `dataNonce` after it has dropped the cached live
 * responses. Carrying it here — rather than in each caller — is what makes
 * every panel in the app refetch together when the snapshot moves, without a
 * single view knowing that "live" exists.
 */
function useDataNonce() {
  return useStore((s) => s.dataNonce)
}

export function useWards(event, t) {
  const nonce = useDataNonce()
  return useResource(() => api.wards(event, t), [event, t, nonce], {
    enabled: Boolean(event && t),
  })
}

export function useCityState(event, t) {
  const nonce = useDataNonce()
  return useResource(() => api.state(event, t), [event, t, nonce], {
    enabled: Boolean(event && t),
  })
}

export function useRain(event, t, kind = 'nowcast', lead) {
  const nonce = useDataNonce()
  return useResource(() => api.rain(event, t, kind, lead), [event, t, kind, lead, nonce], {
    enabled: Boolean(event && t),
  })
}

/**
 * IMD Delhi DWR captures written by the live pipeline.
 *
 * FETCHED ON FIRST PAINT, UNCONDITIONALLY. It used to be gated on
 * `enabled: Boolean(updated)` — i.e. it would not ask for the manifest until
 * /api/live/status had come back with a snapshot timestamp. The reasoning was
 * that the same pipeline run writes both, so before the first run there is
 * provably nothing to fetch and the gate saves a 404.
 *
 * That reasoning is wrong in the one case that matters. The frames are written
 * to disk and served off the static mount; they OUTLIVE the API's notion of a
 * live snapshot, so a repo with 72 captures already on disk and a status
 * endpoint that reports nothing yet (or is slow, or has been restarted) showed
 * an empty radar panel with "no captures on disk yet" — a message that was
 * simply false. Worse, the gate is invisible: `enabled: false` leaves
 * `loading: false, data: null`, which the panel could not tell apart from a
 * real 404.
 *
 * So: ask immediately, and keep the status timestamp only as a REFRESH key, so
 * a completed pipeline run pulls the new frame list in. Cost on a cold repo is
 * one 404 at mount plus one per pipeline run — a fair price for a panel that is
 * never wrong about what is on disk.
 *
 * The error is NOT swallowed here (it used to be `.catch(() => null)`). The
 * panel needs to distinguish "still loading", "genuinely 404" and "the fetch
 * failed", and it can only do that if the failure reaches it.
 */
export function useRadarManifest() {
  const updated = useLive((s) => s.status?.updated_utc || null)
  return useResource(() => api.radarManifest(), [updated])
}

export function useMetrics() {
  return useResource(() => api.metrics(), [])
}

/** Health polls — it is the only thing in the app that is genuinely "live". */
export function useHealth(intervalMs = 20000) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let alive = true
    const tick = () =>
      api
        .health()
        .then((d) => {
          if (alive) setData(d)
        })
        .catch(() => {
          if (alive) setData({ ok: false, badges: { sat: 'down', radar: 'down', stations: 'down', nwp: 'down' } })
        })
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [intervalMs])
  return data
}

/** Sorted-by-risk ward property list, derived client-side from the GeoJSON. */
export function rankWards(fc, limit = 0) {
  if (!fc || !Array.isArray(fc.features)) return []
  const rows = fc.features.map((f) => f.properties)
  rows.sort((a, b) => b.risk_score - a.risk_score)
  return limit ? rows.slice(0, limit) : rows
}

export function findWard(fc, wardId) {
  if (!fc || !wardId || !Array.isArray(fc.features)) return null
  const hit = fc.features.find((f) => f.properties.ward_id === wardId)
  return hit ? hit.properties : null
}
