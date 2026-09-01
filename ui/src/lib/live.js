// The live wiring: status polling, the 60-second data pump, and the manual
// refresh controller.
//
// DESIGN RULE — the app must never show a live number without also showing how
// old it is. /api/live/status is polled on its own short cadence purely so the
// badge in the top bar stays honest; the heavier artefact refetch is separate
// and only fires when the snapshot has actually changed (or once a minute as a
// backstop, because the pipeline can rewrite a frame under the same clock).

import { useEffect, useRef } from 'react'
import { create } from 'zustand'
import { api, invalidate } from './api'
import { useStore } from './store'

const STATUS_MS = 15000 // badge freshness
const DATA_MS = 60000 // backstop refetch while a live screen is open
const POLL_MS = 3000 // during a manual refresh

/** Wipe every cached response belonging to the rolling live event. */
export function invalidateLive() {
  invalidate('event=live')
  invalidate('/static/live/')
}

export const useLive = create((set, get) => ({
  status: null, // last /api/live/status payload
  statusError: null, // transport failure, distinct from a pipeline failure
  refreshing: false, // OUR refresh is in flight (or the server says one is)
  refreshError: null, // why the last manual refresh did not happen
  startedAt: null,

  setStatus: (status) => set({ status, statusError: null }),
  setStatusError: (statusError) => set({ statusError }),

  /**
   * POST /api/live/refresh, then poll until the pipeline lets go.
   *
   * The endpoint is asynchronous — it returns in milliseconds and the work
   * takes 30-40 s — so "did it work?" is answered by /api/live/status and
   * nothing else. Two failure modes are surfaced separately: the refresh never
   * started (someone else's run is in flight) and the run itself failed
   * (status.last_error).
   */
  refresh: async () => {
    if (get().refreshing) return
    set({ refreshing: true, refreshError: null, startedAt: Date.now() })
    try {
      const res = await api.liveRefresh()
      if (res && res.started === false) {
        // Not an error: another refresh owns the pipeline. Fall through and
        // poll it to completion anyway, so the button still tracks the work.
        set({ refreshError: res.reason || 'a refresh is already running' })
      }
    } catch (err) {
      set({ refreshing: false, refreshError: err.message || String(err) })
      return
    }

    const before = get().status?.updated_utc || null
    const deadline = Date.now() + 240000
    let sawRunning = false
    // eslint-disable-next-line no-constant-condition
    while (true) {
      await new Promise((r) => setTimeout(r, POLL_MS))
      let st = null
      try {
        st = await api.liveStatus()
      } catch (err) {
        set({ statusError: err.message || String(err) })
      }
      if (st) {
        set({ status: st, statusError: null })
        if (st.refreshing) sawRunning = true
        const changed = st.updated_utc && st.updated_utc !== before
        // The POST returns before the worker thread flips its flag, so a
        // single `refreshing: false` right after the kick means nothing. Wait
        // for evidence: either a new snapshot, or a run we watched finish.
        if (changed || (sawRunning && !st.refreshing)) {
          if (st.last_error) set({ refreshError: st.last_error })
          break
        }
        if (!st.refreshing && !sawRunning && Date.now() - get().startedAt > 20000) {
          // Nothing ever started and nothing changed — report it rather than
          // spinning forever behind a disabled button.
          set({ refreshError: st.last_error || 'refresh did not start' })
          break
        }
      }
      if (Date.now() > deadline) {
        set({ refreshError: 'refresh timed out after 4 min' })
        break
      }
    }

    invalidateLive()
    try {
      useStore.getState().syncLive(await api.events())
    } catch {
      useStore.getState().bumpData()
    }
    set({ refreshing: false })
  },
}))

/**
 * Mounted exactly once, in the shell.
 *
 *   * /api/live/status every 15 s, always — the badge has to age even while
 *     the operator is deep in a replay.
 *   * when updated_utc moves, drop the live cache and refetch the catalogue,
 *     because a refresh can add frames and LIVE pins to the newest one.
 *   * a 60 s backstop while a live screen is open, for the case where the
 *     pipeline rewrites the current frame in place.
 */
export function useLivePump() {
  const mode = useStore((s) => s.mode)
  const seen = useRef(null)
  const modeRef = useRef(mode)
  modeRef.current = mode

  useEffect(() => {
    let alive = true

    const applyStatus = async (st) => {
      if (!alive) return
      useLive.getState().setStatus(st)
      if (!st.available || !st.updated_utc) return
      if (seen.current === null) {
        seen.current = st.updated_utc
        return
      }
      if (st.updated_utc !== seen.current) {
        seen.current = st.updated_utc
        invalidateLive()
        try {
          const events = await api.events()
          if (alive) useStore.getState().syncLive(events)
        } catch {
          if (alive) useStore.getState().bumpData()
        }
      }
    }

    const tick = () =>
      api
        .liveStatus()
        .then(applyStatus)
        .catch((err) => alive && useLive.getState().setStatusError(err.message || String(err)))

    tick()
    const statusId = setInterval(tick, STATUS_MS)

    const dataId = setInterval(() => {
      // Only while a live screen is actually being looked at. Refetching under
      // a paused replay frame would be pointless traffic and, worse, would
      // make a replay panel flicker for no reason.
      if (modeRef.current !== 'live' || useLive.getState().refreshing) return
      invalidateLive()
      useStore.getState().bumpData()
    }, DATA_MS)

    return () => {
      alive = false
      clearInterval(statusId)
      clearInterval(dataId)
    }
  }, [])
}

/** Minutes since the snapshot, recomputed locally so the badge keeps ageing
 *  between status polls instead of sitting on a stale server number. */
export function ageMinutes(status, now = Date.now()) {
  if (!status || !status.updated_utc) return null
  const ms = now - Date.parse(status.updated_utc)
  if (Number.isNaN(ms)) return status.age_minutes ?? null
  return Math.max(0, ms / 60000)
}

export function ageLabel(mins) {
  if (mins === null || mins === undefined) return '—'
  if (mins < 1) return 'just now'
  if (mins < 60) return `${Math.round(mins)} min ago`
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return m ? `${h} h ${m} min ago` : `${h} h ago`
}

/** The staleness rule lives on the server (20 min = the 15-min cadence plus
 *  one missed cycle). Recompute it locally too, so a badge that has not been
 *  polled for a while still turns amber. */
export function isStale(status, mins) {
  if (!status) return false
  if (mins !== null && mins !== undefined) return mins > 20
  return Boolean(status.stale)
}
