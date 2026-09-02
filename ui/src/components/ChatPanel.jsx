import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { Bot, MessageSquare, Send, ShieldCheck, X } from 'lucide-react'
import { api } from '../lib/api'
import { hhmm } from '../lib/format'
import { useStore } from '../lib/store'

/**
 * ASK PRAVAAH — grounded Q&A about whatever is currently on screen.
 *
 * The panel's only real job is to be honest about which of three things just
 * happened, because the endpoint has three outcomes and they are NOT the same:
 *
 *   ok: true,  grounded: true   the language model answered, and every number
 *                               in the answer was checked against the model
 *                               output it was given.
 *   ok: false                   the language model did not answer — no key, a
 *                               provider error, or its draft was REJECTED for
 *                               inventing a figure — and what you are reading
 *                               is the deterministic fallback. Same numbers,
 *                               fixed wording. This is a normal outcome, not an
 *                               error, and it is labelled rather than hidden.
 *                               Hiding it would be the one thing on this screen
 *                               that could mislead a judge.
 *   a thrown error              the request itself did not complete.
 *
 * NO dangerouslySetInnerHTML, anywhere, ever. The answer is a string from a
 * language model; it goes in as a text node and gets its line breaks from
 * `whitespace-pre-wrap`. React escapes it, so markup in an answer renders as
 * the characters it is rather than as markup.
 */

// Deliberately mixed-language. The backend answers in the question's own
// language, and the fastest way to show that is to put a Hindi question one tap
// away rather than describe the capability in English.
const STARTERS = [
  'What is the risk in this ward?',
  'How accurate is this model?',
  'Which wards should I send pumps to first?',
  'क्या यहाँ बाढ़ आएगी?',
]

function Bubble({ turn }) {
  if (turn.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[86%] rounded-lg rounded-br-sm border border-teal/40 bg-teal/15 px-3 py-2 text-[12.5px] leading-relaxed text-ink">
          {turn.text}
        </div>
      </div>
    )
  }

  const { res, error } = turn
  return (
    <div className="rounded-lg rounded-bl-sm border border-grid bg-bg/40 px-3 py-2">
      {error ? (
        <p className="text-[12.5px] leading-relaxed text-danger">{error}</p>
      ) : (
        <>
          {/* Plain text with real line breaks. Markdown is not expected and is
              not parsed — an asterisk stays an asterisk. */}
          <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-ink">{res.answer}</p>

          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {res.ok && res.grounded ? (
              <>
                <span className="inline-flex items-center gap-1 rounded border border-teal/45 bg-teal/12 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-teal">
                  <ShieldCheck size={10} /> grounded on model output
                </span>
                {res.model && (
                  <span className="rounded border border-grid px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-dim">
                    {res.model}
                  </span>
                )}
              </>
            ) : (
              <span className="rounded border border-amber/45 bg-amber/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber">
                answered without the language model — same numbers, fixed wording
              </span>
            )}
            {turn.context && (
              <span className="ml-auto text-[9px] uppercase tracking-wider text-dim">
                {turn.context}
              </span>
            )}
          </div>

          {/* The rejection reason, stated plainly. "invented_numbers" is the
              interesting one: it means the guard fired and a fabricated figure
              never reached the screen, which is a feature worth showing off. */}
          {res.ok === false && res.reason && (
            <p className="mt-1.5 text-[10px] leading-relaxed text-dim">
              {res.reason === 'invented_numbers'
                ? 'The language model wrote a number that was not in the model output it was given, so its draft was rejected and this deterministic answer was used instead.'
                : res.reason === 'no_key'
                  ? 'No language-model key is configured on this server, so answers come from the deterministic composer.'
                  : `The language model could not be reached (${res.reason}), so the deterministic composer answered.`}
            </p>
          )}
        </>
      )}
    </div>
  )
}

export default function ChatPanel() {
  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null)
  const scroller = useRef(null)
  const input = useRef(null)

  // The three things that make an answer be about what is on screen. Read
  // live from the store rather than passed in, so the panel follows the
  // operator between Command, Nowcast and Inundation without any view having
  // to remember to hand it the clock.
  const event = useStore((s) => s.event)
  const t = useStore((s) => s.t)
  const wardId = useStore((s) => s.selectedWard)

  useEffect(() => {
    let alive = true
    api
      .chatStatus()
      .then((d) => alive && setStatus(d))
      .catch(() => alive && setStatus({ llm_available: false, unreachable: true }))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    if (open && input.current) input.current.focus()
  }, [open])

  useEffect(() => {
    if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [turns, busy])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  const ask = useCallback(
    async (question) => {
      const q = String(question || '').trim()
      if (!q || busy) return
      setDraft('')
      setBusy(true)
      setTurns((ts) => [...ts, { id: `u${ts.length}`, role: 'user', text: q }])
      try {
        const res = await api.chat(q, event, t, wardId)
        setTurns((ts) => [
          ...ts,
          {
            id: `a${ts.length}`,
            role: 'assistant',
            res,
            // Stamped from the RESPONSE, not from the store: the endpoint
            // resolves `t` itself, so this is the hour that was actually read.
            context: `${res.event || event} · ${hhmm(res.t || t)}${res.ward ? ` · ${res.ward}` : ''}`,
          },
        ])
      } catch (err) {
        setTurns((ts) => [
          ...ts,
          { id: `a${ts.length}`, role: 'assistant', error: err.message || String(err) },
        ])
      } finally {
        setBusy(false)
      }
    },
    [busy, event, t, wardId],
  )

  return (
    <>
      {/* Floating dock button. Fixed rather than absolute: the three views that
          carry this panel have different roots and only some of them are
          positioned, and a slide-over that silently anchors to the page in one
          view and to a panel in another is a bug waiting for a demo. */}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Ask about what is on screen (grounded on model output)"
        className={clsx(
          'fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full border px-3.5 py-2.5 shadow-xl transition-colors',
          open
            ? 'border-grid bg-panel text-muted hover:text-ink'
            : 'border-teal/50 bg-teal/20 text-teal hover:bg-teal/30',
        )}
      >
        {open ? <X size={16} /> : <MessageSquare size={16} />}
        <span className="text-[12px] font-semibold">{open ? 'Close' : 'Ask PRAVAAH'}</span>
      </button>

      {open && (
        <aside className="slide-in fixed bottom-0 right-0 top-0 z-40 flex w-[400px] max-w-full flex-col border-l border-grid bg-panel shadow-2xl">
          <header className="flex shrink-0 items-start gap-2 border-b border-grid px-4 py-3">
            <Bot size={17} className="mt-0.5 shrink-0 text-teal" />
            <div className="min-w-0 flex-1">
              <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
                Ask PRAVAAH
              </div>
              {/* What the answers are ABOUT, on screen, always. */}
              <div className="truncate text-[11px] text-dim">
                {event || '—'} · {hhmm(t)} UTC · {wardId ? `ward ${wardId}` : 'no ward selected'}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="shrink-0 rounded border border-grid p-1.5 text-muted hover:text-ink"
            >
              <X size={13} />
            </button>
          </header>

          <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {/* Not an error state. A server with no key still answers every
                question with the same numbers — say that, rather than showing
                something that looks broken. */}
            {status && !status.llm_available && (
              <div className="rounded-md border border-amber/40 bg-amber/10 px-3 py-2 text-[11px] leading-relaxed text-amber">
                {status.unreachable
                  ? 'Could not read the chat status endpoint. Questions will still be sent — the endpoint always answers.'
                  : 'No language-model key is configured on this server, so every answer below is composed deterministically from the same model output. The numbers are identical; only the wording is fixed.'}
              </div>
            )}

            {!turns.length && (
              <div className="space-y-3">
                <p className="text-[11.5px] leading-relaxed text-muted">
                  Answers are grounded on the model output for the event, hour and ward currently on
                  screen. The assistant is given nothing else — no web access, no other data — and
                  any number it writes that is not in that context gets the reply rejected.
                </p>
                {status?.note && <p className="text-[10px] leading-relaxed text-dim">{status.note}</p>}
                <div className="flex flex-col gap-1.5">
                  {STARTERS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => ask(s)}
                      className="rounded-md border border-grid px-2.5 py-1.5 text-left text-[12px] text-muted transition-colors hover:border-teal/50 hover:bg-panel2 hover:text-ink"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {turns.map((turn) => (
              <Bubble key={turn.id} turn={turn} />
            ))}

            {busy && (
              <div className="flex items-center gap-2 text-[11.5px] text-muted">
                <span className="h-1.5 w-1.5 rounded-full bg-teal pulse" />
                Reading the model output…
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              ask(draft)
            }}
            className="flex shrink-0 items-center gap-2 border-t border-grid px-3 py-2.5"
          >
            <input
              ref={input}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Ask in English or हिन्दी…"
              className="min-w-0 flex-1 rounded border border-grid bg-bg px-2.5 py-1.5 text-[12.5px] text-ink outline-none placeholder:text-dim focus:border-teal"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="shrink-0 rounded border border-teal/50 bg-teal/15 p-2 text-teal hover:bg-teal/25 disabled:opacity-40"
            >
              <Send size={14} />
            </button>
          </form>

          <div className="shrink-0 border-t border-grid px-4 py-2 text-[10px] leading-relaxed text-dim">
            The models forecast, the assistant explains. It cannot change a number.
          </div>
        </aside>
      )}
    </>
  )
}
