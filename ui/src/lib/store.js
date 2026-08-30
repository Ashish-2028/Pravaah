import { create } from 'zustand'

export const DEFAULT_EVENT = '2024-06-28'

// The one clock the whole app reads from. Everything else is derived.
export const useStore = create((set, get) => ({
  event: DEFAULT_EVENT,
  t: null, // null until the event catalogue loads, then a real "HHMM"
  lead: 3, // hours, for the nowcast/forecast views
  layer: 'p_flood', // 'p_flood' | 'risk_score' | 'exposure'
  mode: 'live', // 'live' | 'replay'
  playing: false,
  speed: 800, // ms per 30-min step
  selectedWard: null,
  advisoryOpen: false,
  timestamps: [],
  events: [],

  setEvent: (event) => {
    const ev = get().events.find((e) => e.id === event)
    const stamps = ev ? ev.timestamps : []
    set({
      event,
      timestamps: stamps,
      t: stamps.length ? stamps[stamps.length - 1] : null,
      selectedWard: null,
      playing: false,
    })
  },
  setT: (t) => set({ t }),
  setLead: (lead) => set({ lead }),
  setLayer: (layer) => set({ layer }),
  setMode: (mode) => {
    const s = get()
    if (mode === 'live') {
      set({
        mode,
        playing: false,
        t: s.timestamps.length ? s.timestamps[s.timestamps.length - 1] : s.t,
      })
    } else {
      set({ mode })
    }
  },
  setPlaying: (playing) => set({ playing }),
  setSpeed: (speed) => set({ speed }),
  selectWard: (selectedWard) => set({ selectedWard }),
  openAdvisory: (wardId) =>
    set(wardId ? { advisoryOpen: true, selectedWard: wardId } : { advisoryOpen: true }),
  closeAdvisory: () => set({ advisoryOpen: false }),

  hydrateEvents: (payload) => {
    const events = payload.events || []
    const s = get()
    const chosen = events.find((e) => e.id === s.event) || events[0]
    if (!chosen) return
    set({
      events,
      event: chosen.id,
      timestamps: chosen.timestamps,
      t: s.t && chosen.timestamps.includes(s.t)
        ? s.t
        : chosen.timestamps[chosen.timestamps.length - 1],
    })
  },

  step: (delta) => {
    const { timestamps, t } = get()
    if (!timestamps.length) return
    const i = timestamps.indexOf(t)
    const next = Math.max(0, Math.min(timestamps.length - 1, (i < 0 ? 0 : i) + delta))
    set({ t: timestamps[next] })
  },
}))
