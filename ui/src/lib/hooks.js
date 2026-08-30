import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

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

export function useWards(event, t) {
  return useResource(() => api.wards(event, t), [event, t], { enabled: Boolean(event && t) })
}

export function useCityState(event, t) {
  return useResource(() => api.state(event, t), [event, t], { enabled: Boolean(event && t) })
}

export function useRain(event, t, kind = 'nowcast', lead) {
  return useResource(() => api.rain(event, t, kind, lead), [event, t, kind, lead], {
    enabled: Boolean(event && t),
  })
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
