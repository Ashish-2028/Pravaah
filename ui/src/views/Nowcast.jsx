import { useMemo, useState } from 'react'
import clsx from 'clsx'
import EventSelector, { ClockTag, useViewClock } from '../components/EventSelector'
import MapCanvas from '../components/MapCanvas'
import { Prov, modelName } from '../components/Provenance'
import SkillChart from '../components/SkillChart'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { useMetrics, useRain, useWards } from '../lib/hooks'
import { hhmm, num, pct, thresholdLabel, thresholdTitle } from '../lib/format'
import { useStore } from '../lib/store'

const LEADS = [0.5, 1, 2, 3, 4, 6]

// The legacy contract key -> the verification head that scores it. `p15`/`p50`
// are 5 mm and 10 mm (see lib/format.js), and /api/verify names those heads
// `p5` and `p10`, so flipping the threshold toggle above the map also moves the
// skill curve to the head that threshold is actually graded on.
const HEAD_FOR_THRESHOLD = { p15: 'p5', p50: 'p10' }

export default function Nowcast() {
  const lead = useStore((s) => s.lead)
  const setLead = useStore((s) => s.setLead)
  // LIVE by default; the selector above can freeze this on a past storm. Every
  // panel below reads this pair, so all of them follow the selection.
  const { event, t, isArchive, liveMissing } = useViewClock()
  const [threshold, setThreshold] = useState('p15')
  const rainRes = useRain(event, t, 'nowcast', Math.round(lead))
  const wardsRes = useWards(event, t)
  const metrics = useMetrics()

  // THE THRESHOLDS COME FROM THE API, NOT FROM THE FIELD NAME.
  // `p15`/`p50` are legacy contract keys; the fitted heads are 5 mm and 10 mm
  // and the response says so in provenance.head_thresholds_mm. See
  // lib/format.js for the full note on why this matters.
  const prov = rainRes.data?.provenance || null
  const label = (key) => thresholdLabel(prov, key)
  const nowcastModel = modelName(prov?.nowcast_source, 'RainCast-v0')

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

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-2">
      <EventSelector note="Every panel on this screen — rain field, lead stepper, field summary and the skill curve's context — follows this selection." />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_330px] gap-2 overflow-hidden">
        <Panel
          title="Rain probability field — 0 to 6 h"
          right={
            <div className="flex items-center gap-2">
              <div className="flex overflow-hidden rounded border border-grid">
                {['p15', 'p50'].map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setThreshold(k)}
                    title={thresholdTitle(prov, k)}
                    className={clsx(
                      'px-2.5 py-1 text-[11px]',
                      threshold === k
                        ? 'bg-teal/20 font-semibold text-teal'
                        : 'text-muted hover:text-ink',
                    )}
                  >
                    {label(k)}
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
              pointLabel={label(threshold)}
              overlay={
                <div
                  className={clsx(
                    'pointer-events-none absolute left-3 top-3 z-10 max-w-[calc(100%-200px)] rounded-md border bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted',
                    isArchive ? 'border-amber/50' : 'border-grid',
                  )}
                >
                  <div className="mb-0.5">
                    <ClockTag isArchive={isArchive} event={event} t={t} liveMissing={liveMissing} />
                  </div>
                  <div>
                    {rainRes.data.kind} · lead {rainRes.data.lead_h} h · issued {hhmm(t)} UTC ·{' '}
                    {rainRes.data.cells?.length || 0} cells
                  </div>
                  <Prov className="mt-0.5">
                    {nowcastModel} · {label(threshold)}
                  </Prov>
                </div>
              }
            />
          )}
        </Panel>

        {/* FLEX COLUMN, NOT A GRID, AND EVERY CARD IS shrink-0.
            This is the actual fix for "panels are squished and text overflows".
            The rail used to be a `grid-rows-[auto auto 1fr]`, and a CSS grid
            with a definite height will COMPRESS its auto tracks when the
            content does not fit — Panel's own `min-h-0` removes the automatic
            minimum that would otherwise stop it. Measured at 1280 × 700: the
            summary card was handed 126 px for 227 px of content, so its text
            spilled straight over the card below.
            A flex column with `shrink-0` on each card cannot do that. Cards
            keep their content height, the rail scrolls when the sum does not
            fit, and the chart takes whatever is left down to a 280 px floor. */}
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
          <Panel title="Lead stepper" className="shrink-0">
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

          <Panel title="Field summary" className="shrink-0">
            {stats ? (
              <dl className="grid grid-cols-2 gap-x-3 gap-y-2 p-3 text-[11.5px]">
                {[
                  [`Max ${label(threshold)}`, pct(stats.max)],
                  ['Mean probability', pct(stats.mean)],
                  ['Cells ≥ 50%', `${stats.hot} / ${stats.cells}`],
                  ['Peak q50', `${num(stats.q50, 1)} mm`],
                  ['Peak q90', `${num(stats.q90, 1)} mm`],
                ].map(([k, v]) => (
                  <div key={k} className="min-w-0">
                    <dt className="truncate text-[9.5px] uppercase tracking-wider text-muted">
                      {k}
                    </dt>
                    <dd className="tabular truncate text-base font-semibold text-ink">{v}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <div className="p-3 text-xs text-muted">No grid loaded.</div>
            )}
            {stats && (
              <div className="border-t border-grid px-3 pb-2 pt-1.5">
                <Prov title={thresholdTitle(prov, threshold)}>
                  {nowcastModel} · exceedance head &quot;{threshold}&quot;
                </Prov>
              </div>
            )}
          </Panel>

          {/* Deliberately does NOT follow the event selector: these are the
              held-out test-year metrics from /api/verify, and re-scoping them to
              a demo day — three of which are training days — would be the
              dishonest version of this chart. */}
          <Panel
            title="Skill vs lead — the honest decay"
            className="min-h-[280px] shrink-0 flex-1"
            right={
              <span
                className="shrink-0 text-[9.5px] uppercase tracking-wider text-dim"
                title="Computed once over the held-out test year. It does not change with the event selector."
              >
                test year
              </span>
            }
            bodyClass="min-h-0"
          >
            {metrics.error && !metrics.data ? (
              <ErrorBox error={metrics.error} onRetry={metrics.reload} compact />
            ) : metrics.data ? (
              <SkillChart
                rows={metrics.data.skill_vs_lead}
                preferHead={HEAD_FOR_THRESHOLD[threshold]}
                compact
              />
            ) : (
              <Spinner label="Loading skill curve" />
            )}
          </Panel>
        </div>
      </div>
    </div>
  )
}
