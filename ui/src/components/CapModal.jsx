import { useEffect, useState } from 'react'
import { Check, Copy, FileCode2, MessageCircle, ShieldAlert, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { BAND_COLOR } from '../lib/format'
import { useResource } from '../lib/hooks'
import { ErrorBox, Spinner } from './ui'

/**
 * The alerting layer's front end.
 *
 * WHAT THIS DOES AND DOES NOT DO
 * ------------------------------
 * It renders a CAP 1.2 document the backend generated from this ward's own
 * precomputed numbers, and it offers a wa.me deep link. Nothing is sent from
 * here: the link is a user-initiated navigation that opens WhatsApp with the
 * message pre-composed, and a human still has to pick a recipient and press
 * send. No recipient is pre-filled and no emergency number appears anywhere.
 *
 * The offline build is preserved for the same reason — wa.me is never
 * fetched, embedded or preconnected. It is only ever an href a person clicks.
 *
 * Every alert this modal can produce is status=Exercise (see serve/cap.py).
 * The EXERCISE banner below is not decoration; do not remove it.
 */

function Field({ k, v, mono }) {
  if (v === null || v === undefined || v === '') return null
  return (
    <div className="flex gap-3 px-4 py-1.5">
      <dt className="w-[104px] shrink-0 text-muted">{k}</dt>
      <dd
        className={clsx(
          'min-w-0 flex-1 whitespace-pre-wrap break-words text-ink',
          mono && 'font-mono text-[11px] leading-relaxed',
        )}
      >
        {v}
      </dd>
    </div>
  )
}

function CopyButton({ text, label, disabled }) {
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return undefined
    const id = setTimeout(() => setDone(false), 1600)
    return () => clearTimeout(id)
  }, [done])

  const copy = async () => {
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      setDone(true)
    } catch {
      // Clipboard API needs a secure context. Fall back to a selection-based
      // copy so the demo still works over plain http on a projector laptop.
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        setDone(true)
      } catch {
        /* nothing more we can do — the text is on screen to select by hand */
      }
      document.body.removeChild(ta)
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      disabled={disabled || !text}
      className="flex items-center justify-center gap-1.5 rounded-md border border-grid bg-panel2 px-3 py-2 text-[12px] font-semibold text-ink transition-colors hover:bg-grid disabled:opacity-40"
    >
      {done ? <Check size={13} className="text-teal" /> : <Copy size={13} />}
      {done ? 'Copied' : label}
    </button>
  )
}

const TABS = [
  ['rendered', 'Rendered alert'],
  ['xml', 'Raw CAP 1.2 XML'],
  ['message', 'WhatsApp message'],
]

export default function CapModal({ open, ward, event, t, onClose }) {
  const [tab, setTab] = useState('rendered')
  const wardId = ward?.ward_id

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Reset to the rendered view each time the modal is opened on a new ward,
  // so the presenter never re-opens it into a wall of XML.
  useEffect(() => {
    if (open) setTab('rendered')
  }, [open, wardId])

  const enabled = Boolean(open && wardId && event && t)
  const res = useResource(() => api.capPreview(wardId, event, t), [wardId, event, t], { enabled })
  const xmlRes = useResource(() => api.capXml(wardId, event, t), [wardId, event, t], { enabled })

  if (!open || !ward) return null
  const cap = res.data
  const band = BAND_COLOR[ward.risk_band] || '#8ba0bd'

  return (
    <div
      className="fade-in absolute inset-0 z-50 flex items-center justify-center bg-bg/80 p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="pop-in flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-amber/50 bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="presentation"
      >
        <header className="flex shrink-0 items-center gap-2 border-b border-grid bg-amber/10 px-4 py-3">
          <ShieldAlert size={18} className="shrink-0 text-amber" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber">
              CAP 1.2 · status = Exercise · nothing transmitted
            </div>
            <div className="truncate text-sm font-semibold text-ink">
              Common Alerting Protocol — {ward.name}
            </div>
          </div>
          <span
            className="shrink-0 rounded px-2 py-1 text-[10px] font-bold uppercase tracking-wider"
            style={{ color: band, background: `${band}1f`, border: `1px solid ${band}55` }}
          >
            {ward.risk_band}
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 text-muted hover:text-ink"
          >
            <X size={16} />
          </button>
        </header>

        {/* THE DEMO MARKER. Structural, not decorative — this modal generates
            official-looking emergency alerts and must never be mistakable for
            a live IMD/NDMA bulletin. */}
        <div className="shrink-0 border-b border-amber/40 bg-amber/15 px-4 py-2 text-center text-[11px] font-bold uppercase tracking-[0.12em] text-amber">
          Exercise — demonstration message — not a real alert
        </div>

        <nav className="flex shrink-0 gap-1 border-b border-grid px-3 pt-2">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              className={clsx(
                'rounded-t-md border-b-2 px-3 py-1.5 text-[11.5px] transition-colors',
                tab === key
                  ? 'border-teal font-semibold text-teal'
                  : 'border-transparent text-muted hover:text-ink',
              )}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {res.error && !cap ? (
            <ErrorBox error={res.error} onRetry={res.reload} />
          ) : !cap ? (
            <Spinner label="Generating CAP alert" />
          ) : tab === 'rendered' ? (
            <dl className="divide-y divide-grid text-[12.5px]">
              <Field k="identifier" v={cap.identifier} mono />
              <Field k="sender" v={cap.sender} mono />
              <Field k="senderName" v={cap.senderName} />
              <Field k="sent" v={cap.sent} mono />
              <Field k="status" v={`${cap.status}  ← not "Actual"`} />
              <Field k="msgType" v={cap.msgType} />
              <Field k="scope" v={cap.scope} />
              <Field k="category" v={cap.category} />
              <Field k="event" v={cap.event} />
              <Field k="urgency" v={cap.urgency} />
              <Field k="severity" v={cap.severity} />
              <Field k="certainty" v={`${cap.certainty} — P(flood) ${cap.p_flood_pct}%`} />
              <Field k="responseType" v={cap.responseType} />
              <Field k="effective" v={cap.effective} mono />
              <Field k="expires" v={cap.expires} mono />
              <Field k="headline" v={cap.headline} />
              <Field k="areaDesc" v={cap.areaDesc} />
              <Field
                k="polygon"
                v={
                  cap.polygon
                    ? `${cap.polygon.split(' ').length} vertices (lat,lon closed ring)`
                    : 'no geometry available'
                }
              />
              <Field k="description" v={cap.description} />
              <Field k="instruction" v={cap.instruction} />
              <Field k="note" v={cap.note} />
            </dl>
          ) : tab === 'xml' ? (
            xmlRes.error && !xmlRes.data ? (
              <ErrorBox error={xmlRes.error} onRetry={xmlRes.reload} />
            ) : !xmlRes.data ? (
              <Spinner label="Rendering XML" />
            ) : (
              <pre className="overflow-x-auto px-4 py-3 font-mono text-[10.5px] leading-[1.5] text-ink">
                {xmlRes.data}
              </pre>
            )
          ) : (
            <div className="px-4 py-4">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted">
                Pre-composed message (~{cap.whatsapp_text.length} characters)
              </div>
              <pre className="mt-2 whitespace-pre-wrap rounded-md border border-grid bg-panel2 px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-ink">
                {cap.whatsapp_text}
              </pre>
              <p className="mt-3 text-[11px] leading-relaxed text-muted">
                Clicking <span className="text-ink">Send via WhatsApp</span> opens WhatsApp with
                this text already typed. PRAVAAH has no WhatsApp account, no API key and no
                recipient list — you choose the contact and you press send. Nothing leaves this
                machine until you do.
              </p>
            </div>
          )}
        </div>

        <footer className="shrink-0 border-t border-grid px-4 py-3">
          <div className="flex flex-wrap gap-2">
            <a
              href={cap?.whatsapp_url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              aria-disabled={!cap}
              onClick={(e) => {
                if (!cap) e.preventDefault()
              }}
              className={clsx(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md border border-teal/50 bg-teal/15 px-3 py-2 text-[12.5px] font-semibold text-teal transition-colors hover:bg-teal/25',
                !cap && 'pointer-events-none opacity-40',
              )}
            >
              <MessageCircle size={14} /> Send via WhatsApp
            </a>
            <CopyButton text={xmlRes.data} label="Copy XML" disabled={!xmlRes.data} />
            <CopyButton text={cap?.whatsapp_text} label="Copy message" disabled={!cap} />
            <a
              href={wardId && event && t ? api.capXmlUrl(wardId, event, t) : '#'}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-center gap-1.5 rounded-md border border-grid bg-panel2 px-3 py-2 text-[12px] font-semibold text-ink transition-colors hover:bg-grid"
            >
              <FileCode2 size={13} /> Open XML
            </a>
          </div>
          <p className="mt-2.5 text-[10.5px] leading-relaxed text-dim">
            Drafted from precomputed model output; every figure above comes from this ward&apos;s
            properties. <span className="text-amber">status=Exercise</span> — PRAVAAH never
            transmits an alert, and issuing authority for a real one remains IMD / NDMA.
          </p>
        </footer>
      </div>
    </div>
  )
}
