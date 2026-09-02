import { useMemo, useState } from 'react'
import MapCanvas from '../components/MapCanvas'
import RankedList from '../components/RankedList'
import WardDetail from '../components/WardDetail'
import AdvisoryDrawer from '../components/AdvisoryDrawer'
import CapModal from '../components/CapModal'
import { Prov } from '../components/Provenance'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { LayerSwitch } from './Command'
import { findWard, rankWards, useWards } from '../lib/hooks'
import { compact, hhmm, num } from '../lib/format'
import { useStore } from '../lib/store'

export default function Inundation() {
  const { event, t, layer, setLayer, selectedWard, selectWard, advisoryOpen, openAdvisory, closeAdvisory } =
    useStore()
  const wardsRes = useWards(event, t)
  const [capOpen, setCapOpen] = useState(false)

  const ranked = useMemo(() => rankWards(wardsRes.data), [wardsRes.data])
  const ward = useMemo(() => findWard(wardsRes.data, selectedWard), [wardsRes.data, selectedWard])

  const totals = useMemo(() => {
    const hot = ranked.filter((w) => w.risk_band === 'high' || w.risk_band === 'critical')
    return {
      wards: hot.length,
      people: hot.reduce((a, w) => a + w.people, 0),
      hospitals: hot.reduce((a, w) => a + w.hospitals, 0),
      schools: hot.reduce((a, w) => a + w.schools, 0),
      roadKm: hot.reduce((a, w) => a + w.road_km, 0),
      pumps: hot.reduce((a, w) => a + w.pumps, 0),
    }
  }, [ranked])

  return (
    <div className="relative grid h-full grid-cols-[280px_1fr_360px] gap-2 overflow-hidden p-2">
      <div className="flex min-h-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pr-0.5">
        <Panel
          title="Exposure at high + critical"
          className="shrink-0"
          right={<Prov>counted, not modelled</Prov>}
        >
          <dl className="grid grid-cols-2 gap-x-3 gap-y-2 p-3 text-[11.5px]">
            {[
              ['Wards', num(totals.wards)],
              ['People', compact(totals.people)],
              ['Hospitals', num(totals.hospitals)],
              ['Schools', num(totals.schools)],
              ['Road', `${num(totals.roadKm, 0)} km`],
              ['Pumps', num(totals.pumps)],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-[9.5px] uppercase tracking-wider text-muted">{k}</dt>
                <dd className="tabular text-base font-semibold text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
        <Panel title="Wards by risk" className="min-h-[200px] shrink-0 flex-1" bodyClass="min-h-0">
          {wardsRes.data ? (
            <RankedList rows={ranked} selectedWard={selectedWard} onSelect={selectWard} limit={80} />
          ) : (
            <Spinner label="Loading wards" />
          )}
        </Panel>
      </div>

      <Panel
        title="Inundation probability — 100 m raster aggregated to wards"
        right={<LayerSwitch layer={layer} setLayer={setLayer} />}
        bodyClass="relative"
      >
        {wardsRes.error && !wardsRes.data ? (
          <ErrorBox error={wardsRes.error} onRetry={wardsRes.reload} />
        ) : !wardsRes.data ? (
          <Spinner label="Loading ward polygons" />
        ) : (
          <MapCanvas
            wards={wardsRes.data}
            layer={layer}
            selectedWard={selectedWard}
            onSelectWard={selectWard}
            overlay={
              <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-1.5 text-[10.5px] text-muted">
                <div>Issued {hhmm(t)} UTC · click a ward for drivers, assets and advisory</div>
                <Prov className="mt-0.5">
                  FloodRisk-v0 · exposure counts from the static asset layer
                </Prov>
              </div>
            }
          />
        )}
      </Panel>

      <Panel title="Ward detail" bodyClass="min-h-0">
        <WardDetail
          ward={ward}
          event={event}
          t={t}
          onAdvisory={openAdvisory}
          onCap={() => setCapOpen(true)}
        />
      </Panel>

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
