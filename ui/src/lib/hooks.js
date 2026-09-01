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
 * A missing manifest is the NORMAL state before the first live run, so this
 * resolves to null rather than erroring — the panel says so in words.
 *
 * Keyed on the live snapshot's timestamp, NOT on dataNonce: the captures only
 * change when the pipeline runs, and re-requesting a manifest that is not
 * there yet once a minute would paint the console red with 404s for a file
 * whose absence is a normal state.
 */
export function useRadarManifest() {
  const updated = useLive((s) => s.status?.updated_utc || null)
  // Not requested at all until a live snapshot is known to exist: the same
  // pipeline run writes the snapshot and the captures, so before the first run
  // there is provably nothing to fetch. Net effect on a cold repo: ONE 404 per
  // pipeline run instead of one per minute, and none at all once the pipeline
  // has written /static/live/frames/manifest.json.
  return useResource(() => api.radarManifest().catch(() => null), [updated], {
    enabled: Boolean(updated),
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
