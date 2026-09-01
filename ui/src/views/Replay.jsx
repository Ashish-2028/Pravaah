import { useEffect, useMemo, useRef } from 'react'
import clsx from 'clsx'
import { Pause, Play, SkipBack, SkipForward } from 'lucide-react'
import KpiStrip from '../components/KpiStrip'
import MapCanvas from '../components/MapCanvas'
import RankedList from '../components/RankedList'
import AdvisoryDrawer from '../components/AdvisoryDrawer'
import { ErrorBox, Panel, Spinner } from '../components/ui'
import { BandSummary, LayerSwitch } from './Command'
import { findWard, rankWards, useCityState, useWards } from '../lib/hooks'
import { prefetch } from '../lib/api'
import { BAND_COLOR, compact, hhmm, pct, toIST } from '../lib/format'
import { historicals, useStore } from '../lib/store'

const SPEEDS = [
  [1400, '0.5×'],
  [800, '1×'],
  [400, '2×'],
  [180, '5×'],
]

/**
 * THE ONLY REPLAY SCREEN.
 *
 * The event picker and the transport bar live here and nowhere else. Every
 * other view is LIVE NOW, so a judge can never be looking at a scrubbed
 * historical frame while the header says live. The mode itself is set by the
 * shell from the route — this component does not touch it.
 *
 * The dropdown lists HISTORICAL events only. The rolling `live` event has no
 * business in a replay: its frames are rewritten under you every 15 minutes,
 * which is the one thing a replay must never do.
 */
export default function Replay() {
  const {
    event, t, events, timestamps, setEvent, setT, layer, setLayer,
    playing, setPlaying, speed, setSpeed,
    selectedWard, selectWard, advisoryOpen, openAdvisory, closeAdvisory,
  } = useStore()
  const archive = historicals(events)

  const wardsRes = useWards(event, t)
  const stateRes = useCityState(event, t)
  const ranked = useMemo(() => rankWards(wardsRes.data), [wardsRes.data])
  const ward = useMemo(() => findWard(wardsRes.data, selectedWard), [wardsRes.data, selectedWard])
  const idx = timestamps.indexOf(t)

  // warm the next two frames so the step never stutters
  useEffect(() => {
    if (idx < 0) return
    prefetch(event, timestamps[idx + 1])
    prefetch(event, timestamps[idx + 2])
  }, [event, timestamps, idx])

  const tick = useRef(null)
  useEffect(() => {
    if (!playing || timestamps.length === 0) return undefined
    tick.current = setInterval(() => {
      const s = useStore.getState()
      const i = s.timestamps.indexOf(s.t)
      if (i >= s.timestamps.length - 1) {
        s.setPlaying(false)
        return
      }
      s.setT(s.timestamps[i + 1])
    }, speed)
    return () => clearInterval(tick.current)
  }, [playing, speed, timestamps.length])

  const atEnd = idx >= timestamps.length - 1

  return (
    <div className="relative flex h-full flex-col gap-2 overflow-hidden p-2">
      {/* ---------------------------------------------------- transport bar */}
      <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-lg border border-grid bg-panel px-3 py-2">
        <select
          value={event}
          onChange={(e) => setEvent(e.target.value)}
          className="rounded border border-grid bg-bg px-2 py-1.5 text-[12px] text-ink outline-none focus:border-teal"
        >
          {archive.map((ev) => (
            <option key={ev.id} value={ev.id}>
              {ev.name} · {ev.wards} wards · {ev.timestamps.length} frames
            </option>
          ))}
        </select>
        <span className="text-[10px] uppercase tracking-wider text-dim">
          {archive.length} archived events · live excluded
        </span>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => { setPlaying(false); setT(timestamps[Math.max(0, idx - 1)]) }}
            className="rounded border border-grid p-1.5 text-muted hover:text-ink"
            title="Step back"
          >
            <SkipBack size={14} />
          </button>
          <button
            type="button"
            onClick={() => {
              if (atEnd && !playing) setT(timestamps[0])
              setPlaying(!playing)
            }}
            className={clsx(
              'flex items-center gap-1.5 rounded border px-3 py-1.5 text-[12px] font-semibold',
              playing
                ? 'border-amber/50 bg-amber/15 text-amber'
                : 'border-teal/50 bg-teal/15 text-teal',
            )}
          >
            {playing ? <Pause size={14} /> : <Play size={14} />}
            {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
          </button>
          <button
            type="button"
            onClick={() => { setPlaying(false); setT(timestamps[Math.min(timestamps.length - 1, idx + 1)]) }}
            className="rounded border border-grid p-1.5 text-muted hover:text-ink"
            title="Step forward"
          >
            <SkipForward size={14} />
          </button>
        </div>

        <div className="flex overflow-hidden rounded border border-grid">
          {SPEEDS.map(([ms, label]) => (
            <button
              key={ms}
              type="button"
              onClick={() => setSpeed(ms)}
              className={clsx(
                'px-2 py-1 text-[11px]',
                speed === ms ? 'bg-teal/20 font-semibold text-teal' : 'text-muted hover:text-ink',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="tabular ml-1 text-[12px] text-muted">
          <span className="text-lg font-semibold text-ink">{hhmm(t)}</span> UTC ·{' '}
          <span className="text-teal">{toIST(t)}</span> IST · frame{' '}
          <span className="text-ink">{idx + 1}</span>/{timestamps.length}
        </div>

        <div className="ml-auto">
          <LayerSwitch layer={layer} setLayer={setLayer} />
        </div>
      </div>

      {/* ------------------------------------------------------- scrub track */}
      <div className="shrink-0 rounded-lg border border-grid bg-panel px-3 py-2">
        <div className="flex items-stretch gap-1">
          {timestamps.map((stamp, i) => (
            <button
              key={stamp}
              type="button"
              onClick={() => { setPlaying(false); setT(stamp) }}
              title={`${hhmm(stamp)} UTC / ${toIST(stamp)} IST`}
              className={clsx(
                'group flex-1 rounded-sm border-b-2 pb-1 pt-1 text-[10px] transition-colors',
                i === idx
                  ? 'border-teal bg-teal/15 font-semibold text-teal'
                  : i < idx
                    ? 'border-grid text-dim hover:text-ink'
                    : 'border-grid/50 text-dim/60 hover:text-muted',
              )}
            >
              {hhmm(stamp)}
            </button>
          ))}
        </div>
        <div className="mt-1.5 text-[10px] leading-relaxed text-dim">
          Every panel below shows only artefacts issued at or before the clock. The backend resolves
          the latest timestamp ≤ t, so the future never leaks into the replay.
        </div>
      </div>

      <KpiStrip res={stateRes} />

      <div className="grid min-h-0 flex-1 grid-cols-[1fr_320px] gap-2">
        <Panel
          title="Replay — ward choropleth"
          right={ranked.length ? <BandSummary rows={ranked} /> : null}
          bodyClass="relative"
        >
          {wardsRes.error && !wardsRes.data ? (
            <ErrorBox error={wardsRes.error} onRetry={wardsRes.reload} />
          ) : !wardsRes.data ? (
            <Spinner label="Loading frame" />
          ) : (
            <MapCanvas
              wards={wardsRes.data}
              layer={layer}
              selectedWard={selectedWard}
              onSelectWard={selectWard}
              overlay={
                <div className="pointer-events-none absolute left-3 top-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-1.5 text-[10.5px]">
                  <span className="font-semibold text-amber">REPLAY</span>{' '}
                  <span className="text-muted">
                    {events.find((e) => e.id === event)?.name} · issued {hhmm(t)} UTC
                  </span>
                </div>
              }
            />
          )}
        </Panel>

        <div className="grid min-h-0 grid-rows-[1fr_auto] gap-2">
          <Panel title="Wards by risk" bodyClass="min-h-0">
            {wardsRes.data ? (
              <RankedList rows={ranked} selectedWard={selectedWard} onSelect={selectWard} limit={60} />
            ) : (
              <Spinner label="Ranking" />
            )}
          </Panel>
          <Panel title="What we said, at this clock">
            {ward ? (
              <div className="p-3 text-[12px]">
                <div className="truncate font-semibold text-ink">{ward.name}</div>
                <div className="tabular mt-1.5 grid grid-cols-2 gap-1 text-[11px] text-muted">
                  <div>
                    P(flood){' '}
                    <span style={{ color: BAND_COLOR[ward.risk_band] }}>{pct(ward.p_flood)}</span>
                  </div>
                  <div>
                    onset <span className="text-ink">{ward.onset || '—'}</span>
                  </div>
                  <div>
                    band <span className="text-ink">{ward.risk_band}</span>
                  </div>
                  <div>
                    people <span className="text-ink">{compact(ward.people)}</span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => openAdvisory(ward.ward_id)}
                  className="mt-2.5 w-full rounded-md border border-teal/50 bg-teal/15 py-1.5 text-[12px] font-semibold text-teal hover:bg-teal/25"
                >
                  AI advisory at {hhmm(t)}
                </button>
              </div>
            ) : (
              <div className="p-3 text-[11.5px] leading-relaxed text-muted">
                Select a ward to watch its probability climb as the clock advances.
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
    </div>
  )
}
