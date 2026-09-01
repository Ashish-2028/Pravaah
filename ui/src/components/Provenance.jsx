import clsx from 'clsx'

// Where each number came from, said quietly.
//
// Two rules this component exists to enforce:
//   1. A model-derived number carries the MODEL'S NAME, not the project's.
//   2. The wording is taken verbatim from the API's provenance block wherever
//      one exists. Nothing here restates a source in the UI's own words, so
//      the wording can only ever be changed at the source.

/** "RainCast-v0 (calibrated), live" -> "RainCast-v0" */
export function modelName(source, fallback = null) {
  if (!source || typeof source !== 'string') return fallback
  const head = source.split(/[(,—]/)[0].trim()
  return head || fallback
}

/** The small grey label that sits under a model-derived figure. */
export function Prov({ children, title, className, tone = 'dim' }) {
  if (!children) return null
  return (
    <span
      title={title || undefined}
      className={clsx(
        'inline-flex max-w-full items-center gap-1 truncate text-[9px] uppercase tracking-[0.1em]',
        tone === 'dim' ? 'text-dim' : 'text-muted',
        className,
      )}
    >
      <span className="h-1 w-1 shrink-0 rounded-full bg-current opacity-70" />
      <span className="truncate">{children}</span>
    </span>
  )
}

/**
 * The full provenance of a rain grid: what produced the forecast, what the
 * observations actually are, and when the data was pulled.
 *
 * The observation line is the important one. Open-Meteo's past_days window is
 * a reanalysis-style ANALYSIS, not a rain gauge, and the API says so in the
 * string; we print that string rather than summarising it into something
 * comfortable.
 */
export default function ProvenancePanel({ provenance, className }) {
  if (!provenance) {
    return (
      <div className={clsx('p-3 text-[11px] leading-relaxed text-muted', className)}>
        This response carried no provenance block, so no source can be named for these numbers.
      </div>
    )
  }
  const rows = [
    ['Nowcast', provenance.nowcast_source],
    ['Observations', provenance.observation_source],
  ].filter(([, v]) => v)

  const heads = provenance.head_thresholds_mm
  return (
    <div className={clsx('space-y-2 p-3 text-[11px] leading-relaxed', className)}>
      {rows.map(([k, v]) => (
        <div key={k}>
          <div className="text-[9px] uppercase tracking-[0.14em] text-dim">{k}</div>
          <div className="text-muted">{v}</div>
        </div>
      ))}
      {heads && (
        <div>
          <div className="text-[9px] uppercase tracking-[0.14em] text-dim">Exceedance heads</div>
          <div className="text-muted">
            {Object.entries(heads)
              .map(([k, mm]) => `${mm} mm (${k})`)
              .join(' · ')}
            <span className="text-dim">
              {' '}
              — the field names are legacy, the millimetres are the truth.
            </span>
          </div>
        </div>
      )}
      {provenance.fetched_utc && (
        <div className="text-[10px] text-dim">
          Fetched {String(provenance.fetched_utc).replace('T', ' ').slice(0, 19)} UTC
        </div>
      )}
    </div>
  )
}
