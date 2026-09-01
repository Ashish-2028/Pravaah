import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Building2, Droplets, GraduationCap, Route, ShieldAlert, Users } from 'lucide-react'
import { api } from '../lib/api'
import { BAND_COLOR, ci90, hhmm, num, pct } from '../lib/format'
import { useResource } from '../lib/hooks'
import { useChartTheme } from '../lib/theme'
import DriverBars from './DriverBars'
import { ErrorBox, Spinner } from './ui'

const OPERATING_POINT = 0.5

function Timeline({ rows }) {
  const ct = useChartTheme()
  if (!rows || rows.length < 2) {
    return (
      <div className="px-3 py-4 text-xs text-muted">
        Only one issue time is available at this clock — the timeline fills in as the replay runs.
      </div>
    )
  }
  const data = rows.map((r) => ({ t: hhmm(r.t), p: r.p_flood * 100, r: r.risk_score * 100 }))
  return (
    <div className="h-[150px] px-1 pt-2">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 10, left: -18, bottom: 0 }}>
          <defs>
            <linearGradient id="pgrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.55} />
              <stop offset="100%" stopColor="#14b8a6" stopOpacity={0.04} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={ct.grid} vertical={false} />
          <XAxis dataKey="t" stroke={ct.axis} tick={{ fontSize: 10, fill: ct.tick }} tickLine={false} axisLine={{ stroke: ct.grid }} />
          <YAxis
            domain={[0, 100]}
            stroke={ct.axis}
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${v}%`}
          />
          <Tooltip
            contentStyle={{
              background: ct.tooltipBg,
              border: `1px solid ${ct.grid}`,
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: ct.tick }}
            formatter={(v, n) => [`${v.toFixed(1)}%`, n === 'p' ? 'P(flood)' : 'Risk score']}
          />
          <ReferenceLine
            y={OPERATING_POINT * 100}
            stroke="#f59e0b"
            strokeDasharray="4 3"
            label={{ value: 'operating point', fill: '#f59e0b', fontSize: 9, position: 'insideTopRight' }}
          />
          <Area isAnimationActive={false} type="monotone" dataKey="p" stroke="#14b8a6" strokeWidth={2} fill="url(#pgrad)" />
          <Area isAnimationActive={false} type="monotone" dataKey="r" stroke="#f59e0b" strokeWidth={1.2} fill="none" strokeDasharray="3 3" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function AssetRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-center gap-2 border-b border-grid/60 px-3 py-1.5 last:border-0">
      <Icon size={14} className="shrink-0 text-teal" />
      <span className="flex-1 text-[12px] text-muted">{label}</span>
      <span className="tabular text-[12.5px] font-semibold text-ink">{value}</span>
    </div>
  )
}

export default function WardDetail({ ward, event, t, onAdvisory, onCap }) {
  const res = useResource(() => api.ward(ward?.ward_id, event, t), [ward?.ward_id, event, t], {
    enabled: Boolean(ward?.ward_id && event && t),
  })

  if (!ward) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-muted">
        Click a ward on the map to open its inundation detail.
      </div>
    )
  }
  const band = BAND_COLOR[ward.risk_band] || '#8ba0bd'

  return (
    <div className="absolute inset-0 overflow-y-auto">
      <div className="border-b border-grid px-3 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="truncate text-[15px] font-semibold text-ink">{ward.name}</h3>
            <div className="mt-0.5 text-[10.5px] uppercase tracking-wider text-dim">
              {ward.ward_id}
            </div>
          </div>
          <span
            className="shrink-0 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider"
            style={{ color: band, background: `${band}1f`, border: `1px solid ${band}55` }}
          >
            {ward.risk_band}
          </span>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-2">
          <div>
            <div className="text-[9.5px] uppercase tracking-wider text-muted">P(flood)</div>
            <div className="tabular text-xl font-semibold" style={{ color: band }}>
              {pct(ward.p_flood)}
            </div>
          </div>
          <div>
            <div className="text-[9.5px] uppercase tracking-wider text-muted">Onset</div>
            <div className="tabular text-xl font-semibold text-ink">{ward.onset || '—'}</div>
          </div>
          <div>
            <div className="text-[9.5px] uppercase tracking-wider text-muted">Peak</div>
            <div className="tabular text-xl font-semibold text-ink">{ward.peak || '—'}</div>
          </div>
        </div>
        <div className="tabular mt-2 text-[11px] text-muted">
          90% interval:{' '}
          <span className="text-ink">{ci90(ward.ci90) || 'no crossing predicted'}</span>
          {' · '}risk score <span className="text-ink">{pct(ward.risk_score)}</span>
        </div>

        <button
          type="button"
          onClick={() => onAdvisory && onAdvisory(ward.ward_id)}
          className="mt-3 w-full rounded-md border border-teal/50 bg-teal/15 py-2 text-[12.5px] font-semibold text-teal transition-colors hover:bg-teal/25"
        >
          Open AI advisory (EN / हिन्दी)
        </button>
        {onCap && (
          <button
            type="button"
            onClick={() => onCap(ward.ward_id)}
            className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-md border border-amber/50 bg-amber/15 py-2 text-[12.5px] font-semibold text-amber transition-colors hover:bg-amber/25"
          >
            <ShieldAlert size={14} /> Issue CAP alert (Exercise)
          </button>
        )}
      </div>

      <section className="border-b border-grid">
        <h4 className="px-3 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
          Probability timeline (known at {hhmm(t)} UTC)
        </h4>
        {res.error && !res.data ? (
          <ErrorBox error={res.error} onRetry={res.reload} compact />
        ) : res.data ? (
          <Timeline rows={res.data.timeline} />
        ) : (
          <div className="h-[150px]">
            <Spinner label="Loading timeline" />
          </div>
        )}
      </section>

      <section className="border-b border-grid">
        <h4 className="px-3 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
          Top drivers
        </h4>
        <DriverBars drivers={ward.drivers} />
      </section>

      <section>
        <h4 className="px-3 pb-1 pt-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
          Affected assets
        </h4>
        <AssetRow icon={Users} label="People" value={num(ward.people)} />
        <AssetRow icon={Building2} label="Hospitals" value={num(ward.hospitals)} />
        <AssetRow icon={GraduationCap} label="Schools" value={num(ward.schools)} />
        <AssetRow icon={Route} label="Road length" value={`${num(ward.road_km, 1)} km`} />
        <AssetRow icon={Droplets} label="Pumping units" value={num(ward.pumps)} />
      </section>
    </div>
  )
}
