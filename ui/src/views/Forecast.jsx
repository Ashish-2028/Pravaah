import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import MapCanvas from '../components/MapCanvas'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { useRain, useWards } from '../lib/hooks'
import { hhmm, num, pct } from '../lib/format'
import { useStore } from '../lib/store'

// The official IMD heavy-rainfall categories, in mm/24 h.
const IMD = [
  { mm: 64.5, label: 'Heavy' },
  { mm: 115.6, label: 'Very heavy' },
  { mm: 204.5, label: 'Extremely heavy' },
]
const LEADS = [6, 12, 24, 48, 72]

export default function Forecast() {
  const { event, t, lead, setLead } = useStore()
  const [threshold, setThreshold] = useState(64.5)
  const leadH = LEADS.includes(lead) ? lead : 24
  const rainRes = useRain(event, t, 'forecast', leadH)
  const wardsRes = useWards(event, t)

  const cells = rainRes.data?.cells || []

  // No endpoint returns per-threshold exceedance for the forecast head, so we
  // derive it client-side from the quantiles the grid DOES carry: a cell's q90
  // relative to the IMD category is the exceedance signal we can honestly show.
  const points = useMemo(() => {
    if (!cells.length) return null
    return cells.map((c) => ({
      lat: c.lat,
      lon: c.lon,
      value: Math.max(0, Math.min(1, c.q90 / threshold)),
    }))
  }, [cells, threshold])

  const fan = useMemo(() => {
    if (!cells.length) return []
    const sorted = [...cells].sort((a, b) => b.q90 - a.q90).slice(0, 12)
    return sorted.map((c) => ({
      cell: `${c.lat.toFixed(2)},${c.lon.toFixed(2)}`,
      q10: c.q10,
      band: c.q90 - c.q10,
      q50: c.q50,
      q90: c.q90,
    }))
  }, [cells])

  const forecastBlock = rainRes.data?.forecast || null

  return (
    <div className="grid h-full grid-cols-[1fr_340px] gap-2 overflow-hidden p-2">
      <Panel
        title="Exceedance field — 6 to 72 h"
        right={
          <div className="flex overflow-hidden rounded border border-grid">
            {IMD.map((c) => (
              <button
                key={c.mm}
                type="button"
                onClick={() => setThreshold(c.mm)}
                className={clsx(
                  'px-2.5 py-1 text-[11px]',
                  threshold === c.mm ? 'bg-teal/20 font-semibold text-teal' : 'text-muted hover:text-ink',
                )}
                title={c.label}
              >
                {c.mm} mm
              </button>
            ))}
          </div>
        }
        bodyClass="relative"
      >
        {rainRes.error && !rainRes.data ? (
          <ErrorBox error={rainRes.error} onRetry={rainRes.reload} />
        ) : !rainRes.data ? (
          <Spinner label="Loading forecast grid" />
        ) : (
          <MapCanvas
            wards={wardsRes.data}
            layer="p_flood"
            points={points}
            pointLabel={`q90 vs ${threshold} mm`}
            overlay={
              <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted">
                forecast · lead {rainRes.data.lead_h} h · {IMD.find((c) => c.mm === threshold)?.label}{' '}
                ≥ {threshold} mm · issued {hhmm(t)} UTC
              </div>
            }
          />
        )}
      </Panel>

      <div className="grid min-h-0 grid-rows-[auto_auto_1fr] gap-2">
        <Panel title="Lead stepper (6 h blocks)">
          <div className="p-3">
            <div className="flex flex-wrap gap-1">
              {LEADS.map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setLead(h)}
                  className={clsx(
                    'rounded border px-2.5 py-1 text-[11.5px]',
                    leadH === h
                      ? 'border-teal/50 bg-teal/15 font-semibold text-teal'
                      : 'border-grid text-muted hover:text-ink',
                  )}
                >
                  +{h} h
                </button>
              ))}
            </div>
            {forecastBlock && (
              <dl className="mt-3 space-y-1 text-[11.5px]">
                {Object.entries(forecastBlock.thresholds || {}).map(([mm, p]) => (
                  <div key={mm} className="flex justify-between">
                    <dt className="text-muted">P(24 h &gt; {mm} mm)</dt>
                    <dd className="tabular text-ink">{pct(p)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mt-2 text-[10.5px] leading-relaxed text-dim">
              The grid carries q10/q50/q90 per cell. The map shades q90 against the selected IMD
              category — derived client-side, since no endpoint publishes a per-category exceedance
              raster.
            </p>
          </div>
        </Panel>

        <Panel title="RainFuse correction">
          <div className="p-3 text-[11.5px] leading-relaxed text-muted">
            Side-by-side raw ECMWF vs RainFuse vs observed needs three grids per issue time; the
            current contract publishes one. The comparison lives in the Verification view&apos;s
            ablation table, where the raw-NWP baseline row is the same claim in numbers.
          </div>
        </Panel>

        <Panel title="Quantile spread — wettest 12 cells" bodyClass="min-h-0">
          {fan.length ? (
            <div className="absolute inset-0 p-1 pb-3">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={fan} margin={{ top: 10, right: 12, bottom: 4, left: -18 }}>
                  <CartesianGrid stroke="#1f2b40" vertical={false} />
                  <XAxis dataKey="cell" hide />
                  <YAxis
                    stroke="#5d738f"
                    tick={{ fontSize: 10, fill: '#8ba0bd' }}
                    tickFormatter={(v) => `${v}`}
                  />
                  <Tooltip
                    contentStyle={{ background: '#111a2c', border: '1px solid #1f2b40', borderRadius: 6, fontSize: 12 }}
                    labelStyle={{ color: '#8ba0bd' }}
                    formatter={(v, n) => [`${num(v, 1)} mm`, n === 'band' ? 'q10→q90 band' : n]}
                  />
                  <Bar dataKey="q10" stackId="a" fill="transparent" />
                  <Bar dataKey="band" stackId="a" radius={[3, 3, 0, 0]}>
                    {fan.map((f) => (
                      <Cell key={f.cell} fill={f.q90 >= threshold ? '#ef4444' : '#14b8a6'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Spinner label="Loading quantiles" />
          )}
        </Panel>
      </div>
    </div>
  )
}
