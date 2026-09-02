import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { num, pct } from '../lib/format'
import { useChartTheme, useTheme } from '../lib/theme'

// The response curve, and the boundary that makes it worth drawing.
//
// /api/sandbox/curve sweeps event rainfall from 0 to 120 mm and reports the
// city-max ward probability at each step. Past 25.3 mm — the highest split the
// trained booster has on `rain_sum` — a gradient-boosted tree is CONSTANT, so
// the curve flattens. That flat stretch is the honest part of this screen, and
// it only reads as honest if it is drawn and labelled rather than described.
//
// SkillChart's conventions are followed deliberately, for the same reasons
// written up at the top of that file: the legend is DOM, in its own row above
// the plot box, never recharts' <Legend/>, which is laid out INSIDE the box and
// steals plot height the moment it wraps.
//
// ------------------------------------------------------------------------
// THE CURVE IS NOT PERFECTLY FLAT AFTER 25.3 mm, AND THAT IS NOT A BUG.
//
// The sweep is not one-dimensional. serve/sandbox.py moves the peak-hour
// feature with the total (`rain_max = 0.28 * rain_sum`, a typical peak-hour
// share of a burst), because a 120 mm six-hour total with a 4 mm peak hour is
// not a storm that exists. So the point at which the ANSWER stops moving is
// the LATER of the two evidence limits expressed in sweep units:
//
//     rain_sum stops mattering at 25.3 mm
//     rain_max stops mattering at 29.75 / 0.28 = 106.3 mm of sweep
//
// Measured, at rain_prev3d=10 / rain_prev7d=20: max_p holds at 0.8108 from
// 26.1 mm all the way to 104.3 mm, then steps once to 0.8219 at 109.6 mm and
// is constant thereafter. That single late step is rain_max crossing its own
// last split, and this chart marks it rather than letting it look like the
// model still responds to rainfall.
const PEAK_SHARE = 0.28

/**
 * The sentence that explains the one late step, or null when there is no step
 * to explain.
 *
 * Exported because it does NOT fit under the plot. Measured at 1280 × 700: the
 * curve panel's body is 170 px, the wrapped legend takes 46 and two paragraphs
 * of footnote take 117, which left the chart 7 px and drew an empty box. The
 * required sentence stays here where the shading is; this second one moves to
 * the scrolling rail, which has room for it — same house rule as the panels
 * themselves, just applied to prose.
 */
export function peakStepNote(rainMaxLimitMm) {
  if (typeof rainMaxLimitMm !== 'number' || rainMaxLimitMm <= 0) return null
  return (
    `The curve's sweep raises the peak hour with the total (${PEAK_SHARE}× of it), so max P(flood) ` +
    `takes one last step near ${Math.round(rainMaxLimitMm / PEAK_SHARE)} mm — that is the peak-hour ` +
    `feature crossing its own final split at ${rainMaxLimitMm} mm. Past that point nothing moves at all.`
  )
}

export default function ResponseCurve({ curve, rainMaxLimitMm, atRainMm = null, compactAxis = false }) {
  const ct = useChartTheme()
  const theme = useTheme((s) => s.theme)
  const amber = theme === 'dark' ? '#f59e0b' : '#b45309'

  const points = curve?.points || []
  if (!points.length) {
    return <div className="p-4 text-sm text-muted">No response curve returned.</div>
  }

  const limit = curve.evidence_limit_mm
  const hi = points[points.length - 1].rain_mm
  // Where the SECOND rain feature runs out of evidence, in the sweep's units.
  const peakCross =
    typeof rainMaxLimitMm === 'number' && rainMaxLimitMm > 0 ? rainMaxLimitMm / PEAK_SHARE : null
  const peakInRange = peakCross !== null && peakCross > limit && peakCross < hi

  return (
    <div className="absolute inset-0 flex flex-col">
      {/* Legend + the boundary's own caption, outside the plot box. Kept to one
          line of chips: this row is `shrink-0`, so every extra wrapped line
          comes straight out of the plot's height. */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-2.5 gap-y-0.5 px-2.5 pb-1 pt-1.5">
        <span className="flex items-center gap-1.5 text-[10px] text-muted">
          <span className="h-0.5 w-3.5 rounded-full" style={{ background: ct.line }} />
          max P(flood)
        </span>
        <span className="flex items-center gap-1.5 text-[10px] text-muted">
          <span className="h-0.5 w-3.5 rounded-full" style={{ background: '#8ba0bd' }} />
          wards over 60%
        </span>
        <span
          className="ml-auto flex items-center gap-1.5 text-[10px] font-semibold"
          style={{ color: amber }}
          title="Shaded: the trained booster has no split on rain_sum above this value, so its answer is constant there."
        >
          <span
            className="h-2.5 w-3.5 shrink-0 rounded-sm border"
            style={{ borderColor: amber, background: `${amber}26` }}
          />
          beyond {num(limit, 1)} mm — no evidence
        </span>
      </div>

      <div className="min-h-[104px] flex-1 px-1 pb-1">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 6, right: 4, bottom: compactAxis ? 4 : 16, left: -18 }}>
            <CartesianGrid stroke={ct.grid} />
            {/* Shaded FIRST so every line and marker draws over it. */}
            <ReferenceArea
              x1={limit}
              x2={hi}
              yAxisId="p"
              fill={amber}
              fillOpacity={0.13}
              stroke="none"
              label={{
                value: 'no training evidence — model is flat here',
                position: 'insideTopLeft',
                fill: amber,
                fontSize: 9.5,
                offset: 8,
              }}
            />
            <ReferenceLine
              x={limit}
              yAxisId="p"
              stroke={amber}
              strokeWidth={1.6}
              strokeDasharray="4 3"
            />
            {/* The one late step, explained on the chart instead of ignored. */}
            {peakInRange && (
              <ReferenceLine
                x={Math.round(peakCross * 10) / 10}
                yAxisId="p"
                stroke={amber}
                strokeWidth={1}
                strokeOpacity={0.5}
                strokeDasharray="2 4"
              />
            )}
            {/* Where the sliders currently sit, so the chart and the controls
                are visibly the same experiment. */}
            {atRainMm !== null && atRainMm >= 0 && atRainMm <= hi && (
              <ReferenceLine x={atRainMm} yAxisId="p" stroke={ct.tick} strokeWidth={1} strokeOpacity={0.7} />
            )}
            <XAxis
              dataKey="rain_mm"
              type="number"
              domain={[0, hi]}
              stroke={ct.axis}
              tick={{ fontSize: 10, fill: ct.tick }}
              tickLine={false}
              tickFormatter={(v) => `${v}`}
              label={
                compactAxis
                  ? undefined
                  : {
                      value: 'Event rainfall, mm over 6 h (ERA5 scale)',
                      position: 'insideBottom',
                      offset: -8,
                      fill: ct.axis,
                      fontSize: 10,
                    }
              }
            />
            <YAxis
              yAxisId="p"
              stroke={ct.axis}
              tick={{ fontSize: 10, fill: ct.tick }}
              tickLine={false}
              domain={[0, 1]}
              tickFormatter={(v) => `${Math.round(v * 100)}%`}
            />
            <YAxis
              yAxisId="w"
              orientation="right"
              stroke={ct.axis}
              tick={{ fontSize: 10, fill: ct.tick }}
              tickLine={false}
              width={30}
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
              formatter={(v, n) => [n === 'max P(flood)' ? pct(v, 1) : num(v), n]}
              labelFormatter={(v) =>
                `${v} mm${v > limit ? ' · beyond the evidence limit' : ''}`
              }
            />
            <Line
              yAxisId="p"
              isAnimationActive={false}
              type="monotone"
              dataKey="max_p"
              name="max P(flood)"
              stroke={ct.line}
              strokeWidth={2.2}
              dot={false}
            />
            <Line
              yAxisId="w"
              isAnimationActive={false}
              type="monotone"
              dataKey="wards_over_60pct"
              name="wards over 60%"
              stroke="#8ba0bd"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p
        className="shrink-0 border-t border-grid px-3 py-1.5 text-[10.5px] leading-snug text-dim"
        title={peakInRange ? peakStepNote(rainMaxLimitMm) : undefined}
      >
        A gradient-boosted tree is constant above its highest split on a feature. This is a limit of
        our flood-label set, not a claim that heavier rain is harmless.
      </p>
    </div>
  )
}
