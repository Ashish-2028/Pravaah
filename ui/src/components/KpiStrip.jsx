import { CITY_RISK_COLOR, compact, minutes, num, pct } from '../lib/format'
import { ErrorBox, Spinner, Stat } from './ui'

export default function KpiStrip({ res }) {
  if (res.error && !res.data) return <ErrorBox error={res.error} onRetry={res.reload} />
  if (!res.data) return <Spinner label="Loading city state" />
  const k = res.data
  const riskColor = CITY_RISK_COLOR[k.city_risk] || '#8ba0bd'
  const ttc = k.time_to_critical_min
  const ttcColor = ttc === null ? '#5d738f' : ttc <= 30 ? '#ef4444' : ttc <= 90 ? '#f59e0b' : '#14b8a6'

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
      <Stat
        label="Rain now"
        value={`${num(k.rain_now_mm_h, 1)} mm/h`}
        sub="city max, latest observation"
        color={k.rain_now_mm_h >= 40 ? '#ef4444' : k.rain_now_mm_h >= 15 ? '#f59e0b' : '#14b8a6'}
        accent={Math.min(1, k.rain_now_mm_h / 80)}
      />
      <Stat
        label="P(3 h > 50 mm)"
        value={pct(k.p3h50)}
        sub="calibrated exceedance probability"
        color={k.p3h50 >= 0.6 ? '#ef4444' : k.p3h50 >= 0.3 ? '#f59e0b' : '#14b8a6'}
        accent={k.p3h50}
      />
      <Stat
        label="City flood risk"
        value={k.city_risk}
        sub="aggregate of 290 wards"
        color={riskColor}
        accent={{ LOW: 0.25, WATCH: 0.5, HIGH: 0.75, CRITICAL: 1 }[k.city_risk] ?? 0.2}
      />
      <Stat
        label="Time to critical"
        value={minutes(ttc)}
        sub={ttc === null ? 'no threshold crossing' : 'until first ward crosses'}
        color={ttcColor}
        accent={ttc === null ? 0.05 : Math.max(0.05, 1 - Math.min(1, ttc / 180))}
      />
      <Stat
        label="People exposed"
        value={compact(k.people_exposed)}
        sub={`${num(k.people_exposed)} residents`}
        color="#e5edf7"
      />
    </div>
  )
}
