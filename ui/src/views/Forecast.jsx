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
import EventSelector, { ClockTag, useViewClock } from '../components/EventSelector'
import MapCanvas from '../components/MapCanvas'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { Prov, modelName } from '../components/Provenance'
import { useRain, useWards } from '../lib/hooks'
import { hhmm, num, pct } from '../lib/format'
import { useStore } from '../lib/store'
import { useChartTheme } from '../lib/theme'

// The official IMD heavy-rainfall categories, in mm/24 h.
const IMD = [
  { mm: 64.5, label: 'Heavy' },
  { mm: 115.6, label: 'Very heavy' },
  { mm: 204.5, label: 'Extremely heavy' },
]
const LEADS = [6, 12, 24, 48, 72]

// The two quantiles every forecast cell carries. Switching between them is a
// real change to what the map shades and it is honestly client-derived, unlike
// the lead — see the stepper note below.
const QUANTILES = [
  { key: 'q50', label: 'q50 · median' },
  { key: 'q90', label: 'q90 · wet tail' },
]

export default function Forecast() {
  const lead = useStore((s) => s.lead)
  const setLead = useStore((s) => s.setLead)
  const { event, t, isArchive, liveMissing } = useViewClock()
  const [threshold, setThreshold] = useState(64.5)
  const [quantile, setQuantile] = useState('q90')
  const leadH = LEADS.includes(lead) ? lead : 24
  const rainRes = useRain(event, t, 'forecast', leadH)
  const wardsRes = useWards(event, t)
  const ct = useChartTheme()
  // The provenance block names the NOWCAST source. It says nothing about the
  // 6-72 h head, so this view does not borrow that name for a number the
  // nowcast did not produce — it says the source is undeclared instead.
  const prov = rainRes.data?.provenance || null
  const forecastModel = modelName(prov?.forecast_source, null)

  const cells = rainRes.data?.cells || []

  // No endpoint returns per-threshold exceedance for the forecast head, so we
  // derive it client-side from the quantiles the grid DOES carry: a cell's q90
  // relative to the IMD category is the exceedance signal we can honestly show.
  const points = useMemo(() => {
    if (!cells.length) return null
    return cells.map((c) => ({
      lat: c.lat,
      lon: c.lon,
      value: Math.max(0, Math.min(1, c[quantile] / threshold)),
    }))
  }, [cells, threshold, quantile])

  const fan = useMemo(() => {
    if (!cells.length) return []
    const sorted = [...cells].sort((a, b) => b[quantile] - a[quantile]).slice(0, 12)
    return sorted.map((c) => ({
      cell: `${c.lat.toFixed(2)},${c.lon.toFixed(2)}`,
      q10: c.q10,
      band: c.q90 - c.q10,
      q50: c.q50,
      q90: c.q90,
      shown: c[quantile],
    }))
  }, [cells, quantile])

  const forecastBlock = rainRes.data?.forecast || null

  // WHICH LEAD IS ACTUALLY MODELLED, read from the response rather than
  // assumed. RainFuse currently ships a single head, and /api/rain serves one
  // grid per issue time — the `lead` parameter only stamps `lead_h` on it. So
  // exactly one button on the stepper is a distinct forecast and the rest are
  // that same field re-labelled. The UI says so out loud instead of implying
  // five forecasts exist.
  const modelledLead = typeof forecastBlock?.lead_h === 'number' ? forecastBlock.lead_h : null
  const leadIsModelled = modelledLead !== null && leadH === modelledLead

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-2">
      <EventSelector note="The exceedance field, the quantile spread and the category probabilities below all follow this selection." />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_340px] gap-2 overflow-hidden">
      <Panel
        title="Exceedance field — 6 to 72 h"
        right={
          <div className="flex items-center gap-2">
            <div className="flex overflow-hidden rounded border border-grid">
              {QUANTILES.map((q) => (
                <button
                  key={q.key}
                  type="button"
                  onClick={() => setQuantile(q.key)}
                  title={`Shade each cell's ${q.key} against the selected IMD category. Both quantiles are carried by the grid; the choice is a view, not a different model run.`}
                  className={clsx(
                    'px-2.5 py-1 text-[11px]',
                    quantile === q.key ? 'bg-teal/20 font-semibold text-teal' : 'text-muted hover:text-ink',
                  )}
                >
                  {q.label}
                </button>
              ))}
            </div>
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
            pointLabel={`${quantile} vs ${threshold} mm`}
            overlay={
              <div
                className={clsx(
                  'pointer-events-none absolute left-3 top-3 z-10 rounded-md border bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted',
                  isArchive ? 'border-amber/50' : 'border-grid',
                )}
              >
                <div className="mb-0.5">
                  <ClockTag isArchive={isArchive} event={event} t={t} liveMissing={liveMissing} />
                </div>
                <div>
                  forecast · lead {rainRes.data.lead_h} h
                  {modelledLead !== null && !leadIsModelled
                    ? ` (the ${modelledLead} h field, re-labelled)`
                    : ''}{' '}
                  · {IMD.find((c) => c.mm === threshold)?.label} ≥ {threshold} mm · {quantile} ·
                  issued {hhmm(t)} UTC
                </div>
                <Prov className="mt-0.5">
                  {forecastModel
                    ? `${forecastModel} · ${quantile} vs IMD category`
                    : 'model-derived · forecast source not declared by the API'}
                </Prov>
              </div>
            }
          />
        )}
      </Panel>

      {/* Two cards, not three, in a flex column with shrink-0 on each — see the
          long note on the same construction in Nowcast.jsx. A grid track would
          compress the stepper card, whose prose is the tallest thing in this
          rail, and spill it over the chart. */}
      <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
        <Panel title="Lead stepper (6 h blocks)" className="shrink-0">
          <div className="p-3">
            <div className="flex flex-wrap gap-1">
              {LEADS.map((h) => {
                const modelled = h === modelledLead
                return (
                  <button
                    key={h}
                    type="button"
                    onClick={() => setLead(h)}
                    title={
                      modelled
                        ? `The one separately modelled head. RainFuse fits ${h} h and the API returns its grid.`
                        : `Not separately modelled. Selecting +${h} h re-labels the ${modelledLead ?? 'single'} h field — the cell values do not change.`
                    }
                    className={clsx(
                      'flex items-center gap-1 rounded border px-2.5 py-1 text-[11.5px]',
                      leadH === h
                        ? modelled
                          ? 'border-teal/50 bg-teal/15 font-semibold text-teal'
                          : 'border-amber/50 bg-amber/15 font-semibold text-amber'
                        : 'border-grid text-muted hover:text-ink',
                    )}
                  >
                    +{h} h
                    {modelled && (
                      <span
                        className={clsx(
                          'h-1.5 w-1.5 rounded-full',
                          leadH === h ? 'bg-teal' : 'bg-teal/50',
                        )}
                      />
                    )}
                  </button>
                )
              })}
            </div>

            {/* THE HONEST NOTE. Five buttons that secretly show one field is
                the failure mode this replaces. */}
            {modelledLead !== null && (
              <p
                className={clsx(
                  'mt-2 rounded border px-2 py-1.5 text-[10.5px] leading-relaxed',
                  leadIsModelled
                    ? 'border-teal/30 bg-teal/[0.07] text-muted'
                    : 'border-amber/40 bg-amber/[0.07] text-amber/90',
                )}
              >
                {leadIsModelled ? (
                  <>
                    <span className="font-semibold text-teal">+{modelledLead} h is the modelled
                    head.</span>{' '}
                    RainFuse currently ships one forecast head and this is it; the dot marks it.
                  </>
                ) : (
                  <>
                    <span className="font-semibold">+{leadH} h is not separately modelled.</span>{' '}
                    RainFuse ships a single {modelledLead} h head, and /api/rain serves one grid per
                    issue time — the lead parameter only stamps <code>lead_h</code>. The cell values
                    above are the {modelledLead} h field re-labelled, not a distinct forecast.
                  </>
                )}
              </p>
            )}

            {forecastBlock && (
              <dl className="mt-3 space-y-1 text-[11.5px]">
                {Object.entries(forecastBlock.thresholds || {}).map(([mm, p]) => (
                  <div key={mm} className="flex justify-between">
                    <dt className="text-muted">
                      P({forecastBlock.lead_h ?? 24} h &gt; {mm} mm)
                    </dt>
                    <dd className="tabular text-ink">{pct(p)}</dd>
                  </div>
                ))}
              </dl>
            )}
            <p className="mt-2 text-[10.5px] leading-relaxed text-dim">
              The grid carries q10/q50/q90 per cell. The map shades the selected quantile against
              the selected IMD category — derived client-side, since no endpoint publishes a
              per-category exceedance raster. Quantile and category are real changes to the field on
              screen; the lead is not.
            </p>
            {/* All that survives of the old "RainFuse correction · provenance"
                card, which was three paragraphs of prose for one cross-
                reference. The claim it made is still true and still checkable —
                it is just one line now. */}
            <p className="mt-2 text-[10.5px] leading-relaxed text-dim">
              Raw NWP vs RainFuse side by side needs three grids per issue time and the contract
              publishes one; the comparison lives in Verification&apos;s ablation table, where the
              raw-NWP baseline row is the same claim in numbers.
            </p>
          </div>
        </Panel>

        <Panel
          title={`Quantile spread — wettest 12 cells by ${quantile}`}
          className="min-h-[240px] shrink-0 flex-1"
          bodyClass="min-h-0"
        >
          {fan.length ? (
            <div className="absolute inset-0 p-1 pb-3">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={fan} margin={{ top: 10, right: 12, bottom: 4, left: -18 }}>
                  <CartesianGrid stroke={ct.grid} vertical={false} />
                  <XAxis dataKey="cell" hide />
                  <YAxis
                    stroke={ct.axis}
                    tick={{ fontSize: 10, fill: ct.tick }}
                    tickFormatter={(v) => `${v}`}
                  />
                  <Tooltip
                    contentStyle={{ background: ct.tooltipBg, border: `1px solid ${ct.grid}`, borderRadius: 6, fontSize: 12 }}
                    labelStyle={{ color: ct.tick }}
                    formatter={(v, n) => [`${num(v, 1)} mm`, n === 'band' ? 'q10→q90 band' : n]}
                  />
                  <Bar isAnimationActive={false} dataKey="q10" stackId="a" fill="transparent" />
                  <Bar isAnimationActive={false} dataKey="band" stackId="a" radius={[3, 3, 0, 0]}>
                    {fan.map((f) => (
                      <Cell key={f.cell} fill={f.shown >= threshold ? '#ef4444' : '#14b8a6'} />
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
    </div>
  )
}
