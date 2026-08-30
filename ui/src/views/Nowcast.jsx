import { useMemo, useState } from 'react'
import clsx from 'clsx'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import MapCanvas from '../components/MapCanvas'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { useMetrics, useRain, useWards } from '../lib/hooks'
import { hhmm, num, pct } from '../lib/format'
import { useStore } from '../lib/store'

const LEADS = [0.5, 1, 2, 3, 4, 6]

export default function Nowcast() {
  const { event, t, lead, setLead } = useStore()
  const [threshold, setThreshold] = useState('p15')
  const rainRes = useRain(event, t, 'nowcast', Math.round(lead))
  const wardsRes = useWards(event, t)
  const metrics = useMetrics()

  const points = useMemo(() => {
    if (!rainRes.data?.cells) return null
    return rainRes.data.cells.map((c) => ({ lat: c.lat, lon: c.lon, value: c[threshold] }))
  }, [rainRes.data, threshold])

  const stats = useMemo(() => {
    const cells = rainRes.data?.cells || []
    if (!cells.length) return null
    const vals = cells.map((c) => c[threshold])
    return {
      max: Math.max(...vals),
      mean: vals.reduce((a, b) => a + b, 0) / vals.length,
      hot: vals.filter((v) => v >= 0.5).length,
      cells: cells.length,
      q90: Math.max(...cells.map((c) => c.q90)),
      q50: Math.max(...cells.map((c) => c.q50)),
    }
  }, [rainRes.data, threshold])

  const skill = useMemo(() => {
    const rows = metrics.data?.skill_vs_lead || []
    const byLead = new Map()
    rows.forEach((r) => {
      const cur = byLead.get(r.lead_h) || { lead_h: r.lead_h }
      cur[r.model] = r.csi
      byLead.set(r.lead_h, cur)
    })
    return {
      data: [...byLead.values()].sort((a, b) => a.lead_h - b.lead_h),
      models: [...new Set(rows.map((r) => r.model))],
    }
  }, [metrics.data])

  return (
    <div className="grid h-full grid-cols-[1fr_330px] gap-2 overflow-hidden p-2">
      <Panel
        title="Rain probability field — 0 to 6 h"
        right={
          <div className="flex items-center gap-2">
            <div className="flex overflow-hidden rounded border border-grid">
              {[
                ['p15', 'P(>15 mm)'],
                ['p50', 'P(>50 mm)'],
              ].map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => setThreshold(k)}
                  className={clsx(
                    'px-2.5 py-1 text-[11px]',
                    threshold === k ? 'bg-teal/20 font-semibold text-teal' : 'text-muted hover:text-ink',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        }
        bodyClass="relative"
      >
        {rainRes.error && !rainRes.data ? (
          <ErrorBox error={rainRes.error} onRetry={rainRes.reload} />
        ) : !rainRes.data ? (
          <Spinner label="Loading rain grid" />
        ) : (
          <MapCanvas
            wards={wardsRes.data}
            layer="p_flood"
            points={points}
            pointLabel={threshold === 'p15' ? 'P(>15 mm)' : 'P(>50 mm)'}
            overlay={
              <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted">
                {rainRes.data.kind} · lead {rainRes.data.lead_h} h · issued {hhmm(t)} UTC ·{' '}
                {rainRes.data.cells?.length || 0} cells
              </div>
            }
          />
        )}
      </Panel>

      <div className="grid min-h-0 grid-rows-[auto_auto_1fr] gap-2">
        <Panel title="Lead stepper">
          <div className="p-3">
            <div className="flex flex-wrap gap-1">
              {LEADS.map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setLead(h)}
                  className={clsx(
                    'rounded border px-2.5 py-1 text-[11.5px]',
                    lead === h
                      ? 'border-teal/50 bg-teal/15 font-semibold text-teal'
                      : 'border-grid text-muted hover:text-ink',
                  )}
                >
                  +{h} h
                </button>
              ))}
            </div>
            <p className="mt-2 text-[10.5px] leading-relaxed text-dim">
              The backend serves one precomputed grid per issue time; the stepper stamps the
              requested lead onto it. Skill below shows what that lead is actually worth.
            </p>
          </div>
        </Panel>

        <Panel title="Field summary">
          {stats ? (
            <dl className="grid grid-cols-2 gap-x-3 gap-y-2 p-3 text-[11.5px]">
              {[
                ['Max probability', pct(stats.max)],
                ['Mean probability', pct(stats.mean)],
                ['Cells ≥ 50%', `${stats.hot} / ${stats.cells}`],
                ['Peak q50', `${num(stats.q50, 1)} mm`],
                ['Peak q90', `${num(stats.q90, 1)} mm`],
              ].map(([k, v]) => (
                <div key={k}>
                  <dt className="text-[9.5px] uppercase tracking-wider text-muted">{k}</dt>
                  <dd className="tabular text-base font-semibold text-ink">{v}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <div className="p-3 text-xs text-muted">No grid loaded.</div>
          )}
        </Panel>

        <Panel title="Skill vs lead — the honest decay" bodyClass="min-h-0">
          {skill.data.length ? (
            <div className="absolute inset-0 p-1 pb-3">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={skill.data} margin={{ top: 10, right: 14, bottom: 4, left: -14 }}>
                  <CartesianGrid stroke="#1f2b40" />
                  <XAxis
                    dataKey="lead_h"
                    stroke="#5d738f"
                    tick={{ fontSize: 10, fill: '#8ba0bd' }}
                    tickFormatter={(v) => `${v}h`}
                  />
                  <YAxis stroke="#5d738f" tick={{ fontSize: 10, fill: '#8ba0bd' }} />
                  <Tooltip
                    contentStyle={{ background: '#111a2c', border: '1px solid #1f2b40', borderRadius: 6, fontSize: 12 }}
                    labelStyle={{ color: '#8ba0bd' }}
                    formatter={(v, n) => [num(v, 3), n]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {skill.models.map((mm) => (
                    <Line key={mm} type="monotone" dataKey={mm} stroke="#14b8a6" strokeWidth={2} dot={{ r: 3 }} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <Spinner label="Loading skill curve" />
          )}
        </Panel>
      </div>
    </div>
  )
}
