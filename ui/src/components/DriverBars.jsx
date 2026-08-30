import { pct } from '../lib/format'

/**
 * SHAP top-3, already translated to plain words by the backend.
 * Contract: drivers is [[label, weight], ...] — an array of 2-tuples.
 * MapLibre stringifies nested properties, so accept a JSON string too.
 */
export function parseDrivers(drivers) {
  let d = drivers
  if (typeof d === 'string') {
    try {
      d = JSON.parse(d)
    } catch {
      return []
    }
  }
  if (!Array.isArray(d)) return []
  return d
    .filter((row) => Array.isArray(row) && row.length >= 2)
    .map(([label, weight]) => ({ label: String(label), weight: Number(weight) || 0 }))
}

export default function DriverBars({ drivers, max }) {
  const rows = parseDrivers(drivers)
  if (!rows.length) return <div className="px-3 py-2 text-xs text-muted">No driver attribution available.</div>
  const peak = max || Math.max(...rows.map((r) => Math.abs(r.weight)), 0.01)

  return (
    <div className="space-y-2 px-3 py-2.5">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
            <span className="truncate text-ink">{r.label}</span>
            <span className="tabular shrink-0 text-muted">{pct(r.weight)}</span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded bg-grid">
            <div
              className="h-full rounded bg-teal transition-[width] duration-300"
              style={{ width: `${Math.max(3, (Math.abs(r.weight) / peak) * 100)}%` }}
            />
          </div>
        </div>
      ))}
      <p className="pt-1 text-[10px] leading-relaxed text-dim">
        SHAP attribution over the InundaNet feature set, translated to plain words. Weights are
        relative contributions to this ward&apos;s probability.
      </p>
    </div>
  )
}
