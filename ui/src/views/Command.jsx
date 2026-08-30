import { useMemo, useState } from 'react'
import clsx from 'clsx'
import { ShieldAlert } from 'lucide-react'
import KpiStrip from '../components/KpiStrip'
import MapCanvas from '../components/MapCanvas'
import RankedList from '../components/RankedList'
import AdvisoryDrawer from '../components/AdvisoryDrawer'
import CapModal from '../components/CapModal'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { findWard, rankWards, useCityState, useWards } from '../lib/hooks'
import { BAND_COLOR, compact, hhmm, pct, topDriver } from '../lib/format'
import { useStore } from '../lib/store'

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

export default function Command() {
  const { event, t, layer, setLayer, selectedWard, selectWard, advisoryOpen, openAdvisory, closeAdvisory } =
    useStore()
  const wardsRes = useWards(event, t)
  const stateRes = useCityState(event, t)
  const [capOpen, setCapOpen] = useState(false)

  const ranked = useMemo(() => rankWards(wardsRes.data), [wardsRes.data])
  const ward = useMemo(() => findWard(wardsRes.data, selectedWard), [wardsRes.data, selectedWard])

  return (
    <div className="relative flex h-full flex-col gap-2 overflow-hidden p-2">
      <KpiStrip res={stateRes} />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_330px] gap-2">
        <Panel
          title="Ward choropleth — Delhi NCR"
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
                  Issued {hhmm(t)} UTC · {ranked.length} wards · local GeoJSON, no basemap tiles
                </div>
              }
            />
          )}
        </Panel>

        <div className="grid min-h-0 grid-rows-[1fr_auto] gap-2">
          <Panel
            title="Wards by risk"
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

          <Panel title="Selected ward">
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
        event={event}
        t={t}
        onClose={closeAdvisory}
      />
      <CapModal open={capOpen} ward={ward} event={event} t={t} onClose={() => setCapOpen(false)} />
    </div>
  )
}
