import clsx from 'clsx'
import { AlertTriangle, Loader2 } from 'lucide-react'

export function Panel({ title, right, className, bodyClass, children }) {
  return (
    <section
      className={clsx(
        'flex min-h-0 flex-col rounded-lg border border-grid bg-panel',
        className,
      )}
    >
      {/* `flex-wrap` and the `min-w-0` title are what keep a long panel title
          and a two-group control cluster from shunting each other out of the
          header instead of stacking. */}
      {(title || right) && (
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-x-2 gap-y-1 border-b border-grid px-3 py-2">
          <h2 className="min-w-0 truncate text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            {title}
          </h2>
          {right}
        </header>
      )}
      {/* `relative` is load-bearing: fill-height children position themselves
          absolutely because a percentage height against a flex-1 track is
          indefinite and collapses to zero. */}
      <div className={clsx('relative min-h-0 flex-1', bodyClass)}>{children}</div>
    </section>
  )
}

export function Spinner({ label = 'Loading' }) {
  return (
    <div className="flex h-full min-h-[110px] w-full items-center justify-center gap-2 p-6 text-sm text-muted">
      <Loader2 size={16} className="spin" />
      <span>{label}…</span>
    </div>
  )
}

export function ErrorBox({ error, onRetry, compact: isCompact }) {
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 text-danger',
        isCompact ? 'p-2 text-xs' : 'm-3 p-3 text-sm',
      )}
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">Could not load data</div>
        <div className="mt-0.5 break-words text-danger/80">{String(error)}</div>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-2 rounded border border-danger/50 px-2 py-1 text-xs hover:bg-danger/20"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  )
}

/** Loading / error / empty gate so no panel ever renders white. */
export function Async({ res, label, children, keepStale = true }) {
  if (res.error && !res.data) return <ErrorBox error={res.error} onRetry={res.reload} />
  if (!res.data) return <Spinner label={label} />
  return (
    <div className="relative h-full min-h-0">
      {res.loading && keepStale && (
        <div className="pointer-events-none absolute right-2 top-2 z-10 flex items-center gap-1 rounded bg-bg/80 px-1.5 py-0.5 text-[10px] text-muted">
          <Loader2 size={10} className="spin" /> updating
        </div>
      )}
      {children(res.data)}
    </div>
  )
}

export function Pill({ color, children, className }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
        className,
      )}
      style={{ color, background: `${color}1f`, border: `1px solid ${color}55` }}
    >
      {children}
    </span>
  )
}

export function Stat({ label, value, sub, color, accent, title, footer }) {
  return (
    <div className="min-w-0 rounded-lg border border-grid bg-panel px-3 py-2.5">
      <div
        title={title || undefined}
        className="truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-muted"
      >
        {label}
      </div>
      <div
        className="tabular mt-1 truncate text-2xl font-semibold leading-tight"
        style={{ color: color || undefined }}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-muted">{sub}</div>}
      {accent !== undefined && (
        <div className="mt-2 h-1 w-full overflow-hidden rounded bg-grid">
          <div
            className="h-full rounded"
            style={{
              width: `${Math.max(2, Math.min(100, accent * 100))}%`,
              background: color || 'var(--color-teal)',
            }}
          />
        </div>
      )}
      {/* Provenance line: which model produced the number above it. */}
      {footer && <div className="mt-1.5">{footer}</div>}
    </div>
  )
}
