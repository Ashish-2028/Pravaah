import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Languages, RefreshCw, X } from 'lucide-react'
import { api } from '../lib/api'
import { BAND_COLOR, ci90, compact, pct } from '../lib/format'
import { parseDrivers } from './DriverBars'
import { ErrorBox, Spinner } from './ui'

/**
 * The backend is cache-first (PRAVAAH.md §13.1): a cached advisory returns the
 * bilingual text, a miss returns {narration_available:false, properties}.
 *
 * On a miss we compose the same three fields deterministically from the model
 * numbers the endpoint DID return — no new endpoint, no invented data — and we
 * label it plainly so nobody mistakes a template for an LLM narration.
 */
function composeFromProperties(p) {
  const drivers = parseDrivers(p.drivers)
  const driverEn = drivers.map((d) => d.label).join(', ') || 'local terrain and drainage'
  const HI = {
    'low HAND': 'नाले से कम ऊँचाई',
    'low slope': 'कम ढलान',
    'high flow accumulation': 'अधिक जल-संचय',
    'distance to drain': 'नाले से दूरी',
    'impervious surface': 'पक्की सतह',
    'antecedent rain': 'पूर्ववर्ती वर्षा',
    'drain density': 'नाला घनत्व',
  }
  const driverHi = drivers.map((d) => HI[d.label] || d.label).join(', ') || 'स्थानीय भू-आकृति'
  const window = ci90(p.ci90)

  const advisory_en =
    `${p.name} (${p.ward_id}) is at ${pct(p.p_flood)} probability of surface flooding — risk band ` +
    `${String(p.risk_band).toUpperCase()}. ` +
    (p.onset
      ? `Water is expected to start collecting around ${p.onset} IST, peaking near ${p.peak || p.onset}` +
        (window ? ` (90% interval ${window})` : '') + '. '
      : 'No threshold crossing is predicted in the current window. ') +
    `About ${compact(p.people)} residents, ${p.hospitals} hospital(s) and ${p.schools} school(s) sit inside ` +
    `the ward, with ${p.road_km} km of road and ${p.pumps} pumping unit(s). ` +
    `The dominant drivers are ${driverEn}.`

  const advisory_hi =
    `${p.name} (${p.ward_id}) में जलभराव की संभावना ${pct(p.p_flood)} है — जोखिम स्तर: ` +
    `${String(p.risk_band).toUpperCase()}। ` +
    (p.onset
      ? `लगभग ${p.onset} बजे (IST) पानी जमा होना शुरू हो सकता है, चरम ${p.peak || p.onset} बजे के आसपास` +
        (window ? ` (90% अंतराल ${window})` : '') + '। '
      : 'इस अवधि में सीमा-पार होने का पूर्वानुमान नहीं है। ') +
    `इस वार्ड में लगभग ${compact(p.people)} निवासी, ${p.hospitals} अस्पताल और ${p.schools} विद्यालय हैं, ` +
    `${p.road_km} किमी सड़क और ${p.pumps} पंपिंग इकाई के साथ। ` +
    `मुख्य कारण: ${driverHi}।`

  const critical = p.risk_band === 'critical' || p.risk_band === 'high'
  const actions = critical
    ? [
        `Pre-position dewatering pumps and a control-room operator in ${p.name} before ${p.onset || 'the next update'}.`,
        `Alert the ${p.hospitals} hospital(s) and ${p.schools} school(s) in the ward; hold school dispersal until the peak passes.`,
        `Close and barricade the lowest underpass on the ward's ${p.road_km} km road network and divert traffic.`,
      ]
    : [
        `Keep ${p.name} on watch; re-check at the next 30-minute issue.`,
        `Verify that the ward's ${p.pumps} pumping unit(s) and gully gratings are clear of debris.`,
        `Brief the ${p.schools} school(s) in the ward on the standing wet-weather dispersal plan.`,
      ]

  return { advisory_en, advisory_hi, actions, composed: true }
}

function normalise(raw) {
  if (!raw) return null
  if (raw.advisory_en) {
    return {
      advisory_en: raw.advisory_en,
      advisory_hi: raw.advisory_hi,
      actions: raw.actions || [],
      generated: raw.generated,
      cached: raw.cached,
      composed: false,
      properties: raw.properties || null,
    }
  }
  if (raw.properties) {
    return { ...composeFromProperties(raw.properties), properties: raw.properties, note: raw.note }
  }
  return null
}

export default function AdvisoryDrawer({ open, wardId, event, t, onClose }) {
  const [state, setState] = useState({ data: null, error: null, loading: false })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!open || !wardId || !event || !t) return undefined
    let alive = true
    setState({ data: null, error: null, loading: true })
    api
      .advisory(wardId, event, t)
      .then((raw) => alive && setState({ data: normalise(raw), error: null, loading: false }))
      .catch((err) => alive && setState({ data: null, error: err.message, loading: false }))
    return () => {
      alive = false
    }
  }, [open, wardId, event, t, nonce])

  const a = state.data
  const p = a?.properties
  const band = p ? BAND_COLOR[p.risk_band] : '#14b8a6'

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="absolute inset-0 z-30 bg-bg/60"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            className="absolute right-0 top-0 z-40 flex h-full w-[420px] max-w-full flex-col border-l border-grid bg-panel shadow-2xl"
            initial={{ x: 440 }}
            animate={{ x: 0 }}
            exit={{ x: 440 }}
            transition={{ type: 'tween', duration: 0.22 }}
          >
            <header className="flex shrink-0 items-start gap-2 border-b border-grid px-4 py-3">
              <Languages size={17} className="mt-0.5 text-teal" />
              <div className="min-w-0 flex-1">
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                  AI Advisory
                </div>
                <div className="truncate text-sm font-semibold text-ink">
                  {p?.name || wardId || '—'}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setNonce((n) => n + 1)}
                title="Regenerate"
                className="rounded border border-grid p-1.5 text-muted hover:text-ink"
              >
                <RefreshCw size={13} />
              </button>
              <button
                type="button"
                onClick={onClose}
                className="rounded border border-grid p-1.5 text-muted hover:text-ink"
              >
                <X size={13} />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {state.loading && <Spinner label="Fetching advisory" />}
              {state.error && <ErrorBox error={state.error} onRetry={() => setNonce((n) => n + 1)} />}
              {a && (
                <div className="space-y-4 p-4">
                  {p && (
                    <div className="flex flex-wrap items-center gap-2 rounded-md border border-grid bg-bg/40 px-3 py-2">
                      <span
                        className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                        style={{ color: band, background: `${band}1f` }}
                      >
                        {p.risk_band}
                      </span>
                      <span className="tabular text-xs text-muted">
                        P(flood) <span className="text-ink">{pct(p.p_flood)}</span>
                      </span>
                      <span className="tabular text-xs text-muted">
                        onset <span className="text-ink">{p.onset || 'none'}</span>
                      </span>
                      <span className="tabular text-xs text-muted">
                        90% CI <span className="text-ink">{ci90(p.ci90) || '—'}</span>
                      </span>
                    </div>
                  )}

                  <section>
                    <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                      English
                    </h3>
                    <p className="text-[13px] leading-relaxed text-ink">{a.advisory_en}</p>
                  </section>

                  <section>
                    <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                      हिन्दी
                    </h3>
                    <p className="text-[13px] leading-relaxed text-ink">{a.advisory_hi}</p>
                  </section>

                  <section>
                    <h3 className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                      Recommended actions
                    </h3>
                    <ol className="space-y-2">
                      {a.actions.map((act, i) => (
                        <li
                          key={act}
                          className="flex gap-2.5 rounded-md border border-grid bg-bg/40 px-3 py-2 text-[12.5px] leading-relaxed text-ink"
                        >
                          <span className="tabular shrink-0 font-semibold text-teal">{i + 1}</span>
                          <span>{act}</span>
                        </li>
                      ))}
                    </ol>
                  </section>

                  {a.composed && (
                    <div className="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-[11px] leading-relaxed text-amber">
                      Cached LLM narration not available at this timestamp. The text above is
                      composed deterministically from the model numbers this endpoint returned —
                      no figure in it is invented.
                    </div>
                  )}
                </div>
              )}
            </div>

            <footer className="shrink-0 border-t border-grid px-4 py-2.5 text-[10.5px] leading-relaxed text-dim">
              AI-generated narration of model outputs — the models forecast, the AI explains.
              {a?.generated ? ` Generated ${a.generated}.` : ''}
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
