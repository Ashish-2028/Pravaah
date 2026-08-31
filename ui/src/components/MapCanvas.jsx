import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Map as MapLibreMap, NavigationControl } from 'maplibre-gl'
import { BAND_COLOR, compact, pct } from '../lib/format'
import { TOGGLES, getPrefs, loadAll, loadedCount, peek, setPref } from '../lib/basemap'

// DO NOT call setWorkerUrl() here. It was tried and it silently breaks the map.
//
// maplibre-gl 6 spawns its worker as an ES MODULE:
//     new Worker(new URL('./maplibre-gl-worker.mjs', import.meta.url),
//                { type: 'module' })
// which Vite understands natively and emits correctly in both dev and build.
//
// setWorkerUrl() instead makes MapLibre construct a CLASSIC worker. The worker
// file is an ES module full of `import` statements, so a classic worker cannot
// parse it — and the failure is SILENT: no console error, no 'error' event.
// The symptom is a map that looks alive (source present, layers registered,
// correct bounds) but tiles zero features, so the canvas stays empty.
//
// Diagnostic if this ever regresses:
//     map.isStyleLoaded()               -> false, forever
//     map.querySourceFeatures('wards')  -> 0, while /api/wards returns 290

// A completely local style. No tile server, no sprite, no glyphs — which also
// means no symbol layers anywhere in this file. Airplane-mode safe by
// construction.
const BLANK_STYLE = {
  version: 8,
  sources: {},
  layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#0b1220' } }],
}

// Linear in probability so the legend stays honest, but bright enough at the
// low end that a 20% ward is still readable against the #0b1220 ground.
const RAMP = [
  0.0, '#17304d',
  0.25, '#0e7490',
  0.45, '#14b8a6',
  0.6, '#f59e0b',
  0.8, '#ef4444',
  1.0, '#ff6b6b',
]

function fillExpression(layer) {
  if (layer === 'exposure') {
    return [
      'interpolate',
      ['linear'],
      ['get', 'people'],
      0, '#17304d',
      20000, '#0e7490',
      45000, '#14b8a6',
      70000, '#f59e0b',
      100000, '#ef4444',
      150000, '#ff6b6b',
    ]
  }
  const prop = layer === 'risk_score' ? 'risk_score' : 'p_flood'
  return ['interpolate', ['linear'], ['get', prop], ...RAMP]
}

function bboxOf(fc) {
  let minX = 180
  let minY = 90
  let maxX = -180
  let maxY = -90
  const visit = (coords) => {
    if (typeof coords[0] === 'number') {
      const [x, y] = coords
      if (x < minX) minX = x
      if (x > maxX) maxX = x
      if (y < minY) minY = y
      if (y > maxY) maxY = y
      return
    }
    coords.forEach(visit)
  }
  fc.features.forEach((f) => f.geometry && f.geometry.coordinates && visit(f.geometry.coordinates))
  if (minX > maxX) return null
  return [
    [minX, minY],
    [maxX, maxY],
  ]
}

/**
 * MapLibre throws "Style is not done loading" for the frames between a
 * setData/addSource and the worker finishing its tiling pass. Every mutation
 * in this component is idempotent, so swallow the throw and reapply once the
 * map goes idle. Console stays clean; the paint still lands.
 */
function safe(map, fn) {
  try {
    fn()
  } catch {
    if (map && !map._removed) {
      map.once('idle', () => {
        try {
          fn()
        } catch {
          /* the next effect run will reapply it */
        }
      })
    }
  }
}

export default function MapCanvas({
  wards,
  layer = 'p_flood',
  selectedWard,
  onSelectWard,
  overlay = null,
  points = null, // optional [{lat, lon, value}] rain-grid cells
  pointLabel = 'P(>15 mm)',
  className = '',
}) {
  const container = useRef(null)
  const mapRef = useRef(null)
  const fitted = useRef(false)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState(null)

  // ---------------------------------------------------------------- init
  useEffect(() => {
    if (!container.current || mapRef.current) return undefined
    const map = new MapLibreMap({
      container: container.current,
      style: BLANK_STYLE,
      center: [77.1, 28.63],
      zoom: 9,
      attributionControl: false,
      maxZoom: 14,
      minZoom: 7,
      // Keeps the WebGL buffer readable so screen capture and screenshots of
      // the demo do not come out as an empty rectangle.
      preserveDrawingBuffer: true,
    })
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right')
    map.on('load', () => setReady(true))
    map.on('error', () => {
      /* swallowed: a blank style emits benign source warnings on teardown */
    })
    // Belt and braces: if the `load` event is ever missed we still go ready
    // once the style reports itself loaded, rather than showing a dead canvas.
    const poll = setInterval(() => {
      if (mapRef.current && mapRef.current.isStyleLoaded()) {
        setReady(true)
        clearInterval(poll)
      }
    }, 200)
    // MapLibre's own trackResize did not pick up the panel's final height in
    // this layout, which left a short canvas and a mostly empty map. Observe
    // the container ourselves and resize on every change.
    const ro = new ResizeObserver(() => {
      if (mapRef.current) mapRef.current.resize()
    })
    ro.observe(container.current)

    mapRef.current = map
    // Debug handle — lets anyone poke the live map from the console during the
    // demo without a React devtools install.
    window.__pravaahMap = map
    return () => {
      ro.disconnect()
      clearInterval(poll)
      map.remove()
      mapRef.current = null
      setReady(false)
      fitted.current = false
    }
  }, [])

  // --------------------------------------------------- ward source + layers
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !wards) return
    const data = wards

    if (!map.getSource('wards')) {
      safe(map, () => {
        map.addSource('wards', { type: 'geojson', data })
        map.addLayer({
          id: 'wards-fill',
          type: 'fill',
          source: 'wards',
          paint: { 'fill-color': fillExpression(layer), 'fill-opacity': 0.82 },
        })
        map.addLayer({
          id: 'wards-line',
          type: 'line',
          source: 'wards',
          paint: { 'line-color': '#1f2b40', 'line-width': 0.6, 'line-opacity': 0.9 },
        })
        map.addLayer({
          id: 'wards-critical',
          type: 'line',
          source: 'wards',
          filter: ['==', ['get', 'risk_band'], 'critical'],
          paint: { 'line-color': '#ef4444', 'line-width': 2, 'line-opacity': 0.9 },
        })
        map.addLayer({
          id: 'wards-selected',
          type: 'line',
          source: 'wards',
          filter: ['==', ['get', 'ward_id'], '__none__'],
          paint: { 'line-color': '#e5edf7', 'line-width': 2.4 },
        })
      })

      map.on('mousemove', 'wards-fill', (e) => {
        map.getCanvas().style.cursor = 'pointer'
        const f = e.features && e.features[0]
        if (f) setHover({ props: f.properties, x: e.point.x, y: e.point.y })
      })
      map.on('mouseleave', 'wards-fill', () => {
        map.getCanvas().style.cursor = ''
        setHover(null)
      })
    } else {
      safe(map, () => map.getSource('wards').setData(data))
    }

    if (!fitted.current) {
      const bounds = bboxOf(data)
      if (bounds) {
        safe(map, () => map.fitBounds(bounds, { padding: 36, duration: 0 }))
        fitted.current = true
      }
    }
  }, [ready, wards, layer])

  // repaint on layer switch
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !map.getLayer('wards-fill')) return
    safe(map, () => map.setPaintProperty('wards-fill', 'fill-color', fillExpression(layer)))
  }, [ready, layer])

  // selection outline
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !map.getLayer('wards-selected')) return
    safe(map, () =>
      map.setFilter('wards-selected', ['==', ['get', 'ward_id'], selectedWard || '__none__']),
    )
  }, [ready, selectedWard])

  // click -> select
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return undefined
    const handler = (e) => {
      const f = e.features && e.features[0]
      if (f && onSelectWard) onSelectWard(f.properties.ward_id)
    }
    map.on('click', 'wards-fill', handler)
    return () => map.off('click', 'wards-fill', handler)
  }, [ready, onSelectWard])

  // critical-ward glow pulse
  useEffect(() => {
    if (!ready) return undefined
    const id = setInterval(() => {
      const map = mapRef.current
      if (!map || !map.getLayer('wards-critical') || !map.isStyleLoaded()) return
      const phase = 0.45 + 0.45 * (1 + Math.sin(Date.now() / 420)) * 0.5
      try {
        map.setPaintProperty('wards-critical', 'line-opacity', phase)
      } catch {
        /* style busy this frame — the pulse simply skips a beat */
      }
    }, 90)
    return () => clearInterval(id)
  }, [ready])

  // optional rain-grid point overlay
  const pointData = useMemo(() => {
    if (!points) return null
    return {
      type: 'FeatureCollection',
      features: points.map((p) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [p.lon, p.lat] },
        properties: { value: p.value },
      })),
    }
  }, [points])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    if (!pointData) {
      safe(map, () => {
        if (map.getLayer('rain-cells')) map.removeLayer('rain-cells')
        if (map.getSource('rain')) map.removeSource('rain')
      })
      return
    }
    if (!map.getSource('rain')) {
      safe(map, () => {
        map.addSource('rain', { type: 'geojson', data: pointData })
        map.addLayer({
          id: 'rain-cells',
          type: 'circle',
          source: 'rain',
          paint: {
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 6, 12, 22],
            'circle-color': ['interpolate', ['linear'], ['get', 'value'], ...RAMP],
            'circle-opacity': 0.55,
            'circle-stroke-width': 0.5,
            'circle-stroke-color': '#0b1220',
          },
        })
      })
    } else {
      safe(map, () => map.getSource('rain').setData(pointData))
    }
  }, [ready, pointData])

  const hoverBand = hover ? BAND_COLOR[hover.props.risk_band] || '#8ba0bd' : null

  return (
    <div className={`absolute inset-0 ${className}`}>
      <div ref={container} className="h-full w-full" />
      {!ready && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center text-sm text-muted">
          Initialising map canvas…
        </div>
      )}

      {hover && (
        <div
          className="pointer-events-none absolute z-20 w-56 rounded-md border border-grid bg-panel/95 p-2.5 shadow-xl"
          style={{
            left: Math.min(hover.x + 14, (container.current?.clientWidth || 600) - 240),
            top: Math.min(hover.y + 14, (container.current?.clientHeight || 400) - 150),
          }}
        >
          <div className="truncate text-xs font-semibold text-ink">{hover.props.name}</div>
          <div className="mt-0.5 text-[10px] uppercase tracking-wider" style={{ color: hoverBand }}>
            {hover.props.risk_band} · {hover.props.ward_id}
          </div>
          <dl className="mt-2 space-y-1 text-[11px]">
            <div className="flex justify-between">
              <dt className="text-muted">P(flood)</dt>
              <dd className="tabular text-ink">{pct(hover.props.p_flood)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Risk score</dt>
              <dd className="tabular text-ink">{pct(hover.props.risk_score)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">People</dt>
              <dd className="tabular text-ink">{compact(hover.props.people)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-muted">Onset</dt>
              <dd className="tabular text-ink">{hover.props.onset || 'none'}</dd>
            </div>
          </dl>
        </div>
      )}

      {overlay}

      <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-md border border-grid bg-panel/90 px-2.5 py-2">
        <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted">
          {points ? pointLabel : layer === 'exposure' ? 'People exposed' : 'Probability'}
        </div>
        <div
          className="mt-1.5 h-2 w-40 rounded"
          style={{
            background:
              'linear-gradient(90deg,#17304d 0%,#0e7490 25%,#14b8a6 45%,#f59e0b 60%,#ef4444 80%,#ff6b6b 100%)',
          }}
        />
        <div className="tabular mt-1 flex justify-between text-[9px] text-muted">
          {layer === 'exposure' && !points ? (
            <>
              <span>0</span>
              <span>75 K</span>
              <span>150 K</span>
            </>
          ) : (
            <>
              <span>0%</span>
              <span>50%</span>
              <span>100%</span>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
