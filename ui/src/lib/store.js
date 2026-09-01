import { create } from 'zustand'

/** The rolling event the live pipeline rewrites every 15 minutes. */
export const LIVE_EVENT = 'live'

const lastOf = (stamps) => (stamps && stamps.length ? stamps[stamps.length - 1] : null)

export const stampsOf = (events, id) => events.find((e) => e.id === id)?.timestamps || []

/** Everything in the catalogue that is NOT the rolling live event. Written as
 *  a filter, never as a hardcoded list: the catalogue grows. */
export const historicals = (events) => events.filter((e) => e.id !== LIVE_EVENT)

/**
 * The one clock the whole app reads from — but there are now TWO clocks
 * feeding it, and they are not allowed to fight.
 *
 *   LIVE   mode: `event` is the rolling live snapshot (or, if the pipeline has
 *                never run, the newest historical event as a labelled
 *                fallback) and `t` is PINNED to its newest frame. Only the
 *                live pump writes it, and only via syncLive().
 *   REPLAY mode: `event`/`t` are the operator's choice, remembered in
 *                replayEvent/replayT so that flipping to LIVE and back does
 *                not lose their place. Only the Replay view writes it.
 *
 * `event`/`t` are the active pair, mirrored out of whichever mode is current,
 * so every existing consumer keeps reading exactly one clock. The mode is
 * driven by the route (AppShell): /replay is REPLAY, everything else is LIVE.
 * That is what keeps a play loop from ever running underneath a live screen.
 */
export const useStore = create((set, get) => ({
  event: null,
  t: null, // null until the event catalogue loads, then a real "HHMM"
  timestamps: [],
  events: [],

  mode: 'live', // 'live' | 'replay'
  liveEvent: null, // id of the live event, or null when the pipeline has never run
  liveFallback: null, // historical event shown in LIVE mode when live is missing
  replayEvent: null,
  replayT: null,

  /** Bumped whenever live artefacts are known to have changed. Data hooks
   *  carry it in their dependency list, which is what turns a silent cache
   *  invalidation into a visible refetch. */
  dataNonce: 0,

  lead: 3, // hours, for the nowcast/forecast views
  layer: 'p_flood', // 'p_flood' | 'risk_score' | 'exposure'
  playing: false,
  speed: 800, // ms per frame
  selectedWard: null,
  advisoryOpen: false,

  // ------------------------------------------------------------- catalogue
  hydrateEvents: (payload) => {
    const events = payload.events || []
    if (!events.length) return
    const s = get()
    const live = events.find((e) => e.id === LIVE_EVENT) || null
    const hist = historicals(events)
    const fallback = hist[0]?.id || null

    // Replay keeps the operator's event if it is still in the catalogue.
    const replayEvent =
      (s.replayEvent && events.some((e) => e.id === s.replayEvent) && s.replayEvent !== LIVE_EVENT
        ? s.replayEvent
        : null) || fallback
    const replayStamps = stampsOf(events, replayEvent)
    const replayT =
      s.replayT && replayStamps.includes(s.replayT) ? s.replayT : lastOf(replayStamps)

    const liveId = live ? live.id : fallback
    const liveStamps = stampsOf(events, liveId)

    const next = {
      events,
      liveEvent: live ? live.id : null,
      liveFallback: fallback,
      replayEvent,
      replayT,
    }
    if (s.mode === 'replay') {
      Object.assign(next, { event: replayEvent, t: replayT, timestamps: replayStamps })
    } else {
      // LIVE always pins to the newest frame — that is what "live" means.
      Object.assign(next, { event: liveId, t: lastOf(liveStamps), timestamps: liveStamps })
    }
    set(next)
  },

  /**
   * Called by the live pump when /api/live/status reports a newer snapshot.
   * Refetching the catalogue is not optional: a refresh usually changes the
   * live event's frame list, so pinning to "the newest frame" requires the new
   * list, not the one we booted with.
   */
  syncLive: (payload) => {
    get().hydrateEvents(payload)
    set((s) => ({ dataNonce: s.dataNonce + 1 }))
  },

  bumpData: () => set((s) => ({ dataNonce: s.dataNonce + 1 })),

  // ------------------------------------------------------------------ mode
  setMode: (mode) => {
    const s = get()
    if (mode === s.mode) return
    if (mode === 'replay') {
      const ev = s.replayEvent || s.liveFallback
      const stamps = stampsOf(s.events, ev)
      set({
        mode,
        event: ev,
        timestamps: stamps,
        t: s.replayT && stamps.includes(s.replayT) ? s.replayT : lastOf(stamps),
        playing: false,
      })
    } else {
      const ev = s.liveEvent || s.liveFallback
      const stamps = stampsOf(s.events, ev)
      set({ mode, event: ev, timestamps: stamps, t: lastOf(stamps), playing: false })
    }
  },

  // ---------------------------------------------------------- replay clock
  // Both writers mirror into the replay shadow so the choice survives a trip
  // through LIVE. They are no-ops outside replay mode by construction: only
  // the Replay view calls them.
  setEvent: (event) => {
    const stamps = stampsOf(get().events, event)
    set({
      event,
      replayEvent: event,
      timestamps: stamps,
      t: lastOf(stamps),
      replayT: lastOf(stamps),
      selectedWard: null,
      playing: false,
    })
  },
  setT: (t) => set({ t, replayT: t }),
  step: (delta) => {
    const { timestamps, t } = get()
    if (!timestamps.length) return
    const i = timestamps.indexOf(t)
    const next = Math.max(0, Math.min(timestamps.length - 1, (i < 0 ? 0 : i) + delta))
    set({ t: timestamps[next], replayT: timestamps[next] })
  },

  // ----------------------------------------------------------------- misc
  setLead: (lead) => set({ lead }),
  setLayer: (layer) => set({ layer }),
  setPlaying: (playing) => set({ playing }),
  setSpeed: (speed) => set({ speed }),
  selectWard: (selectedWard) => set({ selectedWard }),
  openAdvisory: (wardId) =>
    set(wardId ? { advisoryOpen: true, selectedWard: wardId } : { advisoryOpen: true }),
  closeAdvisory: () => set({ advisoryOpen: false }),
}))

/** True when LIVE mode is showing a historical event because the live
 *  pipeline has produced nothing yet. Every live screen surfaces this rather
 *  than pretending. */
export const selectLiveMissing = (s) => s.mode === 'live' && !s.liveEvent
