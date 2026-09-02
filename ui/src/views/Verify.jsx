import { useState } from 'react'
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import SkillChart from '../components/SkillChart'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { useMetrics } from '../lib/hooks'
import { num } from '../lib/format'
import { useChartTheme } from '../lib/theme'

// Recharts takes colours as JS values, so — like the map — these do not come
// along for free when the CSS custom properties swap. They are read from
// CHART_THEME instead. `ct` is threaded through as a prop rather than hooked
// in each chart so the module-scope helpers stay pure.
const axisOf = (ct) => ({ stroke: ct.axis, tick: { fontSize: 10, fill: ct.tick }, tickLine: false })
const tipOf = (ct) => ({
  contentStyle: {
    background: ct.tooltipBg,
    border: `1px solid ${ct.grid}`,
    borderRadius: 6,
    fontSize: 12,
  },
  labelStyle: { color: ct.tick },
})

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
    <div className="max-h-[46vh] overflow-auto">
      <table className="w-full min-w-[420px] text-[12.5px]">
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
  const ct = useChartTheme()
  const AXIS = axisOf(ct)
  const TIP = tipOf(ct)
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
      {/* Fourteen heads. As a button strip they wrapped into four rows and ate
          the plot; as a select they are one row at any panel width. */}
      {heads.length > 1 && (
        <div className="flex shrink-0 items-center gap-2 px-3 pb-1 pt-2">
          <label className="text-[9.5px] uppercase tracking-[0.14em] text-dim" htmlFor="rel-head">
            Head
          </label>
          <select
            id="rel-head"
            value={active}
            onChange={(e) => setHead(e.target.value)}
            className="min-w-0 max-w-[260px] flex-1 rounded border border-grid bg-bg px-1.5 py-0.5 text-[11px] text-ink outline-none focus:border-teal"
          >
            {heads.map((h) => (
              <option key={h} value={h}>
                {h}
              </option>
            ))}
          </select>
          <span className="tabular shrink-0 text-[10px] text-dim">{points.length} bins</span>
        </div>
      )}
      <div className="min-h-0 flex-1 p-2 pt-0">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 8, right: 14, bottom: 18, left: -10 }}>
            <CartesianGrid stroke={ct.grid} />
            <XAxis
              type="number"
              dataKey="x"
              domain={[0, 100]}
              {...AXIS}
              tickFormatter={(v) => `${v}%`}
              label={{ value: 'Forecast probability', position: 'insideBottom', offset: -10, fill: ct.axis, fontSize: 10 }}
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
              cursor={{ stroke: ct.grid }}
              formatter={(v, n) => [`${Number(v).toFixed(1)}%`, n === 'x' ? 'predicted' : 'observed']}
            />
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: 100, y: 100 }]}
              stroke="#f59e0b"
              strokeDasharray="5 4"
              ifOverflow="extendDomain"
            />
            <Scatter isAnimationActive={false} data={points} fill="#14b8a6" />
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


function LeadTime({ rows }) {
  if (!rows?.length) return <div className="p-4 text-sm text-muted">No lead-time comparison.</div>
  return (
    <div className="max-h-[46vh] overflow-auto">
      <table className="w-full min-w-[420px] text-[12.5px]">
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
          className="min-h-[380px]"
          bodyClass="min-h-0"
        >
          <Reliability reliability={m.reliability} />
        </Panel>

        <Panel title="Skill vs lead time" className="min-h-[380px]" bodyClass="min-h-0">
          <SkillChart
            rows={m.skill_vs_lead}
            footnote="The honest decay, one exceedance head at a time: the model against the
              persistence and raw-NWP baselines it has to beat. Nowcast skill falls away after
              roughly 2 h — we publish the curve rather than a single headline number."
          />
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
