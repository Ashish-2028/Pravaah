import { useEffect } from 'react'
import { ShieldAlert, X } from 'lucide-react'
import { ci90, compact, hhmm, pct, toIST } from '../lib/format'

/** Mock CAP card. Nothing is transmitted — this is a drafting aid for the demo. */
export default function CapModal({ open, ward, event, t, onClose }) {
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  const severity =
    ward?.risk_band === 'critical'
      ? 'Extreme'
      : ward?.risk_band === 'high'
        ? 'Severe'
        : ward?.risk_band === 'watch'
          ? 'Moderate'
          : 'Minor'

  if (!open || !ward) return null

  return (
    <div
      className="fade-in absolute inset-0 z-50 flex items-center justify-center bg-bg/75 p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="pop-in max-h-full w-full max-w-lg overflow-y-auto rounded-lg border border-amber/50 bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <header className="flex items-center gap-2 border-b border-grid bg-amber/10 px-4 py-3">
          <ShieldAlert size={18} className="text-amber" />
          <div className="flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber">
              CAP 1.2 draft — not transmitted
            </div>
            <div className="text-sm font-semibold text-ink">Common Alerting Protocol</div>
          </div>
          <button type="button" onClick={onClose} className="text-muted hover:text-ink">
            <X size={16} />
          </button>
        </header>

        <dl className="divide-y divide-grid text-[12.5px]">
          {[
            ['identifier', `PRAVAAH.${event}.${t}.${ward.ward_id}`],
            ['sender', 'pravaah.ndma.local'],
            ['sent', `${hhmm(t)}Z (${toIST(t)} IST)`],
            ['status', 'Exercise'],
            ['msgType', 'Alert'],
            ['scope', 'Public'],
            ['category', 'Met / Geo'],
            ['event', 'Urban surface inundation'],
            ['urgency', ward.onset ? 'Expected' : 'Future'],
            ['severity', severity],
            ['certainty', `Likely — P(flood) ${pct(ward.p_flood)}`],
            ['areaDesc', `${ward.name} (${ward.ward_id}), Delhi NCR`],
            ['onset', ward.onset ? `${ward.onset} IST` : 'not predicted'],
            ['expires', ward.peak ? `${ward.peak} IST` : 'next issue'],
            ['effective window', ci90(ward.ci90) || '—'],
            ['population', `${compact(ward.people)} residents`],
          ].map(([k, v]) => (
            <div key={k} className="flex gap-3 px-4 py-1.5">
              <dt className="w-36 shrink-0 text-muted">{k}</dt>
              <dd className="min-w-0 flex-1 break-words text-ink">{v}</dd>
            </div>
          ))}
        </dl>

        <footer className="border-t border-grid px-4 py-2.5 text-[10.5px] leading-relaxed text-dim">
          Drafted from precomputed model output. PRAVAAH never transmits an alert; issuing authority
          remains IMD / NDMA.
        </footer>
      </div>
    </div>
  )
}
