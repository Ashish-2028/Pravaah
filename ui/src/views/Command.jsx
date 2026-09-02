import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { AlertTriangle, ShieldAlert } from 'lucide-react'
import KpiStrip from '../components/KpiStrip'
import MapCanvas from '../components/MapCanvas'
import RadarPanel from '../components/RadarPanel'
import RankedList from '../components/RankedList'
import AdvisoryDrawer from '../components/AdvisoryDrawer'
import CapModal from '../components/CapModal'
import { LiveBadge, RefreshButton, RefreshError } from '../components/LiveBadge'
import { useLive } from '../lib/live'
import { Prov, modelName } from '../components/Provenance'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { findWard, rankWards, useCityState, useRain, useWards } from '../lib/hooks'
import { BAND_COLOR, compact, hhmm, pct, topDriver } from '../lib/format'
import { selectLiveMissing, useStore } from '../lib/store'

const LAYERS = [
  ['p_flood', 'Inundation prob.'],
  ['risk_score', 'Risk score'],
  ['exposure', 'Exposure'],
]

export function LayerSwitch({ layer, setLayer }) {
  return (
    <div className="flex overflow-hidden rounded border border-grid">
      {LAYERS.map(([key, label]) => (
        <button
          key={key}
          type="button"
          onClick={() => setLayer(key)}
          className={clsx(
            'px-2.5 py-1 text-[11px] transition-colors',
            layer === key ? 'bg-teal/20 font-semibold text-teal' : 'text-muted hover:text-ink',
          )}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

export function BandSummary({ rows }) {
  const counts = rows.reduce((acc, w) => {
    acc[w.risk_band] = (acc[w.risk_band] || 0) + 1
    return acc
  }, {})
  return (
    <div className="flex items-center gap-2">
      {['critical', 'high', 'watch', 'low'].map((b) => (
        <span key={b} className="flex items-center gap-1 text-[10px] text-muted">
          <span className="h-2 w-2 rounded-full" style={{ background: BAND_COLOR[b] }} />
          <span className="tabular text-ink">{counts[b] || 0}</span>
          {b}
        </span>
      ))}
    </div>
  )
}

/**
 * COMMAND CENTER = LIVE NOW.
 *
 * This screen answers one question — what is happening in Delhi at this
 * minute — and it carries the evidence for its own freshness: the snapshot
 * age, a refresh that re-runs the pipeline, and the radar loop. It has no
 * event picker and no transport controls; those belong to Replay and only to
 * Replay, so that nothing here can be mistaken for an archive playback.
 */
export default function Command() {
  const { event, t, layer, setLayer, selectedWard, selectWard, advisoryOpen, openAdvisory, closeAdvisory } =
    useStore()
  const liveMissing = useStore(selectLiveMissing)
  const liveStatus = useLive((s) => s.status)
  const events = useStore((s) => s.events)
  const wardsRes = useWards(event, t)
  const stateRes = useCityState(event, t)
  // Fetched for its provenance block as much as for its cells: it is what
  // lets the exceedance KPI state a threshold in millimetres instead of
  // repeating a legacy field name.
  const rainRes = useRain(event, t, 'nowcast', 3)
  const prov = rainRes.data?.provenance || null
  const [capOpen, setCapOpen] = useState(false)

  const ranked = useMemo(() => rankWards(wardsRes.data), [wardsRes.data])
  const ward = useMemo(() => findWard(wardsRes.data, selectedWard), [wardsRes.data, selectedWard])
  const eventName = events.find((e) => e.id === event)?.name

  return (
    <div className="relative flex h-full flex-col gap-2 overflow-hidden p-2">
      {/* ------------------------------------------------- live status ribbon */}
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-dim">
          Current conditions
        </span>
        <LiveBadge />
        <RefreshButton label="Refresh live" />
        <Prov className="ml-1" title="Every ward number on this screen comes from these models.">
          {modelName(prov?.nowcast_source, 'RainCast-v0')} → FloodRisk-v0
        </Prov>
        <div className="ml-auto min-w-0 max-w-[54%]">
          <RefreshError />
        </div>
      </div>

      {liveMissing && (
        <div className="flex shrink-0 items-start gap-2 rounded-md border border-amber/40 bg-amber/10 px-2.5 py-1.5 text-[11px] leading-snug text-amber">
          <AlertTriangle size={14} className="mt-px shrink-0" />
          {/* Two different failures, said differently. "No snapshot at all" is
              fixed by pressing refresh; "a snapshot exists but the catalogue
              does not list it" is a server-side problem and pressing refresh
              will not help, so we do not imply that it will. */}
          {liveStatus?.available ? (
            <div>
              <span className="font-semibold">
                A live snapshot exists ({liveStatus.updated_ist}) but the API is not serving it.{' '}
              </span>
              /api/events lists no <code>live</code> event, so it cannot be loaded. Showing{' '}
              <span className="font-semibold">{eventName}</span> from the archive instead — every
              number below is that historical event, not the current hour.
            </div>
          ) : (
            <div>
              <span className="font-semibold">No live snapshot yet. </span>
              This screen is showing <span className="font-semibold">{eventName}</span> from the
              archive so nothing is blank. Press “Refresh live” to run the pipeline — it takes about
              30–40 seconds — and this banner will disappear.
            </div>
          )}
        </div>
      )}

      <KpiStrip res={stateRes} provenance={prov} />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_352px] gap-2">
        <Panel
          title={liveMissing ? 'Ward choropleth — archive fallback' : 'Ward choropleth — live now'}
          right={<LayerSwitch layer={layer} setLayer={setLayer} />}
          bodyClass="relative"
        >
          {wardsRes.error && !wardsRes.data ? (
            <ErrorBox error={wardsRes.error} onRetry={wardsRes.reload} />
          ) : !wardsRes.data ? (
            <Spinner label="Loading 290 ward polygons" />
          ) : (
            <MapCanvas
              wards={wardsRes.data}
              layer={layer}
              selectedWard={selectedWard}
              onSelectWard={selectWard}
              overlay={
                <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted">
                  <div>
                    Issued {hhmm(t)} UTC · {ranked.length} wards · local vector basemap, no tile
                    server
                  </div>
                  <Prov className="mt-0.5">FloodRisk-v0 · per-ward inundation probability</Prov>
                </div>
              }
            />
          )}
        </Panel>

        {/* The rail scrolls rather than compressing — flex column, shrink-0 on
            every card. Radar (≈250 px) plus the selected-ward card plus a ward
            list does not fit a laptop viewport, and a grid track would hand each
            card less height than its content and let it spill over its
            neighbour. See the long note in Nowcast.jsx. */}
        <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
          <Panel
            title="Wards by risk"
            className="min-h-[180px] shrink-0 flex-1"
            right={<span className="tabular text-[10px] text-dim">{ranked.length}</span>}
            bodyClass="min-h-0"
          >
            {wardsRes.data ? (
              <RankedList
                rows={ranked}
                selectedWard={selectedWard}
                onSelect={selectWard}
                limit={60}
              />
            ) : (
              <Spinner label="Ranking wards" />
            )}
          </Panel>

          <Panel title="Live radar — IMD Delhi DWR" className="shrink-0">
            <RadarPanel height={190} />
          </Panel>

          <Panel title="Selected ward" className="shrink-0">
            {ward ? (
              <div className="p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold text-ink">{ward.name}</div>
                    <div className="text-[10px] uppercase tracking-wider text-dim">
                      {ward.ward_id} · {topDriver(ward.drivers) || '—'}
                    </div>
                  </div>
                  <div
                    className="tabular shrink-0 text-lg font-semibold"
                    style={{ color: BAND_COLOR[ward.risk_band] }}
                  >
                    {pct(ward.p_flood)}
                  </div>
                </div>
                <div className="tabular mt-2 grid grid-cols-3 gap-1 text-[11px] text-muted">
                  <div>
                    onset <span className="text-ink">{ward.onset || '—'}</span>
                  </div>
                  <div>
                    peak <span className="text-ink">{ward.peak || '—'}</span>
                  </div>
                  <div>
                    people <span className="text-ink">{compact(ward.people)}</span>
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    type="button"
                    onClick={() => openAdvisory(ward.ward_id)}
                    className="flex-1 rounded-md border border-teal/50 bg-teal/15 py-1.5 text-[12px] font-semibold text-teal hover:bg-teal/25"
                  >
                    AI advisory
                  </button>
                  <button
                    type="button"
                    onClick={() => setCapOpen(true)}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-amber/50 bg-amber/15 py-1.5 text-[12px] font-semibold text-amber hover:bg-amber/25"
                  >
                    <ShieldAlert size={13} /> Issue CAP
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-4 text-[12px] leading-relaxed text-muted">
                No ward selected. Click a polygon on the map or a row in the list.
                {ranked.length > 0 && (
                  <div className="mt-2">
                    <BandSummary rows={ranked} />
                  </div>
                )}
              </div>
            )}
          </Panel>
        </div>
      </div>

      <AdvisoryDrawer
        open={advisoryOpen}
        wardId={selectedWard}
        ward={ward}
        event={event}
        t={t}
        onClose={closeAdvisory}
      />
      <CapModal open={capOpen} ward={ward} event={event} t={t} onClose={() => setCapOpen(false)} />
    </div>
  )
}
