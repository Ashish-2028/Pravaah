import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { useMetrics } from '../lib/hooks'
import { num } from '../lib/format'

const AXIS = { stroke: '#5d738f', tick: { fontSize: 10, fill: '#8ba0bd' }, tickLine: false }
const TIP = {
  contentStyle: {
    background: '#111a2c',
    border: '1px solid #1f2b40',
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: '#8ba0bd' },
}
const SERIES_COLORS = ['#14b8a6', '#f59e0b', '#ef4444', '#8ba0bd', '#7dd3fc']

function ProofTag({ id, children }) {
  return (
    <span className="flex items-center">
      <span className="mr-2 rounded bg-teal/15 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wider text-teal">
        {id}
      </span>
      <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
        {children}
      </span>
    </span>
  )
}

function Ablation({ rows }) {
  if (!rows?.length) return <div className="p-4 text-sm text-muted">No ablation rows.</div>
  const best = rows.reduce((a, b) => (b.csi > a.csi ? b : a), rows[0])
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-grid text-left text-[10px] uppercase tracking-wider text-muted">
            <th className="px-3 py-2 font-semibold">Configuration</th>
            <th className="px-3 py-2 text-right font-semibold">CSI ↑</th>
            <th className="px-3 py-2 text-right font-semibold">POD ↑</th>
            <th className="px-3 py-2 text-right font-semibold">FAR ↓</th>
            <th className="px-3 py-2 text-right font-semibold">Brier ↓</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isBest = r.config === best.config
            return (
              <tr
                key={r.config}
                className={isBest ? 'border-b border-grid bg-teal/10' : 'border-b border-grid/60'}
              >
                <td className="px-3 py-2">
                  <span className={isBest ? 'font-semibold text-teal' : 'text-ink'}>{r.config}</span>
                  {isBest && (
                    <span className="ml-2 text-[9.5px] uppercase tracking-wider text-teal">best</span>
                  )}
                </td>
                <td className="tabular px-3 py-2 text-right text-ink">{num(r.csi, 3)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{num(r.pod, 3)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{num(r.far, 3)}</td>
                <td className="tabular px-3 py-2 text-right text-ink">{num(r.brier, 3)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[10.5px] leading-relaxed text-dim">
        P-1 · Fusion works if the all-sources row beats every ablated row and the raw NWP baseline on
        CSI, POD and FAR simultaneously.
      </p>
    </div>
  )
}

function Reliability({ reliability }) {
  const heads = Object.keys(reliability || {})
  const [head, setHead] = useState(heads[0])
  const active = head && reliability[head] ? head : heads[0]
  const points = (reliability?.[active] || []).map((p) => ({
    x: p.predicted * 100,
    y: p.observed * 100,
    count: p.count,
  }))

  return (
    <div className="absolute inset-0 flex flex-col">
      {heads.length > 1 && (
        <div className="flex gap-1 px-3 pt-2">
          {heads.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setHead(h)}
              className={
                h === active
                  ? 'rounded border border-teal/50 bg-teal/15 px-2 py-0.5 text-[10.5px] text-teal'
                  : 'rounded border border-grid px-2 py-0.5 text-[10.5px] text-muted hover:text-ink'
              }
            >
              {h}
            </button>
          ))}
        </div>
      )}
      <div className="min-h-0 flex-1 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 14, bottom: 18, left: -10 }}>
            <CartesianGrid stroke="#1f2b40" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[0, 100]}
              {...AXIS}
              tickFormatter={(v) => `${v}%`}
              label={{ value: 'Forecast probability', position: 'insideBottom', offset: -10, fill: '#5d738f', fontSize: 10 }}
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[0, 100]}
              {...AXIS}
              tickFormatter={(v) => `${v}%`}
            />
            <ZAxis type="number" dataKey="count" range={[40, 180]} />
            <Tooltip
              {...TIP}
              cursor={{ stroke: '#1f2b40' }}
              formatter={(v, n) => [`${Number(v).toFixed(1)}%`, n === 'x' ? 'predicted' : 'observed']}
            />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
              stroke="#f59e0b"
              strokeDasharray="5 4"
              ifOverflow="extendDomain"
            />
            <Scatter data={points} fill="#14b8a6" />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="px-3 pb-2 text-[10.5px] leading-relaxed text-dim">
        P-2 · Perfect calibration is the amber diagonal. Marker size is bin count. When PRAVAAH says
        80%, it should happen about 80% of the time.
      </p>
    </div>
  )
}

function SkillVsLead({ rows }) {
  const { data, models } = useMemo(() => {
    const byLead = new Map()
    const seen = new Set()
    ;(rows || []).forEach((r) => {
      seen.add(r.model)
      const cur = byLead.get(r.lead_h) || { lead_h: r.lead_h }
      cur[r.model] = r.csi
      byLead.set(r.lead_h, cur)
    })
    return {
      data: [...byLead.values()].sort((a, b) => a.lead_h - b.lead_h),
      models: [...seen],
    }
  }, [rows])

  if (!data.length) return <div className="p-4 text-sm text-muted">No skill curve.</div>

  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="min-h-0 flex-1 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 18, left: -12 }}>
            <CartesianGrid stroke="#1f2b40" />
            <XAxis
              dataKey="lead_h"
              {...AXIS}
              tickFormatter={(v) => `${v} h`}
              label={{ value: 'Lead time', position: 'insideBottom', offset: -10, fill: '#5d738f', fontSize: 10 }}
            />
            <YAxis {...AXIS} domain={[0, 'auto']} />
            <Tooltip {...TIP} formatter={(v, n) => [num(v, 3), n]} labelFormatter={(v) => `Lead ${v} h`} />
            <Legend wrapperStyle={{ fontSize: 11, color: '#8ba0bd' }} />
            {models.map((m, i) => (
              <Line
                key={m}
                type="monotone"
                dataKey={m}
                name={m}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="px-3 pb-2 text-[10.5px] leading-relaxed text-dim">
        The honest decay. Nowcast skill falls away after roughly 2 h — we publish the curve rather
        than a single headline number.
      </p>
    </div>
  )
}

function LeadTime({ rows }) {
  if (!rows?.length) return <div className="p-4 text-sm text-muted">No lead-time comparison.</div>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-grid text-left text-[10px] uppercase tracking-wider text-muted">
            <th className="px-3 py-2 font-semibold">Event</th>
            <th className="px-3 py-2 font-semibold">PRAVAAH crossing</th>
            <th className="px-3 py-2 font-semibold">IMD CAP sent</th>
            <th className="px-3 py-2 text-right font-semibold">Minutes gained</th>
            <th className="px-3 py-2 text-right font-semibold">Matched FAR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.event} className="border-b border-grid/60">
              <td className="px-3 py-2 text-ink">{r.event}</td>
              <td className="tabular px-3 py-2 text-teal">{r.pravaah_crossing_utc}</td>
              <td className="tabular px-3 py-2 text-muted">{r.imd_cap_sent_utc}</td>
              <td className="tabular px-3 py-2 text-right text-lg font-semibold text-amber">
                +{num(r.minutes_gained, 0)}
              </td>
              <td className="tabular px-3 py-2 text-right text-ink">{num(r.matched_far, 2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-3 py-2 text-[10.5px] leading-relaxed text-dim">
        P-3 · Minutes gained over IMD&apos;s own public CAP stream, compared at a matched false-alarm
        ratio so the gain cannot be bought by crying wolf.
      </p>
    </div>
  )
}

export default function Verify() {
  const res = useMetrics()

  if (res.error && !res.data) {
    return (
      <div className="p-4">
        <ErrorBox error={res.error} onRetry={res.reload} />
      </div>
    )
  }
  if (!res.data) return <Spinner label="Loading verification metrics" />

  const m = res.data
  const notes = m.notes || {}
  const isFake =
    Object.values(notes).some((v) => /fake/i.test(String(v))) ||
    (m.ablation || []).some((r) => /\[FAKE\]/i.test(r.config))

  return (
    <div className="h-full overflow-y-auto p-2">
      {isFake && (
        <div className="mb-2 rounded-lg border border-amber/40 bg-amber/10 px-3 py-2 text-[11.5px] leading-relaxed text-amber">
          These metrics are the placeholder artefacts written by the fake generator. The view is
          wired to <code className="text-ink">/api/verify/metrics</code> and will show the real
          numbers the moment <code className="text-ink">reports/metrics.json</code> is regenerated —
          no UI change required.
          {notes.status ? ` (${notes.status})` : ''}
        </div>
      )}

      <div className="grid gap-2 xl:grid-cols-2">
        <Panel title={<ProofTag id="P-1">Ablation — does fusion actually help?</ProofTag>}>
          <Ablation rows={m.ablation} />
        </Panel>

        <Panel title={<ProofTag id="P-3">Lead time vs IMD CAP</ProofTag>}>
          <LeadTime rows={m.leadtime_vs_cap} />
        </Panel>

        <Panel
          title={<ProofTag id="P-2">Reliability diagram</ProofTag>}
          className="min-h-[340px]"
          bodyClass="min-h-0"
        >
          <Reliability reliability={m.reliability} />
        </Panel>

        <Panel title="Skill vs lead time" className="min-h-[340px]" bodyClass="min-h-0">
          <SkillVsLead rows={m.skill_vs_lead} />
        </Panel>
      </div>

      <Panel title="Split methodology" className="mt-2">
        <div className="grid gap-3 p-3 text-[12px] leading-relaxed text-muted md:grid-cols-2">
          <p>
            Splits are by <span className="text-ink">event and year</span>, never random. A random
            split over gridded weather leaks neighbouring pixels and hours across the boundary and
            inflates every score.
          </p>
          <p>
            No look-ahead: every feature at time t0 is read through the cube&apos;s latest-at-t0
            accessor, so nothing the model sees was published after the forecast was issued. The
            replay view enforces the same law at serve time.
          </p>
          {Object.entries(notes).map(([k, v]) => (
            <p key={k} className="md:col-span-2">
              <span className="text-[10px] uppercase tracking-wider text-dim">{k}: </span>
              <span className="text-ink">{String(v)}</span>
            </p>
          ))}
        </div>
      </Panel>

      <div className="p-3 text-center text-[10.5px] text-dim">
        Every probability in PRAVAAH is displayed as a percentage. Rendered directly from{' '}
        <code>/api/verify/metrics</code> — a static read of <code>reports/</code>, zero runtime risk.
      </div>
    </div>
  )
}
