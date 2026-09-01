import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { ageLabel, ageMinutes, isStale, useLive } from '../lib/live'

/**
 * How old the live snapshot is — and it never hides.
 *
 * A snapshot that quietly goes stale mid-demo is worse than one that admits
 * "42 min old": the operator can act on the second and cannot act on the
 * first. So the badge turns AMBER past 20 minutes and stays on screen. The
 * only state that removes it is "the pipeline has never run", which is
 * reported in words instead.
 */
export function LiveBadge({ compact: isCompact = false }) {
  const status = useLive((s) => s.status)
  const statusError = useLive((s) => s.statusError)
  const refreshing = useLive((s) => s.refreshing)
  // Re-render once a minute so the age keeps counting between status polls.
  const [, setBeat] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setBeat((n) => n + 1), 30000)
    return () => clearInterval(id)
  }, [])

  if (statusError && !status) {
    return (
      <Shell color="#ef4444" title={statusError}>
        <span className="font-semibold">LIVE STATUS UNREACHABLE</span>
      </Shell>
    )
  }
  if (!status) {
    return (
      <Shell color="#5d738f" title="Asking the API for the live snapshot age">
        <span>checking live…</span>
      </Shell>
    )
  }
  if (!status.available) {
    return (
      <Shell color="#f59e0b" title={status.note || 'no live snapshot on disk yet'}>
        <AlertTriangle size={11} className="shrink-0" />
        <span className="font-semibold">NO LIVE SNAPSHOT</span>
      </Shell>
    )
  }

  const mins = ageMinutes(status)
  const stale = isStale(status, mins)
  const color = stale ? '#f59e0b' : '#14b8a6'
  const serverAge = status.age_minutes

  return (
    <Shell
      color={color}
      title={[
        `Live snapshot ${status.updated_ist || status.updated_utc}`,
        `${status.frames ?? '—'} frames · ${status.wards ?? '—'} wards`,
        serverAge !== undefined ? `server-reported age ${serverAge} min` : null,
        stale ? 'STALE: older than 20 min (15-min cadence plus one missed cycle)' : null,
        status.last_error ? `last refresh error: ${status.last_error}` : null,
      ]
        .filter(Boolean)
        .join('\n')}
    >
      <span
        className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', !stale && !refreshing && 'pulse')}
        style={{ background: color }}
      />
      {stale && <span className="font-bold">STALE</span>}
      <span className="tabular font-semibold">{status.updated_ist || '—'}</span>
      {!isCompact && <span className="opacity-70">· {ageLabel(mins)}</span>}
    </Shell>
  )
}

function Shell({ color, title, children }) {
  return (
    <div
      title={title}
      className="flex items-center gap-1.5 whitespace-nowrap rounded border px-2 py-1 text-[10px] uppercase tracking-wider"
      style={{ borderColor: `${color}55`, background: `${color}14`, color }}
    >
      {children}
    </div>
  )
}

/**
 * Manual refresh. POSTs, then polls /api/live/status every 3 s until the
 * pipeline lets go, then the pump drops the live cache and every panel
 * refetches. Disabled — genuinely, not just styled — while that runs.
 */
export function RefreshButton({ label = 'Refresh' }) {
  const refreshing = useLive((s) => s.refreshing)
  const refresh = useLive((s) => s.refresh)
  return (
    <button
      type="button"
      onClick={refresh}
      disabled={refreshing}
      title={
        refreshing
          ? 'Pulling observations and re-running the nowcast — about 30–40 seconds'
          : 'Pull the latest observations and re-run the live nowcast'
      }
      className={clsx(
        'flex items-center gap-1.5 whitespace-nowrap rounded border px-2 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors',
        refreshing
          ? 'cursor-wait border-amber/50 bg-amber/10 text-amber'
          : 'border-grid text-muted hover:border-teal/50 hover:text-teal',
      )}
    >
      <RefreshCw size={11} className={refreshing ? 'spin' : undefined} />
      {refreshing ? 'refreshing…' : label}
    </button>
  )
}

/** The one place a failed refresh is reported. Rendered by the live views so
 *  a pipeline error cannot vanish into a console nobody is reading. */
export function RefreshError() {
  const refreshError = useLive((s) => s.refreshError)
  const lastError = useLive((s) => s.status?.last_error)
  const msg = refreshError || lastError
  if (!msg) return null
  return (
    <div className="flex items-start gap-2 rounded-md border border-amber/40 bg-amber/10 px-2.5 py-1.5 text-[10.5px] leading-snug text-amber">
      <AlertTriangle size={13} className="mt-px shrink-0" />
      <div className="min-w-0">
        <span className="font-semibold">Last live refresh reported an error. </span>
        <span className="break-words opacity-90">{String(msg)}</span>
      </div>
    </div>
  )
}
