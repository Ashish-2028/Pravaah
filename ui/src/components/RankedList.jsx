import clsx from 'clsx'
import { BAND_COLOR, compact, pct, topDriver } from '../lib/format'

export default function RankedList({ rows, selectedWard, onSelect, limit = 40 }) {
  const shown = rows.slice(0, limit)
  if (!shown.length) {
    return <div className="p-4 text-sm text-muted">No wards at this timestamp.</div>
  }
  return (
    <ul className="absolute inset-0 overflow-y-auto">
      {shown.map((w, i) => {
        const color = BAND_COLOR[w.risk_band] || '#8ba0bd'
        const active = w.ward_id === selectedWard
        return (
          <li key={w.ward_id}>
            <button
              type="button"
              onClick={() => onSelect(w.ward_id)}
              className={clsx(
                'flex w-full items-start gap-2.5 border-b border-grid/70 px-3 py-2 text-left transition-colors',
                active ? 'bg-teal/10' : 'hover:bg-panel2',
              )}
            >
              <span className="tabular w-5 shrink-0 pt-0.5 text-[11px] text-dim">{i + 1}</span>
              <span
                className={clsx('mt-1.5 h-2 w-2 shrink-0 rounded-full', w.risk_band === 'critical' && 'pulse')}
                style={{ background: color }}
              />
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[13px] font-medium text-ink">{w.name}</span>
                  <span className="tabular shrink-0 text-[13px] font-semibold" style={{ color }}>
                    {pct(w.risk_score)}
                  </span>
                </span>
                <span className="mt-0.5 flex items-center justify-between gap-2 text-[10.5px] text-muted">
                  <span className="truncate">{topDriver(w.drivers) || '—'}</span>
                  <span className="tabular shrink-0">
                    {w.onset ? `onset ${w.onset}` : 'no onset'}
                  </span>
                </span>
                <span className="mt-0.5 block text-[10px] text-dim">
                  {compact(w.people)} people · P(flood) {pct(w.p_flood)}
                </span>
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
