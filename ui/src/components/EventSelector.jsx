// The compact event selector for the Nowcast and Forecast views.
//
// WHY IT EXISTS. Both views were LIVE-only, and in a calm September every
// panel on them is the same low-risk blue. The colour ramp, the critical
// bands and what the two models actually do in a cloudburst were therefore
// undemonstrable — the Replay view can show that for the ward layer, but
// nothing could show it for the rain fields.
//
// WHAT IT IS NOT. This is deliberately NOT the replay transport. No play, no
// pause, no speed, no auto-advance, no timer of any kind. Those stay unique
// to /replay so two clocks can never run against each other. All this does is
// pick one frozen (event, hour) pair and hold it still.
//
// THE HONESTY RULE. When a historical event is selected these views are not
// live and must not read as live anywhere: the bar turns amber, an ARCHIVE
// chip appears here, in the map overlay and in the shell header, and the date
// is spelled out. A judge must never mistake a 2021 storm for this morning.

import { useMemo } from 'react'
import clsx from 'clsx'
import { History, Radio, Zap } from 'lucide-react'
import { hhmm, toIST } from '../lib/format'
import { historicals, peakHourOf, useStore } from '../lib/store'

/**
 * The (event, t) pair a selector view should render, and whether that pair is
 * an archive override or the shared live clock.
 *
 * Read this INSTEAD OF `event`/`t` in any view that mounts <EventSelector/>.
 * Every panel then follows the selection for free, because they all already
 * take (event, t) and the API already takes ?event=&t=.
 */
export function useViewClock() {
  const archiveEvent = useStore((s) => s.archiveEvent)
  const archiveT = useStore((s) => s.archiveT)
  const liveEvent = useStore((s) => s.event)
  const liveT = useStore((s) => s.t)
  const liveMissing = useStore((s) => !s.liveEvent)

  const isArchive = Boolean(archiveEvent)
  return {
    event: isArchive ? archiveEvent : liveEvent,
    t: isArchive ? archiveT : liveT,
    isArchive,
    // LIVE mode showing a historical fallback because the pipeline has never
    // run. Not the same thing as an archive override, and not live either.
    liveMissing: !isArchive && liveMissing,
  }
}

/** Newest first, and derived from the catalogue — never a hardcoded list. */
function useArchiveEvents() {
  const events = useStore((s) => s.events)
  return useMemo(
    () => historicals(events).slice().sort((a, b) => String(b.id).localeCompare(String(a.id))),
    [events],
  )
}

/** "val" / "train" / whatever the catalogue adds next, quietly. */
function SplitTag({ split, note, className }) {
  if (!split) return null
  return (
    <span
      title={
        note ||
        `This demo day falls in the "${split}" split. The replay demonstrates the product; the skill numbers in Verification come from the held-out test year.`
      }
      className={clsx(
        'rounded border border-grid px-1 py-px text-[9px] font-semibold uppercase tracking-wider text-dim',
        className,
      )}
    >
      {split}
    </span>
  )
}

/**
 * The archive/live tag for a map overlay. Exported so both views stamp the
 * same words on the canvas itself, where a screenshot of the map alone still
 * carries the disclaimer.
 */
export function ClockTag({ isArchive, event, t, liveMissing }) {
  const events = useStore((s) => s.events)
  const name = events.find((e) => e.id === event)?.name
  if (isArchive) {
    return (
      <span>
        <span className="font-semibold text-amber">ARCHIVE</span>{' '}
        <span className="text-muted">
          {name || event} · {hhmm(t)} UTC / {toIST(t)} IST · not current conditions
        </span>
      </span>
    )
  }
  if (liveMissing) {
    return (
      <span>
        <span className="font-semibold text-amber">NO LIVE SNAPSHOT</span>{' '}
        <span className="text-muted">showing {name || event}</span>
      </span>
    )
  }
  return (
    <span>
      <span className="font-semibold text-teal">LIVE</span>{' '}
      <span className="text-muted">{name || event} · issued {hhmm(t)} UTC</span>
    </span>
  )
}

export default function EventSelector({ note }) {
  const events = useStore((s) => s.events)
  const splitNote = useStore((s) => s.splitNote)
  const setArchiveEvent = useStore((s) => s.setArchiveEvent)
  const setArchiveT = useStore((s) => s.setArchiveT)
  const liveEvent = useStore((s) => s.liveEvent)
  const { event, t, isArchive, liveMissing } = useViewClock()
  const archive = useArchiveEvents()

  const selected = events.find((e) => e.id === event) || null
  const stamps = selected?.timestamps || []
  const peak = peakHourOf(events, event)
  const liveName = events.find((e) => e.id === liveEvent)?.name || 'Live'

  return (
    <div
      className={clsx(
        'flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border px-3 py-2',
        isArchive ? 'border-amber/45 bg-amber/[0.06]' : 'border-grid bg-panel',
      )}
    >
      {/* ------------------------------------------------------- mode chip */}
      <div
        className={clsx(
          'flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-[0.14em]',
          isArchive || liveMissing
            ? 'bg-amber/20 text-amber'
            : 'bg-teal/15 text-teal',
        )}
        title={
          isArchive
            ? 'A past event is on screen. These panels are NOT showing current conditions.'
            : liveMissing
              ? 'The live pipeline has produced no snapshot yet, so a historical day is standing in.'
              : 'Current conditions, pinned to the newest live frame.'
        }
      >
        {isArchive ? (
          <History size={11} />
        ) : (
          <span
            className={clsx(
              'h-1.5 w-1.5 rounded-full',
              liveMissing ? 'bg-amber' : 'bg-teal pulse',
            )}
          />
        )}
        {isArchive ? 'Archive' : liveMissing ? 'No live data' : 'Live'}
      </div>

      {/* ----------------------------------------------------- event picker */}
      <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-dim">
        Event
        <select
          value={isArchive ? event : ''}
          onChange={(e) => setArchiveEvent(e.target.value || null)}
          className={clsx(
            'rounded border bg-bg px-2 py-1 text-[12px] normal-case tracking-normal text-ink outline-none focus:border-teal',
            isArchive ? 'border-amber/50' : 'border-grid',
          )}
        >
          <option value="">{liveEvent ? `${liveName} — live now` : 'Live (no snapshot yet)'}</option>
          {archive.map((ev) => (
            <option key={ev.id} value={ev.id}>
              {ev.name}
              {ev.split ? ` · ${ev.split}` : ''} · {ev.timestamps.length} frames
            </option>
          ))}
        </select>
      </label>

      {/* ------------------------------------------------------ hour picker */}
      {isArchive && (
        <>
          <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-dim">
            Hour
            <select
              value={t || ''}
              onChange={(e) => setArchiveT(e.target.value)}
              className="rounded border border-amber/50 bg-bg px-2 py-1 text-[12px] normal-case tracking-normal tabular text-ink outline-none focus:border-teal"
            >
              {stamps.map((s) => (
                <option key={s} value={s}>
                  {hhmm(s)} UTC · {toIST(s)} IST{s === peak ? ' · peak' : ''}
                </option>
              ))}
            </select>
          </label>

          {/* The catalogue names the storm peak. Surfacing it as one click is
              the difference between a presenter finding the cloudburst and a
              presenter scrolling past it. Hidden entirely when an event does
              not declare one. */}
          {peak && stamps.includes(peak) && (
            <button
              type="button"
              onClick={() => setArchiveT(peak)}
              title={`Jump to the storm peak declared in the event catalogue (${hhmm(peak)} UTC / ${toIST(peak)} IST)`}
              className={clsx(
                'flex items-center gap-1 rounded border px-2 py-1 text-[11px]',
                t === peak
                  ? 'border-amber/60 bg-amber/20 font-semibold text-amber'
                  : 'border-grid text-muted hover:text-ink',
              )}
            >
              <Zap size={11} /> Peak {hhmm(peak)}Z
            </button>
          )}

          <button
            type="button"
            onClick={() => setArchiveEvent(null)}
            title="Return these panels to the live pipeline"
            className="flex items-center gap-1 rounded border border-teal/50 px-2 py-1 text-[11px] text-teal hover:bg-teal/15"
          >
            <Radio size={11} /> Back to live
          </button>
        </>
      )}

      {/* ------------------------------------------------------- provenance */}
      <div className="ml-auto flex items-center gap-2 text-[10.5px] text-dim">
        {selected?.imd_rain_mm !== undefined && selected?.imd_rain_mm !== null && (
          <span title="IMD 24 h rain-day total recorded for this event, from the event catalogue.">
            IMD {selected.imd_rain_mm} mm
          </span>
        )}
        <SplitTag split={selected?.split} note={splitNote} />
      </div>

      {/* A selector-wide caveat the view can specialise. Full width so it
          never competes with the controls above it. */}
      {(isArchive || note) && (
        <p className="w-full text-[10px] leading-relaxed text-dim">
          {isArchive && (
            <span className="text-amber/90">
              Showing {selected?.name || event} at {hhmm(t)} UTC / {toIST(t)} IST — a past event,
              not current conditions.{' '}
            </span>
          )}
          {isArchive && splitNote ? `${splitNote} ` : ''}
          {note}
        </p>
      )}
    </div>
  )
}
