import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import { AlertTriangle, Crosshair, FlaskConical, Globe2 } from 'lucide-react'
import MapCanvas from '../components/MapCanvas'
import ResponseCurve, { peakStepNote } from '../components/ResponseCurve'
import { Prov } from '../components/Provenance'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { api } from '../lib/api'
import { useResource, useWards } from '../lib/hooks'
import { BAND_COLOR, BAND_ORDER, compact, featureLabel, num, pct } from '../lib/format'
import { useStore } from '../lib/store'

/**
 * SANDBOX — invent a storm, watch the real model answer it.
 *
 * The pitch is one sentence: the rainfall is synthetic, EVERYTHING ELSE IS NOT.
 * /api/sandbox runs the shipped InundaNet booster over all 148,776 real 100 m
 * terrain cells on every request, so what comes back is the actual model's
 * actual answer to a storm the judge made up — not a lookup, not an animation.
 *
 * Which makes the honesty requirements load-bearing rather than decorative:
 *
 *   1. NOTHING ON THIS SCREEN IS A FORECAST. The word never appears against
 *      sandbox output. The amber banner is persistent, and the same words are
 *      burned into the map overlay so a screenshot of the canvas alone still
 *      carries the caveat.
 *   2. THE UNITS ARE NOT IMD's. These are 6 h ERA5 accumulations. IMD's
 *      64.5 / 115.6 / 204.5 mm categories are 24 h GAUGE totals and labelling a
 *      slider with them would be a category error in front of an audience that
 *      knows the difference. The API's own caveat string is printed verbatim.
 *   3. THE EVIDENCE BOUNDARY IS THE POINT. The booster's highest split on
 *      rain_sum is 25.3 mm, so above it the model is mathematically constant —
 *      40 mm and 300 mm return byte-identical probabilities. Every slider marks
 *      its own limit, the curve shades the region beyond it, and there is a
 *      button that proves the flatness with two live requests rather than
 *      asking anyone to take it on faith.
 *
 * Layout follows the house rule the hard way learned elsewhere in this app:
 * both rails are FLEX COLUMNS with `shrink-0` on every card. A CSS grid with a
 * definite height compresses its auto tracks and spills text over the card
 * below — see the long note in Nowcast.jsx.
 */

// Slider travel. Deliberately WIDER than the evidence limits: the flatness has
// to be demonstrable by dragging, not merely asserted, so the controls are
// allowed into the region where the model has nothing to say — clearly marked
// as a different regime, which is the whole demo.
const SLIDERS = [
  {
    key: 'rain_sum',
    label: 'Event rainfall',
    max: 60,
    step: 0.5,
    help: 'Total accumulation over the 6-hour window, on the ERA5 scale.',
  },
  {
    key: 'rain_max',
    label: 'Peak hour',
    max: 40,
    step: 0.25,
    help: 'The wettest single hour inside that window. Linked to the total — see the note below.',
  },
  {
    key: 'rain_prev3d',
    label: 'Previous 3 days',
    max: 80,
    step: 0.5,
    help: 'How wet the ground already was going in.',
  },
  {
    key: 'rain_prev7d',
    label: 'Previous 7 days',
    max: 140,
    step: 0.5,
    help: 'Longer-run antecedent wetness.',
  },
]

const DEFAULTS = { rain_sum: 20, rain_max: 7, rain_prev3d: 25, rain_prev7d: 45 }

const round2 = (v) => Math.round(v * 100) / 100

/**
 * Keep the storm physically possible.
 *
 *     rain_sum / 6  ≤  rain_max  ≤  rain_sum
 *
 * The upper bound is arithmetic: one hour of a six-hour total cannot exceed the
 * total. The lower bound is the perfectly-even case — six identical hours — so
 * a 120 mm six-hour total cannot have a 9 mm peak hour, and a judge who builds
 * that storm is feeding the model a combination that appears nowhere in nature
 * or in its training set. Whichever slider the operator moved is authoritative
 * and the other one yields, so the control they are dragging never fights back.
 */
function constrain(next, moved) {
  const r = { ...next }
  if (moved === 'rain_sum') {
    r.rain_max = Math.min(r.rain_sum, Math.max(r.rain_sum / 6, r.rain_max))
  } else if (moved === 'rain_max') {
    r.rain_sum = Math.min(6 * r.rain_max, Math.max(r.rain_max, r.rain_sum))
  }
  r.rain_sum = round2(r.rain_sum)
  r.rain_max = round2(r.rain_max)
  return r
}

// ----------------------------------------------------------------- controls

function RainSlider({ spec, value, limit, saturated, onChange }) {
  // The travel expands to hold an out-of-range value rather than silently
  // truncating it: the "Beyond evidence" preset sets rain_sum to 120 mm, and a
  // slider that pegged at 60 while the request carried 120 would be lying about
  // what was run. Because the expansion tracks the value exactly, dragging back
  // down is continuous — the thumb never jumps.
  const axisMax = Math.max(spec.max, value)
  const limitPct = Math.max(0, Math.min(100, (limit / axisMax) * 100))
  // Local comparison for the colour so the regime flips on the same frame as
  // the drag; the API's own `saturated` flag drives the sentence, so the claim
  // in words is always the server's, never ours.
  const beyond = value > limit

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={`sb-${spec.key}`} className="min-w-0 truncate text-[11.5px] text-ink" title={spec.help}>
          {spec.label}
        </label>
        <span
          className={clsx(
            'tabular shrink-0 text-[13px] font-semibold',
            beyond ? 'text-amber' : 'text-ink',
          )}
        >
          {num(value, 1)} mm
        </span>
      </div>

      <input
        id={`sb-${spec.key}`}
        type="range"
        min={0}
        max={axisMax}
        step={spec.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={clsx('mt-1 w-full cursor-pointer', beyond ? 'accent-amber' : 'accent-teal')}
      />

      {/* The evidence rail: this feature's own last split, and the hatched
          region past it where the booster stops responding. */}
      <div
        className="relative mt-0.5 h-1.5 overflow-hidden rounded bg-grid"
        title={`The trained booster's highest split on ${spec.key} is ${limit} mm. Above that the tree is constant, so this slider stops changing the answer.`}
      >
        <div className="absolute inset-y-0 right-0 bg-amber/20" style={{ width: `${100 - limitPct}%` }}>
          <div
            className="h-full w-full text-amber/45"
            style={{
              backgroundImage:
                'repeating-linear-gradient(45deg, currentColor 0 2px, transparent 2px 5px)',
            }}
          />
        </div>
        <div className="absolute inset-y-0 w-[1.5px] bg-amber" style={{ left: `${limitPct}%` }} />
      </div>
      <div className="tabular mt-0.5 flex items-baseline justify-between gap-1 text-[9px] text-dim">
        <span>0</span>
        <span className="truncate text-amber">evidence ends {num(limit, 2)} mm</span>
        <span>{num(axisMax, 0)}</span>
      </div>

      {saturated && (
        <p className="mt-1 rounded border border-amber/40 bg-amber/10 px-1.5 py-1 text-[10px] leading-snug text-amber">
          Past this the model has no evidence and its answer stops changing.
        </p>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ results

function Bands({ bands }) {
  return (
    <div className="grid grid-cols-4 gap-1.5 px-3 pt-3">
      {BAND_ORDER.map((b) => (
        <div
          key={b}
          className="min-w-0 rounded border px-1.5 py-1.5"
          style={{ borderColor: `${BAND_COLOR[b]}55`, background: `${BAND_COLOR[b]}14` }}
        >
          <div className="tabular text-lg font-semibold leading-none" style={{ color: BAND_COLOR[b] }}>
            {bands?.[b] || 0}
          </div>
          <div className="truncate text-[9px] uppercase tracking-wider text-muted">{b}</div>
        </div>
      ))}
    </div>
  )
}

const COLUMNS = [
  ['name', 'Ward', 'left'],
  ['p_flood', 'P(flood)', 'right'],
  ['rain_here_mm', 'Rain', 'right'],
  ['people', 'People', 'right'],
]

function WardTable({ rows }) {
  const [sort, setSort] = useState({ key: 'p_flood', dir: -1 })

  const sorted = useMemo(() => {
    const out = [...rows]
    out.sort((a, b) => {
      const x = a[sort.key]
      const y = b[sort.key]
      const c = typeof x === 'string' ? String(x).localeCompare(String(y)) : (x || 0) - (y || 0)
      return c * sort.dir
    })
    return out.slice(0, 15)
  }, [rows, sort])

  const flip = (key) =>
    setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === 'name' ? 1 : -1 }))

  return (
    <div className="overflow-x-auto px-1.5 pb-2">
      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr>
            {COLUMNS.map(([key, label, align]) => (
              <th
                key={key}
                className={clsx(
                  'sticky top-0 bg-panel px-1.5 py-1.5 font-semibold uppercase tracking-wider',
                  align === 'right' ? 'text-right' : 'text-left',
                )}
              >
                <button
                  type="button"
                  onClick={() => flip(key)}
                  className={clsx(
                    'text-[9px] uppercase tracking-wider hover:text-ink',
                    sort.key === key ? 'text-teal' : 'text-muted',
                  )}
                >
                  {label}
                  {sort.key === key ? (sort.dir < 0 ? ' ↓' : ' ↑') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((w) => (
            <tr key={w.ward_id} className="border-t border-grid/70">
              <td className="max-w-[124px] truncate px-1.5 py-1 text-ink" title={w.name}>
                <span
                  className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle"
                  style={{ background: BAND_COLOR[w.risk_band] }}
                />
                {w.name}
              </td>
              <td
                className="tabular px-1.5 py-1 text-right font-semibold"
                style={{ color: BAND_COLOR[w.risk_band] }}
              >
                {pct(w.p_flood)}
              </td>
              <td className="tabular px-1.5 py-1 text-right text-muted">{num(w.rain_here_mm, 1)}</td>
              <td className="tabular px-1.5 py-1 text-right text-muted">{compact(w.people)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * The saturation proof.
 *
 * Two live scoring passes, 40 mm and 300 mm of event rainfall, compared field
 * by field. This exists because "the model is flat up here" is a claim, and a
 * claim a judge can check in one click at the podium is worth more than the
 * same claim in a footnote. It compares the FULL 289-ward probability vector,
 * not just the headline, so a partial match cannot quietly pass.
 *
 * THE PEAK HOURS DIFFER, AND THEY HAVE TO. `total / 6 ≤ peak ≤ total` makes it
 * impossible to hold the peak hour fixed while moving the total from 40 mm to
 * 300 mm — the 300 mm storm's peak hour cannot be below 50 mm. Rather than send
 * a physically impossible pair the UI otherwise refuses to build, both storms
 * are put past EVERY evidence limit (rain_max's is 29.75 mm), where the two
 * rain features are jointly saturated and the model genuinely cannot tell the
 * storms apart. Verified against the running service: 289 / 289 identical.
 */
const PROOF_A = { rain_sum: 40, rain_max: 30 }
const PROOF_B = { rain_sum: 300, rain_max: 50 }

function SaturationProof({ rain }) {
  const [state, setState] = useState({ status: 'idle', result: null, error: null })

  const run = useCallback(async () => {
    setState({ status: 'running', result: null, error: null })
    const base = { rain_prev3d: rain.rain_prev3d, rain_prev7d: rain.rain_prev7d }
    try {
      const [a, b] = await Promise.all([
        api.sandbox({ ...base, ...PROOF_A }),
        api.sandbox({ ...base, ...PROOF_B }),
      ])
      const pa = a.wards.map((w) => w.p_flood)
      const pb = b.wards.map((w) => w.p_flood)
      const same = pa.length === pb.length && pa.every((v, i) => v === pb[i])
      setState({
        status: 'done',
        error: null,
        result: {
          same,
          n: pa.length,
          identical: pa.filter((v, i) => v === pb[i]).length,
          maxA: a.summary.max_p_flood,
          maxB: b.summary.max_p_flood,
          peopleA: a.summary.people_exposed,
          peopleB: b.summary.people_exposed,
        },
      })
    } catch (err) {
      setState({ status: 'idle', result: null, error: err.message || String(err) })
    }
  }, [rain.rain_prev3d, rain.rain_prev7d])

  const r = state.result
  return (
    <div className="p-3">
      <button
        type="button"
        onClick={run}
        disabled={state.status === 'running'}
        className="w-full rounded-md border border-amber/50 bg-amber/15 py-1.5 text-[12px] font-semibold text-amber hover:bg-amber/25 disabled:opacity-60"
      >
        {state.status === 'running' ? 'Scoring both…' : 'Run 40 mm and 300 mm side by side'}
      </button>
      <p className="mt-2 text-[10px] leading-relaxed text-dim">
        Two live passes over all 148,776 cells — {PROOF_A.rain_sum} mm with a {PROOF_A.rain_max} mm
        peak hour, and {PROOF_B.rain_sum} mm with a {PROOF_B.rain_max} mm one. Both sit past every
        evidence limit, so the model should be unable to tell them apart.
      </p>
      {state.error && <ErrorBox error={state.error} onRetry={run} compact />}
      {r && (
        <div
          className={clsx(
            'mt-2 rounded-md border px-2 py-1.5 text-[10.5px] leading-relaxed',
            r.same ? 'border-amber/45 bg-amber/10 text-amber' : 'border-danger/45 bg-danger/10 text-danger',
          )}
        >
          <div className="font-semibold">
            {r.same
              ? `Identical. All ${r.identical} of ${r.n} ward probabilities match exactly.`
              : `Not identical — ${r.identical} of ${r.n} ward probabilities match.`}
          </div>
          <div className="tabular mt-1 text-muted">
            max P(flood) {pct(r.maxA, 1)} vs {pct(r.maxB, 1)} · people {compact(r.peopleA)} vs{' '}
            {compact(r.peopleB)}
          </div>
        </div>
      )}
    </div>
  )
}

// -------------------------------------------------------------------- view

export default function Sandbox() {
  // Ward GEOMETRY only. The sandbox response carries a value per ward but no
  // polygons, and /api/wards is the one place those polygons live — so this
  // fetch supplies shape and the sandbox supplies every number painted on it.
  // The live clock is used purely to name a file; nothing on this screen is
  // scoped to an hour, because a hypothetical does not have one.
  const event = useStore((s) => s.event)
  const t = useStore((s) => s.t)
  const wardsRes = useWards(event, t)

  const [rain, setRain] = useState(DEFAULTS)
  const [centre, setCentre] = useState(null) // [lat, lon] | null = uniform
  const [radiusKm, setRadiusKm] = useState(12)
  const [clamped, setClamped] = useState(null)
  const clampTimer = useRef(null)

  // Debounced mirror of every control. Warm inference is ~0.10 s, so 250 ms is
  // the difference between "live" and "a request per pixel of slider travel".
  const [applied, setApplied] = useState({ ...DEFAULTS, centre: null, radiusKm: 12 })
  useEffect(() => {
    const id = setTimeout(() => setApplied({ ...rain, centre, radiusKm }), 250)
    return () => clearTimeout(id)
  }, [rain, centre, radiusKm])

  useEffect(() => () => clearTimeout(clampTimer.current), [])

  const key = JSON.stringify(applied)
  const res = useResource(
    () =>
      api.sandbox({
        rain_sum: applied.rain_sum,
        rain_max: applied.rain_max,
        rain_prev3d: applied.rain_prev3d,
        rain_prev7d: applied.rain_prev7d,
        centre: applied.centre,
        radius_km: applied.radiusKm,
      }),
    [key],
  )

  // The curve holds the antecedent features fixed and sweeps the event total,
  // so it only has to be refetched when the two antecedent sliders move.
  const curveRes = useResource(
    () => api.sandboxCurve(applied.rain_prev3d, applied.rain_prev7d),
    [applied.rain_prev3d, applied.rain_prev7d],
  )

  const data = res.data
  const evidence = data?.evidence || null
  const limits = evidence?.limits_mm || {}
  const saturated = evidence?.saturated || {}

  const setField = useCallback((k, v) => {
    setRain((prev) => {
      const next = constrain({ ...prev, [k]: v }, k)
      // Only announce a clamp that actually moved the *other* control.
      const partner = k === 'rain_sum' ? 'rain_max' : k === 'rain_max' ? 'rain_sum' : null
      if (partner && next[partner] !== prev[partner]) {
        clearTimeout(clampTimer.current)
        setClamped(partner)
        clampTimer.current = setTimeout(() => setClamped(null), 2600)
      }
      return next
    })
  }, [])

  const applyPreset = useCallback((p) => {
    setRain({
      rain_sum: p.rain_sum,
      rain_max: p.rain_max,
      rain_prev3d: p.rain_prev3d,
      rain_prev7d: p.rain_prev7d,
    })
  }, [])

  const onMapClick = useCallback((lngLat) => {
    setCentre([round2(lngLat.lat), round2(lngLat.lng)])
  }, [])

  // Sandbox values grafted onto the real polygons. Wards the sandbox did not
  // score (it returns 289 of the catalogue's 290) are DROPPED rather than left
  // painted with a stale live probability — a leftover polygon carrying last
  // hour's real number would be the one genuinely dishonest pixel on this page.
  const sandboxWards = useMemo(() => {
    const base = wardsRes.data
    const rows = data?.wards
    if (!base || !rows) return null
    const by = new Map(rows.map((w) => [w.ward_id, w]))
    return {
      type: 'FeatureCollection',
      features: base.features
        .filter((f) => by.has(f.properties.ward_id))
        .map((f) => {
          const w = by.get(f.properties.ward_id)
          return {
            ...f,
            properties: {
              ward_id: w.ward_id,
              name: w.name,
              p_flood: w.p_flood,
              risk_score: w.risk_score,
              risk_band: w.risk_band,
              rain_here_mm: w.rain_here_mm,
              people: w.people,
              hospitals: w.hospitals,
              schools: w.schools,
              onset: null, // a hypothetical has no clock, so it has no onset
            },
          }
        }),
    }
  }, [wardsRes.data, data])

  const storm = useMemo(
    () => (applied.centre ? { lat: applied.centre[0], lon: applied.centre[1], radiusKm: applied.radiusKm } : null),
    [applied.centre, applied.radiusKm],
  )

  const summary = data?.summary || null
  const top = summary?.top_ward || null
  const driverPeak = top ? Math.max(...top.drivers.map((d) => Math.abs(d.contribution)), 0.01) : 1

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden p-2">
      {/* ------------------------------------------------- the standing caveat */}
      <div className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-amber/50 bg-amber/10 px-3 py-2 text-amber">
        <AlertTriangle size={15} className="shrink-0" />
        <span className="text-[12px] font-bold uppercase tracking-[0.1em]">
          {data?.label || 'HYPOTHETICAL — user-chosen rainfall, not a forecast'}
        </span>
        <span className="min-w-0 flex-1 text-[10.5px] leading-snug text-muted">
          {data?.model?.note ||
            'Live inference by the shipped model on real 100 m terrain. Only the rainfall is user-chosen.'}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[292px_1fr_336px] gap-2 overflow-hidden">
        {/* ------------------------------------------------------- controls */}
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
          <Panel title="Storms to try" className="shrink-0">
            <div className="flex flex-col gap-1 p-2">
              {(data?.presets || []).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyPreset(p)}
                  className="rounded border border-grid px-2 py-1.5 text-left transition-colors hover:border-teal/50 hover:bg-panel2"
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[12px] font-semibold text-ink">{p.label}</span>
                    <span className="tabular shrink-0 text-[10px] text-dim">{p.rain_sum} mm</span>
                  </span>
                  <span className="mt-0.5 block text-[10px] leading-snug text-muted">{p.note}</span>
                </button>
              ))}
              {!data && <div className="p-1 text-[11px] text-muted">Loading presets…</div>}
            </div>
          </Panel>

          <Panel
            title="Rainfall"
            className="shrink-0"
            right={<span className="shrink-0 text-[9.5px] uppercase tracking-wider text-dim">6 h · ERA5</span>}
          >
            <div className="space-y-3 p-3">
              {SLIDERS.map((spec) => (
                <RainSlider
                  key={spec.key}
                  spec={spec}
                  value={rain[spec.key]}
                  limit={limits[spec.key] ?? spec.max}
                  saturated={Boolean(saturated[spec.key])}
                  onChange={(v) => setField(spec.key, v)}
                />
              ))}

              <div
                className="rounded border border-grid bg-bg/40 px-2 py-1.5 text-[10px] leading-relaxed text-dim"
                title="One hour of a six-hour total cannot exceed the total, and cannot be smaller than a sixth of it — that would be perfectly even rain. A 6 h total of 120 mm cannot have a 9 mm peak hour, so the two sliders move each other rather than letting an impossible storm be built."
              >
                <span className="tabular text-muted">total ÷ 6 ≤ peak hour ≤ total</span> — the two
                are linked so an impossible storm cannot be built.
                {clamped && (
                  <span className="mt-1 block font-semibold text-amber">
                    {clamped === 'rain_max' ? 'Peak hour' : 'Event rainfall'} was adjusted to keep
                    the storm physical.
                  </span>
                )}
              </div>

              {/* Verbatim from the API. The moment this is paraphrased, the UI
                  owns a claim about units that the backend is the authority on. */}
              <p className="text-[10px] leading-relaxed text-dim">{data?.units?.caveat}</p>
            </div>
          </Panel>

          <Panel title="Where the rain falls" className="shrink-0">
            <div className="p-3">
              <div className="flex overflow-hidden rounded border border-grid">
                <button
                  type="button"
                  onClick={() => setCentre(null)}
                  className={clsx(
                    'flex flex-1 items-center justify-center gap-1.5 px-2 py-1.5 text-[11px]',
                    centre ? 'text-muted hover:text-ink' : 'bg-teal/20 font-semibold text-teal',
                  )}
                >
                  <Globe2 size={12} /> Uniform
                </button>
                <button
                  type="button"
                  disabled
                  className={clsx(
                    'flex flex-1 items-center justify-center gap-1.5 px-2 py-1.5 text-[11px]',
                    centre ? 'bg-amber/20 font-semibold text-amber' : 'text-dim',
                  )}
                >
                  <Crosshair size={12} /> Placed
                </button>
              </div>

              <p className="mt-2 text-[10.5px] leading-relaxed text-muted">
                {centre ? (
                  <>
                    Storm centred at{' '}
                    <span className="tabular text-ink">
                      {num(centre[0], 2)}°N {num(centre[1], 2)}°E
                    </span>
                    . Click elsewhere on the map to move it.
                  </>
                ) : (
                  'Rain is uniform across the city. Click anywhere on the map to drop a storm centre and put the burst over a ward you know.'
                )}
              </p>

              <div className="mt-3">
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor="sb-radius" className="text-[11.5px] text-ink">
                    Storm radius
                  </label>
                  <span className="tabular text-[13px] font-semibold text-ink">{radiusKm} km</span>
                </div>
                <input
                  id="sb-radius"
                  type="range"
                  min={3}
                  max={40}
                  step={1}
                  value={radiusKm}
                  disabled={!centre}
                  onChange={(e) => setRadiusKm(Number(e.target.value))}
                  className="mt-1 w-full cursor-pointer accent-amber disabled:cursor-not-allowed disabled:opacity-40"
                />
                <p className="mt-1 text-[10px] leading-relaxed text-dim">
                  A Gaussian kernel, not a hard edge: the radius is roughly two standard deviations,
                  so rain tails off outside the ring rather than stopping at it.
                </p>
              </div>
            </div>
          </Panel>

          <Panel title="Prove the flat line" className="shrink-0">
            <SaturationProof rain={rain} />
          </Panel>
        </div>

        {/* ------------------------------------------------- map + the curve */}
        <div className="flex min-w-0 flex-col gap-2">
          <Panel
            title="InundaNet on invented rainfall"
            className="min-h-[200px] flex-1"
            right={
              <span className="tabular shrink-0 text-[9.5px] uppercase tracking-wider text-dim">
                {data ? `${num(data.model.cells_scored)} cells scored` : '…'}
              </span>
            }
            bodyClass="relative"
          >
            {wardsRes.error && !wardsRes.data ? (
              <ErrorBox error={wardsRes.error} onRetry={wardsRes.reload} />
            ) : res.error && !data ? (
              <ErrorBox error={res.error} onRetry={res.reload} />
            ) : !sandboxWards ? (
              <Spinner label="Scoring 148,776 terrain cells" />
            ) : (
              <MapCanvas
                wards={sandboxWards}
                layer="p_flood"
                storm={storm}
                onMapClick={onMapClick}
                legendLabel="Hypothetical P(flood)"
                overlay={
                  /* THE CAVEAT LIVES ON THE CANVAS, NOT ONLY IN THE PAGE.
                     A screenshot of this map will be pasted into a deck by
                     somebody who did not read the banner above it, so the map
                     carries the same words on its own. */
                  <div className="pointer-events-none absolute left-3 top-3 z-10 max-w-[calc(100%-190px)] rounded-md border border-amber/60 bg-panel/92 px-2.5 py-1.5">
                    <div className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-amber">
                      Hypothetical — not a forecast
                    </div>
                    <div className="mt-0.5 text-[10.5px] text-muted">
                      {num(rain.rain_sum, 1)} mm / 6 h, peak {num(rain.rain_max, 1)} mm ·{' '}
                      {centre ? `${radiusKm} km storm` : 'uniform city-wide'}
                    </div>
                    {/* Prov truncates by design, so the line has to FIT the
                        overlay at 1280 px — a provenance label clipped to
                        "live inference on real terr…" says nothing. The full
                        sentence lives in the title. */}
                    <Prov className="mt-0.5" title={data?.model?.note}>
                      {data ? `${data.model.name} · live inference` : 'InundaNet v0'}
                    </Prov>
                  </div>
                }
              />
            )}
          </Panel>

          <Panel
            title="Response curve — and where the evidence stops"
            /* A FIXED height, not flex-1. The plot is the only thing in this
               column that must not be squeezed, and the map above it will
               happily take whatever is left — see the collapsed-chart note in
               ResponseCurve.jsx for what a few pixels short looks like. */
            className="h-[264px] shrink-0"
            right={
              <span className="shrink-0 text-[9.5px] uppercase tracking-wider text-dim">
                antecedents held fixed
              </span>
            }
            bodyClass="min-h-0"
          >
            {curveRes.error && !curveRes.data ? (
              <ErrorBox error={curveRes.error} onRetry={curveRes.reload} compact />
            ) : curveRes.data ? (
              <ResponseCurve
                curve={curveRes.data}
                rainMaxLimitMm={limits.rain_max}
                atRainMm={rain.rain_sum}
                compactAxis
              />
            ) : (
              <Spinner label="Sweeping rainfall" />
            )}
          </Panel>
        </div>

        {/* -------------------------------------------------------- results */}
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
          <Panel
            title="What the model says"
            className="shrink-0"
            right={
              res.loading ? (
                <span className="shrink-0 text-[9.5px] uppercase tracking-wider text-dim">
                  scoring…
                </span>
              ) : null
            }
          >
            {summary ? (
              <>
                <Bands bands={summary.bands} />
                <dl className="grid grid-cols-2 gap-x-3 gap-y-2 p-3 text-[11.5px]">
                  {[
                    ['People exposed', compact(summary.people_exposed), 'In wards at high or critical band under this hypothetical rainfall.'],
                    ['Max P(flood)', pct(summary.max_p_flood, 1), 'The single wettest ward, at the 90th-percentile cell rule.'],
                  ].map(([k, v, title]) => (
                    <div key={k} className="min-w-0">
                      <dt className="truncate text-[9.5px] uppercase tracking-wider text-muted" title={title}>
                        {k}
                      </dt>
                      <dd className="tabular truncate text-lg font-semibold text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
                <div className="border-t border-grid px-3 pb-2 pt-1.5">
                  <Prov title={`${data.model.artefact} — ${data.model.note}`}>
                    {data.model.name} · hypothetical input
                  </Prov>
                </div>
              </>
            ) : (
              <Spinner label="Running the model" />
            )}
          </Panel>

          {top && (
            <Panel title="Wettest ward and why" className="shrink-0">
              <div className="p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-ink">{top.name}</div>
                    <div className="text-[10px] uppercase tracking-wider text-dim">
                      ward {top.ward_id}
                    </div>
                  </div>
                  <div className="tabular shrink-0 text-lg font-semibold text-amber">
                    {pct(top.p_flood, 1)}
                  </div>
                </div>
                <div className="mt-3 space-y-2">
                  {top.drivers.map((d) => (
                    <div key={d.feature}>
                      <div className="flex items-baseline justify-between gap-2 text-[11.5px]">
                        <span className="min-w-0 truncate text-ink" title={d.feature}>
                          {featureLabel(d.feature)}
                        </span>
                        <span className="tabular shrink-0 text-muted">{num(d.contribution, 2)}</span>
                      </div>
                      <div className="mt-1 h-1.5 w-full overflow-hidden rounded bg-grid">
                        <div
                          className="h-full rounded bg-teal"
                          style={{
                            width: `${Math.max(3, (Math.abs(d.contribution) / driverPeak) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
                <p className="mt-2 text-[10px] leading-relaxed text-dim">
                  SHAP contributions for this ward under this hypothetical rainfall. Terrain drivers
                  are fixed properties of the ground; only the rain ones move with the sliders.
                </p>
              </div>
            </Panel>
          )}

          <Panel
            title="Top wards"
            className="shrink-0"
            right={<span className="shrink-0 text-[9.5px] uppercase tracking-wider text-dim">sortable</span>}
          >
            {data ? (
              <WardTable rows={data.wards} />
            ) : (
              <div className="p-3 text-[11px] text-muted">No result yet.</div>
            )}
          </Panel>

          <Panel title="Why the sliders stop working" className="shrink-0">
            <div className="space-y-2 p-3 text-[10.5px] leading-relaxed">
              <div className="flex items-start gap-1.5 text-amber">
                <FlaskConical size={13} className="mt-px shrink-0" />
                <span>
                  A gradient-boosted tree is constant above its highest split on a feature. This is a
                  limit of our flood-label set, not a claim that heavier rain is harmless.
                </span>
              </div>
              {evidence && (
                <>
                  <p className="text-muted">{evidence.note}</p>
                  {/* THE LIMITS ARE PER-FEATURE, AND THE FIRST TWO ARE LINKED.
                      Dragging the total past 25.3 mm does not freeze the whole
                      answer, because the physical constraint drags the peak
                      hour up with it and the peak hour still has evidence left.
                      Saying only "the answer stops changing" would leave a
                      judge who watched the number keep moving thinking the
                      screen had lied to them. */}
                  <p className="text-dim">
                    Each limit is that feature&apos;s own. The whole answer only stops moving once
                    every rain feature is past its limit — pushing the total up drags the peak hour
                    with it, and the peak hour still matters until {num(limits.rain_max, 2)} mm. The
                    antecedent sliders are unlinked, so either of those freezes the result on its
                    own.
                  </p>
                  {/* Lives here rather than under the plot because it does not
                      fit there — this rail scrolls, the chart panel does not. */}
                  {peakStepNote(limits.rain_max) && (
                    <p className="text-dim">{peakStepNote(limits.rain_max)}</p>
                  )}
                  <dl className="tabular grid grid-cols-2 gap-x-3 gap-y-1 text-[10.5px]">
                    {SLIDERS.map((s) => (
                      <div key={s.key} className="flex items-baseline justify-between gap-2">
                        <dt className="min-w-0 truncate text-dim" title={s.key}>
                          {s.label}
                        </dt>
                        <dd
                          className={clsx(
                            'shrink-0 font-semibold',
                            saturated[s.key] ? 'text-amber' : 'text-muted',
                          )}
                        >
                          {num(limits[s.key], 2)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  )
}
