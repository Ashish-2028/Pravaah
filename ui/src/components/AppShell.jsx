import { useEffect, useRef } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import clsx from 'clsx'
import {
  Activity,
  BadgeCheck,
  CloudRain,
  Gauge,
  History,
  Moon,
  Sun,
  Waves,
} from 'lucide-react'
import { BADGE_COLOR, hhmm, toIST } from '../lib/format'
import { useHealth } from '../lib/hooks'
import { useLivePump } from '../lib/live'
import { useStore } from '../lib/store'
import { useTheme } from '../lib/theme'
import { LiveBadge, RefreshButton } from './LiveBadge'

// Order is the demo's own narrative: where are we now, what happens in the
// next six hours, what happens in the next three days, who gets wet, what did
// we say last time, and does any of it verify.
const NAV = [
  { to: '/command', label: 'Command Center', icon: Gauge },
  { to: '/nowcast', label: 'Nowcast 0–6 h', icon: CloudRain },
  { to: '/forecast', label: 'Forecast 6–72 h', icon: Activity },
  { to: '/inundation', label: 'Inundation + Impact', icon: Waves },
  { to: '/replay', label: 'Replay', icon: History },
  { to: '/verify', label: 'Verification', icon: BadgeCheck },
]

/** The one route that is a replay screen. Everything else is LIVE NOW. */
export const REPLAY_ROUTE = '/replay'

// The API health payload calls the fourth feed "stations"; the deck calls the
// same badge STATIC. We show the API's own keys so the badge can never lie.
const BADGE_KEYS = [
  ['sat', 'SAT'],
  ['radar', 'RADAR'],
  ['nwp', 'NWP'],
  ['stations', 'STATIONS'],
]

function SourceBadges() {
  const health = useHealth()
  const badges = health?.badges
  return (
    <div className="hidden items-center gap-1.5 2xl:flex">
      {BADGE_KEYS.map(([key, label]) => {
        const stateName = badges?.[key] || 'unknown'
        const color = BADGE_COLOR[stateName] || '#5d738f'
        return (
          <div
            key={key}
            title={`${label}: ${stateName}`}
            className="flex items-center gap-1.5 rounded border px-2 py-1"
            style={{ borderColor: `${color}55`, background: `${color}14` }}
          >
            <span
              className={clsx('h-1.5 w-1.5 rounded-full', stateName === 'down' && 'pulse')}
              style={{ background: color }}
            />
            <span className="text-[10px] font-semibold tracking-wider" style={{ color }}>
              {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/**
 * LIVE | REPLAY, and it means something now.
 *
 * The mode is not a piece of decorative state that views consult — it IS the
 * route. REPLAY takes you to the only screen with an event picker and a
 * transport bar; LIVE takes you back to whichever live screen you came from.
 * Because the mode is derived from the location, a play loop can never be
 * running underneath a live panel, and the live pump never advances a clock
 * somebody is scrubbing.
 */
function ModeToggle() {
  const mode = useStore((s) => s.mode)
  const navigate = useNavigate()
  const location = useLocation()
  const lastLive = useRef('/command')
  if (location.pathname !== REPLAY_ROUTE) lastLive.current = location.pathname

  return (
    <div className="flex overflow-hidden rounded border border-grid">
      {[
        ['live', 'live'],
        ['replay', 'replay'],
      ].map(([m, label]) => (
        <button
          key={m}
          type="button"
          onClick={() => navigate(m === 'replay' ? REPLAY_ROUTE : lastLive.current || '/command')}
          title={
            m === 'live'
              ? 'Current conditions, pinned to the newest live frame'
              : 'Historical events with play, pause and scrub'
          }
          className={clsx(
            'px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider transition-colors',
            mode === m ? 'bg-teal/20 text-teal' : 'text-muted hover:text-ink',
          )}
        >
          {m === 'live' && (
            <span
              className={clsx(
                'mr-1.5 inline-block h-1.5 w-1.5 rounded-full align-middle',
                mode === 'live' ? 'bg-teal pulse' : 'bg-grid',
              )}
            />
          )}
          {label}
        </button>
      ))}
    </div>
  )
}

function Clock() {
  const t = useStore((s) => s.t)
  const mode = useStore((s) => s.mode)
  return (
    <div className="flex items-baseline gap-2 rounded border border-grid bg-panel px-2.5 py-1">
      <span className="tabular text-lg font-semibold leading-none text-ink">{hhmm(t)}</span>
      <span className="text-[10px] uppercase tracking-wider text-muted">UTC</span>
      <span className="tabular text-sm leading-none text-teal">{toIST(t)}</span>
      <span className="text-[10px] uppercase tracking-wider text-muted">IST</span>
      {mode === 'replay' && (
        <span className="ml-1 rounded bg-amber/20 px-1 text-[9px] font-bold uppercase tracking-wider text-amber">
          replay
        </span>
      )}
    </div>
  )
}

/** Dark by default because this is a control room; light exists for projectors
 *  that wash the dark palette out to mud. One `data-theme` stamp swaps every
 *  colour in the app, map included. */
function ThemeToggle() {
  const theme = useTheme((s) => s.theme)
  const toggleTheme = useTheme((s) => s.toggleTheme)
  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={
        theme === 'dark'
          ? 'Switch to the light theme (for washed-out projectors)'
          : 'Switch back to the dark control-room theme'
      }
      className="rounded border border-grid p-1.5 text-muted transition-colors hover:border-teal/50 hover:text-teal"
    >
      {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
    </button>
  )
}

export default function AppShell({ children }) {
  const events = useStore((s) => s.events)
  const event = useStore((s) => s.event)
  const mode = useStore((s) => s.mode)
  const setMode = useStore((s) => s.setMode)
  const location = useLocation()
  const eventName = events.find((e) => e.id === event)?.name

  // Route -> mode. The single writer of `mode` in the whole app.
  useEffect(() => {
    setMode(location.pathname === REPLAY_ROUTE ? 'replay' : 'live')
  }, [location.pathname, setMode])

  // Status polling + the live refetch loop. Mounted once, here, so no view has
  // to remember to start it and two views can never start it twice.
  useLivePump()

  return (
    <div className="flex h-full w-full bg-bg text-ink">
      <aside className="flex w-[212px] shrink-0 flex-col border-r border-grid bg-panel">
        <div className="flex items-center gap-2.5 border-b border-grid px-3 py-3">
          {/* The wordmark ships with its own dark ground, so it keeps its own
              tile in both themes rather than being knocked out on light. */}
          <img
            src="/pravaah-wordmark.png"
            alt="PRAVAAH"
            width={608}
            height={440}
            className="h-[52px] w-auto shrink-0 rounded border border-grid"
          />
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase leading-tight tracking-[0.1em] text-ink">
              Flood Early
              <br />
              Warning
            </div>
            <div className="mt-1 truncate text-[9px] uppercase tracking-[0.12em] text-dim">
              Delhi NCR
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'mb-0.5 flex items-center gap-2.5 rounded-md px-2.5 py-2 text-[13px] transition-colors',
                  isActive
                    ? 'bg-teal/15 font-medium text-teal'
                    : 'text-muted hover:bg-panel2 hover:text-ink',
                )
              }
            >
              <Icon size={16} className="shrink-0" />
              <span className="truncate">{label}</span>
              {to === REPLAY_ROUTE && (
                <span className="ml-auto text-[8.5px] uppercase tracking-wider text-dim">
                  archive
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-grid px-3 py-2.5 text-[10px] leading-relaxed text-muted">
          <div className="font-semibold uppercase tracking-wider text-dim">Offline build</div>
          <div className="mt-1">No external tiles, fonts or CDNs. Every request goes to localhost.</div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-3 border-b border-grid bg-panel px-4 py-2.5">
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-tight text-ink">
              Delhi NCR
              <span className="ml-2 text-[10px] font-semibold uppercase tracking-wider text-dim">
                {mode === 'replay' ? 'archive replay' : 'live now'}
              </span>
            </div>
            <div className="truncate text-[11px] text-muted">
              {eventName || 'Loading event catalogue…'}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2.5">
            {/* The age of the live snapshot is visible on EVERY screen,
                including the replay ones — the operator should never have to
                navigate to find out how old the live picture is. */}
            <LiveBadge />
            <RefreshButton />
            <ModeToggle />
            <Clock />
            <SourceBadges />
            <ThemeToggle />
          </div>
        </header>

        <main key={location.pathname} className="min-h-0 flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}
