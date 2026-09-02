import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { num } from '../lib/format'
import { useChartTheme } from '../lib/theme'

// Skill vs lead, drawn so it can actually be read.
//
// /api/verify/metrics returns skill_vs_lead as a flat list of
// {lead_h, model, csi} rows, and `model` is a FAMILY plus a HEAD glued
// together: "RainCast p5", "persistence acc20", "raw NWP very_heavy". There are
// sixteen of them. Plotting all sixteen — which is what this used to do — puts
// sixteen legend chips above a 150 px panel, where they wrap onto four rows,
// eat the plot area and overlap the lines. Worse, the old Nowcast copy of this
// chart drew every one of the sixteen in the SAME colour, so even an unwrapped
// legend could not have told you which line was which.
//
// The fix is to say what the chart is for. ONE head at a time: the model and
// the baselines it has to beat at that threshold, which is two or three lines.
// That is the comparison the "honest decay" claim actually rests on.
//
// The legend is DOM, not recharts' <Legend/>, and it lives outside the plotting
// box in its own row. A recharts legend is laid out inside the chart's box and
// steals height from the plot when it wraps; a flex row above it cannot.

const HEAD_ORDER = ['p5', 'p10', 'acc10', 'acc20', 'heavy', 'very_heavy']

/** The millimetres, not the field name — same rule as lib/format.js. */
const HEAD_LABEL = {
  p5: 'P(> 5 mm)',
  p10: 'P(> 10 mm)',
  acc10: 'accum ≥ 10 mm',
  acc20: 'accum ≥ 20 mm',
  heavy: 'IMD heavy (≥ 64.5 mm)',
  very_heavy: 'IMD very heavy (≥ 115.6 mm)',
}

// The model families keep a stable colour across every head, so switching head
// does not re-teach the reader which line is the baseline.
const FAMILY_COLOR = {
  RainCast: '#14b8a6',
  RainFuse: '#38bdf8',
  persistence: '#f59e0b',
  'raw GFS': '#8ba0bd',
  'raw NWP': '#8ba0bd',
}
const FALLBACK_COLORS = ['#a78bfa', '#f472b6', '#7dd3fc', '#fbbf24']

/** Ours first, then the baselines — the reading order of the claim. */
const FAMILY_RANK = { RainCast: 0, RainFuse: 0, persistence: 1, 'raw GFS': 2, 'raw NWP': 2 }

/** "raw GFS acc10" -> {family: 'raw GFS', head: 'acc10'}. The head is always
 *  the last whitespace-separated token; "very_heavy" is one token by design. */
function split(model) {
  const s = String(model || '').trim()
  const i = s.lastIndexOf(' ')
  if (i < 0) return { family: s, head: '' }
  return { family: s.slice(0, i), head: s.slice(i + 1) }
}

export function groupSkill(rows) {
  const heads = new Map() // head -> { families:Set, byLead:Map }
  ;(rows || []).forEach((r) => {
    const { family, head } = split(r.model)
    if (!heads.has(head)) heads.set(head, { families: new Set(), byLead: new Map() })
    const g = heads.get(head)
    g.families.add(family)
    const row = g.byLead.get(r.lead_h) || { lead_h: r.lead_h }
    row[family] = r.csi
    g.byLead.set(r.lead_h, row)
  })

  const out = new Map()
  heads.forEach((g, head) => {
    out.set(head, {
      head,
      label: HEAD_LABEL[head] || head,
      data: [...g.byLead.values()].sort((a, b) => a.lead_h - b.lead_h),
      families: [...g.families].sort(
        (a, b) => (FAMILY_RANK[a] ?? 9) - (FAMILY_RANK[b] ?? 9) || a.localeCompare(b),
      ),
    })
  })

  const order = [...out.keys()].sort((a, b) => {
    const ia = HEAD_ORDER.indexOf(a)
    const ib = HEAD_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b)
  })
  return { heads: order, groups: out }
}

function colorFor(family, i) {
  return FAMILY_COLOR[family] || FALLBACK_COLORS[i % FALLBACK_COLORS.length]
}

/**
 * @param rows        skill_vs_lead rows straight from the API
 * @param preferHead  which head to open on ('p5' | 'p10' | …); ignored if absent
 * @param footnote    the sentence under the plot, if the caller has room for one
 * @param compact     narrow rail styling (right-hand panels)
 */
export default function SkillChart({ rows, preferHead, footnote, compact = false }) {
  const ct = useChartTheme()
  const { heads, groups } = useMemo(() => groupSkill(rows), [rows])
  const [picked, setPicked] = useState(null)

  const head =
    (picked && groups.has(picked) && picked) ||
    (preferHead && groups.has(preferHead) && preferHead) ||
    heads[0]
  const g = head ? groups.get(head) : null

  if (!g || !g.data.length) {
    return <div className="p-4 text-sm text-muted">No skill curve in this metrics file.</div>
  }

  return (
    <div className="absolute inset-0 flex flex-col">
      {/* Head selector. A <select> rather than a button strip on purpose: six
          heads of button will wrap to three rows in a 330 px rail and re-create
          exactly the collision this chart was rebuilt to remove. */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 px-2.5 pb-1 pt-2">
        <label
          className="text-[9.5px] uppercase tracking-[0.14em] text-dim"
          htmlFor={`head-${head}`}
        >
          Head
        </label>
        <select
          id={`head-${head}`}
          value={head}
          onChange={(e) => setPicked(e.target.value)}
          className="min-w-0 flex-1 rounded border border-grid bg-bg px-1.5 py-0.5 text-[11px] text-ink outline-none focus:border-teal"
        >
          {heads.map((h) => (
            <option key={h} value={h}>
              {HEAD_LABEL[h] || h}
            </option>
          ))}
        </select>
      </div>

      {/* Legend, outside the plot box and scrollable rather than wrapping. */}
      <div className="flex shrink-0 items-center gap-3 overflow-x-auto whitespace-nowrap px-2.5 pb-1">
        {g.families.map((f, i) => (
          <span key={f} className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted">
            <span
              className="h-0.5 w-3.5 shrink-0 rounded-full"
              style={{ background: colorFor(f, i) }}
            />
            {f}
          </span>
        ))}
      </div>

      {/* A LINE CHART NEEDS TWO POINTS. The RainFuse heads (IMD heavy / very
          heavy) are scored at a single lead — 24 h — so plotting them draws two
          lonely dots on an axis with nothing to decay along, which looks broken
          and reads as no data. At one lead the comparison is still a comparison,
          so it is drawn as one: the number, the baseline, and the gap. */}
      {g.data.length < 2 ? (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
          <div className="text-[10.5px] text-dim">
            Scored at a single lead ({g.data[0].lead_h} h), so there is no decay curve to draw.
          </div>
          <dl className="mt-2 space-y-2">
            {g.families.map((f, i) => {
              const v = g.data[0][f]
              const best = Math.max(...g.families.map((k) => g.data[0][k] || 0), 1e-9)
              return (
                <div key={f}>
                  <div className="flex items-baseline justify-between gap-2">
                    <dt className="min-w-0 truncate text-[11px] text-muted">{f}</dt>
                    <dd className="tabular shrink-0 text-[13px] font-semibold text-ink">
                      {v === undefined ? '—' : num(v, 3)}
                    </dd>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-grid">
                    <div
                      className="h-full rounded"
                      style={{
                        width: `${Math.max(2, Math.min(100, ((v || 0) / best) * 100))}%`,
                        background: colorFor(f, i),
                      }}
                    />
                  </div>
                </div>
              )
            })}
          </dl>
          <div className="mt-2 text-[10px] uppercase tracking-wider text-dim">CSI ↑</div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 px-1 pb-1">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={g.data} margin={{ top: 6, right: 14, bottom: compact ? 4 : 16, left: -14 }}>
              <CartesianGrid stroke={ct.grid} />
              <XAxis
                dataKey="lead_h"
                stroke={ct.axis}
                tick={{ fontSize: 10, fill: ct.tick }}
                tickLine={false}
                tickFormatter={(v) => `${v} h`}
                label={
                  compact
                    ? undefined
                    : {
                        value: 'Lead time',
                        position: 'insideBottom',
                        offset: -8,
                        fill: ct.axis,
                        fontSize: 10,
                      }
                }
              />
              <YAxis
                stroke={ct.axis}
                tick={{ fontSize: 10, fill: ct.tick }}
                tickLine={false}
                domain={[0, 'auto']}
              />
              <Tooltip
                contentStyle={{
                  background: ct.tooltipBg,
                  border: `1px solid ${ct.grid}`,
                  borderRadius: 6,
                  fontSize: 12,
                }}
                labelStyle={{ color: ct.tick }}
                formatter={(v, n) => [num(v, 3), n]}
                labelFormatter={(v) => `Lead ${v} h · CSI`}
              />
              {g.families.map((f, i) => (
                <Line
                  isAnimationActive={false}
                  key={f}
                  type="monotone"
                  dataKey={f}
                  name={f}
                  stroke={colorFor(f, i)}
                  strokeWidth={FAMILY_RANK[f] === 0 ? 2.2 : 1.5}
                  strokeDasharray={FAMILY_RANK[f] === 2 ? '4 3' : undefined}
                  dot={{ r: 2.5 }}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {footnote && (
        <p className="shrink-0 px-3 pb-2 text-[10.5px] leading-relaxed text-dim">{footnote}</p>
      )}
    </div>
  )
}
