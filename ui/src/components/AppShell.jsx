import { NavLink, useLocation } from 'react-router-dom'
import clsx from 'clsx'
import {
  Activity,
  BadgeCheck,
  CloudRain,
  Gauge,
  History,
  Radio,
  Waves,
} from 'lucide-react'
import { BADGE_COLOR, hhmm, toIST } from '../lib/format'
import { useHealth } from '../lib/hooks'
import { useStore } from '../lib/store'

const NAV = [
  { to: '/command', label: 'Command Center', icon: Gauge },
  { to: '/inundation', label: 'Inundation + Impact', icon: Waves },
  { to: '/replay', label: 'Replay', icon: History },
  { to: '/verify', label: 'Verification', icon: BadgeCheck },
  { to: '/nowcast', label: 'Nowcast 0–6 h', icon: CloudRain },
  { to: '/forecast', label: 'Forecast 6–72 h', icon: Activity },
]

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
    <div className="flex items-center gap-1.5">
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

function ModeToggle() {
  const mode = useStore((s) => s.mode)
  const setMode = useStore((s) => s.setMode)
  return (
    <div className="flex overflow-hidden rounded border border-grid">
      {['live', 'replay'].map((m) => (
        <button
          key={m}
          type="button"
          onClick={() => setMode(m)}
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
          {m}
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

export default function AppShell({ children }) {
  const events = useStore((s) => s.events)
  const event = useStore((s) => s.event)
  const location = useLocation()
  const eventName = events.find((e) => e.id === event)?.name

  return (
    <div className="flex h-full w-full bg-bg text-ink">
      <aside className="flex w-[212px] shrink-0 flex-col border-r border-grid bg-panel">
        <div className="flex items-center gap-2 border-b border-grid px-4 py-3.5">
          <Radio size={20} className="text-teal" />
          <div className="min-w-0">
            <div className="text-base font-bold leading-none tracking-[0.18em] text-ink">
              PRAVAAH
            </div>
            <div className="mt-1 truncate text-[9px] uppercase tracking-[0.12em] text-muted">
              Flood Early Warning
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
            <div className="text-sm font-semibold leading-tight text-ink">Delhi NCR</div>
            <div className="truncate text-[11px] text-muted">
              {eventName || 'Loading event catalogue…'}
            </div>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <ModeToggle />
            <Clock />
            <SourceBadges />
          </div>
        </header>

        <main key={location.pathname} className="min-h-0 flex-1 overflow-hidden">
          {children}
        </main>
      </div>
    </div>
  )
}
