import { useEffect, useMemo, useRef, useState } from 'react'
import clsx from 'clsx'
import { Pause, Play, Radar } from 'lucide-react'
import { useRadarManifest } from '../lib/hooks'
import { Spinner } from './ui'

const BASE = '/static/live/frames'
const FRAME_MS = 550

/**
 * Same-origin only. The manifest is written by our own pipeline, but it is
 * still data arriving over HTTP, and this app's offline guarantee is that
 * NOTHING is ever fetched from another host. An absolute URL is dropped rather
 * than rendered.
 */
function localUrl(url) {
  if (typeof url !== 'string' || !url) return null
  if (/^[a-z]+:/i.test(url) || url.startsWith('//')) return null
  return url.startsWith('/') ? url : `${BASE}/${url.replace(/^\.\//, '')}`
}

/**
 * Live IMD Delhi DWR captures, animated.
 *
 * HONESTY IS THE FEATURE HERE. These are pictures of a radar product. Nothing
 * decodes them, no model consumes them, and no number anywhere else in this UI
 * is derived from them. The manifest carries that statement in its
 * `disclaimer` field and this panel renders it verbatim, on screen, next to
 * the animation — not in a tooltip, because a judge watching the loop from
 * three metres away has to see it too.
 */
export default function RadarPanel({ className, height = 260 }) {
  const res = useRadarManifest()
  const manifest = res.data
  const [productKey, setProductKey] = useState(null)
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(true)
  // Tracked per-URL rather than as a boolean, so a missing capture cannot
  // leave the next frame blanked out too.
  const [brokenSrc, setBrokenSrc] = useState(null)

  const products = useMemo(() => {
    const p = manifest?.products
    if (!p || typeof p !== 'object') return []
    return Object.entries(p)
      .map(([key, v]) => ({
        key,
        label: v?.label || key,
        frames: (Array.isArray(v?.frames) ? v.frames : [])
          .map((f) => ({ ...f, src: localUrl(f?.url) }))
          .filter((f) => f.src),
      }))
      .filter((p2) => p2.frames.length)
  }, [manifest])

  const product = products.find((p) => p.key === productKey) || products[0] || null
  const frames = product?.frames || []
  // Derived, never stored: a refresh can shorten the loop under us and a
  // clamped index that lives in state would need an effect to chase it.
  const at = frames.length ? Math.min(i, frames.length - 1) : 0
  const frame = frames.length ? frames[at] : null
  const broken = Boolean(frame && brokenSrc === frame.src)

  const countRef = useRef(frames.length)
  useEffect(() => {
    countRef.current = frames.length
  }, [frames.length])

  useEffect(() => {
    if (!playing || frames.length < 2) return undefined
    const id = setInterval(() => setI((v) => (v + 1) % (countRef.current || 1)), FRAME_MS)
    return () => clearInterval(id)
  }, [playing, frames.length])

  // Warm the whole loop so the animation does not stutter on first pass.
  // Keyed on the joined URL list, not the array identity, so a re-render does
  // not re-request 12 images.
  const srcKey = frames.map((f) => f.src).join('|')
  useEffect(() => {
    srcKey.split('|').filter(Boolean).forEach((src) => {
      const img = new Image()
      img.src = src
    })
  }, [srcKey])

  if (res.loading && !manifest) return <Spinner label="Loading radar captures" />

  if (!products.length) {
    return (
      <div className={clsx('p-3 text-[11px] leading-relaxed text-muted', className)}>
        <div className="flex items-center gap-1.5 text-dim">
          <Radar size={13} /> No radar captures on disk yet.
        </div>
        <p className="mt-1.5">
          The live pipeline writes IMD Delhi DWR frames to {BASE}. Run a live refresh, or wait for
          the next 15-minute cycle, and the loop appears here. Nothing in this UI depends on it.
        </p>
      </div>
    )
  }

  return (
    <div className={clsx('flex h-full min-h-0 flex-col', className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-grid px-2.5 py-1.5">
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          disabled={frames.length < 2}
          className={clsx(
            'flex items-center gap-1 rounded border px-2 py-1 text-[10.5px] font-semibold',
            playing
              ? 'border-amber/50 bg-amber/15 text-amber'
              : 'border-teal/50 bg-teal/15 text-teal',
            frames.length < 2 && 'opacity-50',
          )}
        >
          {playing ? <Pause size={11} /> : <Play size={11} />}
          {playing ? 'Pause' : 'Play'}
        </button>

        {products.length > 1 && (
          <select
            value={product.key}
            onChange={(e) => setProductKey(e.target.value)}
            className="rounded border border-grid bg-bg px-1.5 py-1 text-[11px] text-ink outline-none focus:border-teal"
          >
            {products.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        )}

        <span className="tabular text-[10.5px] text-muted">
          {product.label} · frame <span className="text-ink">{at + 1}</span>
          /{frames.length}
          {frame?.stamp ? <span className="text-teal"> · {frame.stamp}</span> : null}
        </span>
      </div>

      <div
        className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden bg-bg"
        style={{ minHeight: height }}
      >
        {frame && !broken ? (
          <img
            src={frame.src}
            alt={`${product.label} capture ${frame.stamp || frame.captured_utc || ''}`}
            onError={() => setBrokenSrc(frame.src)}
            className="max-h-full max-w-full object-contain"
          />
        ) : (
          <div className="p-4 text-center text-[11px] text-muted">
            Capture file missing from disk ({frame?.src}).
          </div>
        )}
        {/* Scrub strip: one hit target per frame, same idiom as the replay
            scrubber so the gesture transfers. */}
        {frames.length > 1 && (
          <div className="absolute inset-x-2 bottom-2 flex gap-0.5">
            {frames.map((f, n) => (
              <button
                key={f.src}
                type="button"
                title={f.stamp || f.captured_utc || `frame ${n + 1}`}
                onClick={() => {
                  setPlaying(false)
                  setI(n)
                }}
                className={clsx(
                  'h-1.5 flex-1 rounded-sm transition-colors',
                  n === at ? 'bg-teal' : 'bg-ink/25 hover:bg-ink/50',
                )}
              />
            ))}
          </div>
        )}
      </div>

      {/* Verbatim from the manifest. If the pipeline ever drops the field we
          say the same thing in our own words rather than saying nothing. */}
      <div className="border-t border-grid px-2.5 py-1.5 text-[9.5px] leading-snug text-amber">
        {manifest?.disclaimer ||
          'Radar imagery is DISPLAYED, not decoded. No model in this system consumes these frames.'}
      </div>
    </div>
  )
}
