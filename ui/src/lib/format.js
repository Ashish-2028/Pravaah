// Display helpers. House rule: every probability is shown as a percentage.

export const BAND_COLOR = {
  low: '#5d738f',
  watch: '#14b8a6',
  high: '#f59e0b',
  critical: '#ef4444',
}

export const BADGE_COLOR = {
  ok: '#14b8a6',
  degraded: '#f59e0b',
  down: '#ef4444',
}

export const CITY_RISK_COLOR = {
  LOW: '#5d738f',
  WATCH: '#14b8a6',
  HIGH: '#f59e0b',
  CRITICAL: '#ef4444',
}

export const BAND_ORDER = ['critical', 'high', 'watch', 'low']

/** 0.583 -> "58%" */
export function pct(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function num(v, digits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return Number(v).toLocaleString('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

/** 3057303 -> "3.06 M" */
export function compact(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e7) return `${(n / 1e7).toFixed(2)} Cr`
  if (Math.abs(n) >= 1e5) return `${(n / 1e5).toFixed(2)} L`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)} K`
  return String(n)
}

export function minutes(v) {
  if (v === null || v === undefined) return 'none predicted'
  if (v <= 0) return 'now'
  if (v < 60) return `${v} min`
  const h = Math.floor(v / 60)
  const m = v % 60
  return m ? `${h} h ${m} min` : `${h} h`
}

/** "0730" -> "07:30" */
export function hhmm(t) {
  if (!t || t.length !== 4) return t || '—'
  return `${t.slice(0, 2)}:${t.slice(2)}`
}

/** "0730" UTC -> "13:00" IST (UTC + 5:30) */
export function toIST(t) {
  if (!t || t.length !== 4) return '—'
  const mins = Number(t.slice(0, 2)) * 60 + Number(t.slice(2)) + 330
  const wrapped = ((mins % 1440) + 1440) % 1440
  const h = String(Math.floor(wrapped / 60)).padStart(2, '0')
  const m = String(wrapped % 60).padStart(2, '0')
  return `${h}:${m}`
}

export function ci90(arr) {
  if (!Array.isArray(arr) || arr.length !== 2) return null
  return `${arr[0]} – ${arr[1]}`
}

export function topDriver(drivers) {
  if (!Array.isArray(drivers) || !drivers.length) return null
  return drivers[0][0]
}

/** Diverging control-room ramp used by every choropleth. */
export function rampColor(v) {
  const stops = [
    [0.0, [18, 32, 58]],
    [0.25, [13, 125, 140]],
    [0.45, [20, 184, 166]],
    [0.6, [245, 158, 11]],
    [0.8, [239, 68, 68]],
    [1.0, [255, 107, 107]],
  ]
  const x = Math.max(0, Math.min(1, Number(v) || 0))
  for (let i = 1; i < stops.length; i += 1) {
    if (x <= stops[i][0]) {
      const [a, ca] = stops[i - 1]
      const [b, cb] = stops[i]
      const f = (x - a) / (b - a || 1)
      const c = ca.map((ch, j) => Math.round(ch + (cb[j] - ch) * f))
      return `rgb(${c[0]},${c[1]},${c[2]})`
    }
  }
  return 'rgb(255,107,107)'
}
