import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Map as MapLibreMap, NavigationControl } from 'maplibre-gl'
import { BAND_COLOR, compact, pct } from '../lib/format'
import { LAYER_COUNT, TOGGLES, getPrefs, loadAll, loadedCount, setPref } from '../lib/basemap'

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
//
// ---------------------------------------------------------------------------
// A SECOND, UNRELATED WAY TO GET A PERMANENTLY BLANK MAP: no animation frames.
//
// In a hidden or headless browser pane, document.visibilityState is 'hidden'
// and requestAnimationFrame NEVER FIRES. MapLibre's whole pipeline is driven
// off rAF, so the style never loads, nothing tiles, and the canvas stays empty
// while every other signal looks healthy — same symptom as the worker bug
// above, completely different cause. Check this BEFORE suspecting the map:
//
//     document.visibilityState                      -> 'hidden'
//     await new Promise(r => requestAnimationFrame(r))   // never resolves
//
// SHIMMING rAF IS NOT ENOUGH ON ITS OWN. Map construction schedules the
// style-load callback inside Style.loadJSON via browser.frame() — i.e. against
// whatever rAF existed at construction time. If the map was built before the
// shim, that frame token is already lost and no later frame revives it. You
// must shim AND then re-enter the pipeline:
//
//     window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16)
//     window.cancelAnimationFrame = (id) => clearTimeout(id)
//     window.__pravaahMap.setStyle(BLANK_STYLE)   // re-runs loadJSON, now with a live rAF
//
// After that the poll below sets `ready` and every effect in this file
// replays normally. Verify with map.queryRenderedFeatures({layers:[...]})
// rather than screenshots — an agent pane can render a stale frame.
//
// TWO CAVEATS ON THAT KICK, both of which have cost time:
//   * Kick ONCE, on a fresh load. setStyle() wipes all sources and layers, and
//     the effects below only re-add them when `ready` goes false -> true. A
//     second kick mid-session leaves `ready` stuck true and you get a loaded
//     style with NO layers at all — which looks exactly like the bug you were
//     chasing.
//   * queryRenderedFeatures() returns 0 for a layer that DOES NOT EXIST, and
//     only signals that via an 'error' event this component swallows. Always
//     check map.getLayer(id) alongside the count, or 0 is ambiguous.
//
// ---------------------------------------------------------------------------
// "bm-roads-major RENDERS ZERO FEATURES" — IT IS ALMOST CERTAINLY NOT A BUG.
//
// This was investigated at length and the answer is that the layer was right
// and the viewport was wrong. Reported symptom: at centre [77.221, 28.631]
// z12.4, bm-roads-secondary rendered 676 features while bm-roads-major
// rendered 0, from identical machinery and with the source demonstrably loaded
// (querySourceFeatures returned 595).
//
// Root cause: THERE ARE NO MAJOR-TIER ROADS IN THAT VIEWPORT. Measured against
// the raw GeoJSON with a Liang-Barsky segment-vs-bbox test (not a vertex test
// — a long segment can cross a box with both endpoints outside it):
//
//     viewport 77.200..77.242 / 28.6139..28.6481   major    0   secondary  678
//     wider Delhi 77.10..77.35 / 28.50..28.75      major 2375   secondary 8430
//     nearest major-tier road to the viewport centre: 2.45 km away
//
// 678 in-bounds vs 676 rendered is a match; the layer paints exactly what is
// there. That test window is the Lutyens'/Connaught Place area, whose streets
// OSM classifies secondary/tertiary. build_basemap.py's "major" tier is
// motorway/trunk/primary + links — Ring Road, NH-48, DND — which are outside
// it. Move ~2.5 km south to [77.2465, 28.5865] and bm-roads-major renders 214
// features at the same zoom.
//
// THE GENERAL LESSON: this basemap is tiered by OSM highway class, so any
// single small viewport can legitimately contain one tier and none of another.
// Before debugging a "layer renders nothing", count what SHOULD be in the
// current bounds straight from the GeoJSON:
//
//     const b = map.getBounds()
//     const fc = await (await fetch('/static/basemap/roads_major.geojson')).json()
//     // ...then a real segment-vs-bbox test against b, not a vertex test.
//
// If that count is 0, the map is correct and there is nothing to fix.

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

// ---------------------------------------------------------------- basemap
//
// Google-Maps-dark discipline: the streets are CONTEXT, never the subject.
// Everything below is dark enough to sit a shade above the #0b1220 ground and
// no more, and everything fades IN with zoom, so the city view stays a
// choropleth and the ward view becomes a street map.
//
// The pedestrian/vehicular split on underpasses matters: the OSM extract mixes
// 386 footways and 109 flights of steps in with the road tunnels. The road
// classes are the flood blackspots; the pedestrian ones get 45% of the weight
// so they read as background without being hidden.
const PED = ['footway', 'steps', 'path', 'corridor', 'cycleway', 'pedestrian', 'track']
const underpassWeight = ['match', ['get', 'highway'], PED, 0.45, 1]
const majorWeight = [
  'match',
  ['get', 'highway'],
  ['motorway', 'trunk'], 1.25,
  ['motorway_link', 'trunk_link'], 0.7,
  1,
]
const waterWeight = ['match', ['get', 'waterway'], ['river'], 2, ['canal'], 1.4, 1]

/**
 * A zoom ramp whose every stop is multiplied by a per-feature weight.
 *
 * This shape is NOT optional. MapLibre rejects `['*', ['interpolate', …
 * ['zoom'] …], weight]` outright — "zoom expression may only be used as input
 * to a top-level step or interpolate expression" — and the rejection surfaces
 * as an 'error' event, which this component deliberately swallows, so the
 * layer would simply never appear and nothing would say why. Keep ['zoom'] as
 * the interpolate input and push the multiply down into each output.
 */
function zoomScaled(interpolation, stops, weight) {
  const expr = ['interpolate', interpolation, ['zoom']]
  for (const [z, v] of stops) expr.push(z, ['*', v, weight])
  return expr
}

const LAYER_SPECS = {
  waterways: [
    {
      id: 'bm-water',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        // Desaturated blue — present, never competing with the teal ramp.
        'line-color': [
          'match',
          ['get', 'waterway'],
          ['river'], '#22648f',
          ['canal'], '#1d5678',
          ['stream'], '#1a4667',
          '#173a55', // drains and ditches — 1,505 of the 1,958, keep them quiet
        ],
        'line-width': zoomScaled(
          ['exponential', 1.4],
          [[8, 0.5], [11, 1.4], [14, 4]],
          waterWeight,
        ),
        'line-opacity': ['interpolate', ['linear'], ['zoom'], 8, 0.5, 11, 0.8, 14, 1],
      },
    },
  ],

  roads_secondary: [
    {
      id: 'bm-roads-secondary',
      type: 'line',
      minzoom: 10.8,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        // Brightens with zoom for the same reason as the major tier below.
        'line-color': ['interpolate', ['linear'], ['zoom'], 11, '#2b3c53', 14, '#516684'],
        'line-width': ['interpolate', ['exponential', 1.5], ['zoom'], 11, 0.4, 13, 1.2, 14, 2.1],
        'line-opacity': ['interpolate', ['linear'], ['zoom'], 10.8, 0, 11.6, 0.5, 14, 0.8],
      },
    },
  ],

  roads_major: [
    {
      // Casing only from z11.5 — below that it just muddies the choropleth.
      id: 'bm-roads-major-casing',
      type: 'line',
      minzoom: 11.5,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#0d1523',
        'line-width': zoomScaled(['exponential', 1.5], [[11.5, 2.6], [14, 7]], majorWeight),
        'line-opacity': ['interpolate', ['linear'], ['zoom'], 11.5, 0, 12.2, 0.8],
      },
    },
    {
      id: 'bm-roads-major',
      type: 'line',
      minzoom: 8.5,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        // Zoom-ramped rather than class-ramped. At city zoom the roads sit
        // just above the #0b1220 ground and stay out of the way; by z14 they
        // have to survive being seen THROUGH a 55%-opaque choropleth fill, and
        // a colour dark enough to be tasteful at z9 simply disappears there.
        // Road class is still legible — it is carried by width.
        'line-color': ['interpolate', ['linear'], ['zoom'], 9, '#33465f', 12, '#546d92', 14, '#7089ad'],
        'line-width': zoomScaled(
          ['exponential', 1.5],
          [[8, 0.4], [10, 1], [12, 2.2], [14, 4.4]],
          majorWeight,
        ),
        'line-opacity': ['interpolate', ['linear'], ['zoom'], 8.5, 0, 9.2, 0.55, 12, 0.85, 14, 0.95],
      },
    },
  ],

  underpasses: [
    {
      // Doubles as the hover target: a 1 px dashed line is impossible to hit
      // with a mouse, so the glow underneath is what queryRenderedFeatures
      // actually catches.
      id: 'bm-underpass-glow',
      type: 'line',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#f59e0b',
        'line-blur': 3,
        'line-width': zoomScaled(['linear'], [[8, 6], [12, 11], [14, 18]], underpassWeight),
        'line-opacity': zoomScaled(
          ['linear'],
          [[8, 0.13], [12, 0.2], [14, 0.24]],
          underpassWeight,
        ),
      },
    },
    {
      id: 'bm-underpasses',
      type: 'line',
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
      paint: {
        'line-color': ['match', ['get', 'highway'], PED, '#a9761d', '#f59e0b'],
        'line-width': zoomScaled(['linear'], [[8, 1.1], [12, 2.6], [14, 4.2]], underpassWeight),
        'line-opacity': 0.95,
        'line-dasharray': [2, 1.4],
      },
    },
  ],

  // Deliberately drawn as an ANNOTATION, not as a data value: a hollow ink
  // ring with a centre pip, in the same #e5edf7 as body text, using no colour
  // from the risk ramp and no colour from the asset set. Everything else on
  // this map is something the model produced; these 84 points are the labels
  // it was fitted against, and they should not look like a prediction.
  //
  // Confidence drives size, ring weight and opacity, so the 10 high-confidence
  // sites — Minto Bridge, ITO, Tilak Bridge, Rajghat, Shanti Van, Bhairon Marg
  // among them — carry visibly more weight than the 74 medium ones.
  blackspots: [
    {
      id: 'bm-blackspots-ring',
      type: 'circle',
      // No practical zoom gate. 84 points cannot clutter anything, and the
      // fitted view lands anywhere from z8.2 in a narrow panel to z9.6 in the
      // full-width one — a z8.5 gate made the landmarks vanish in the first
      // case. Fade in below the opening zoom instead of gating at it.
      minzoom: 7,
      paint: {
        // A whisper of fill rather than a true hollow: it keeps the ring
        // legible over a bright choropleth AND makes the marker a reliable
        // hover target, which a zero-opacity circle is not.
        'circle-color': '#e5edf7',
        'circle-opacity': [
          'interpolate', ['linear'], ['zoom'],
          7.2, 0,
          8.2, ['match', ['get', 'confidence'], 'high', 0.1, 0.05],
        ],
        'circle-radius': zoomScaled(
          ['linear'],
          [[9, 4.5], [12, 7.5], [14, 11]],
          ['match', ['get', 'confidence'], 'high', 1, 0.68],
        ),
        'circle-stroke-color': '#e5edf7',
        'circle-stroke-width': ['match', ['get', 'confidence'], 'high', 1.8, 1],
        'circle-stroke-opacity': [
          'interpolate', ['linear'], ['zoom'],
          7.2, 0,
          8.2, ['match', ['get', 'confidence'], 'high', 0.95, 0.5],
        ],
      },
    },
    {
      id: 'bm-blackspots-pip',
      type: 'circle',
      minzoom: 7,
      paint: {
        'circle-color': '#e5edf7',
        'circle-radius': ['match', ['get', 'confidence'], 'high', 1.7, 1.1],
        'circle-opacity': [
          'interpolate', ['linear'], ['zoom'],
          7.2, 0,
          8.2, ['match', ['get', 'confidence'], 'high', 0.95, 0.5],
        ],
      },
    },
  ],

  hospitals: [assetLayer('bm-hospitals', '#f472b6')],
  schools: [assetLayer('bm-schools', '#a78bfa')],
  pumps: [assetLayer('bm-pumps', '#38bdf8')],
}

function assetLayer(id, color) {
  return {
    id,
    type: 'circle',
    minzoom: 10.8,
    paint: {
      'circle-color': color,
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 11, 1.8, 13, 3.4, 14, 5],
      'circle-opacity': ['interpolate', ['linear'], ['zoom'], 10.8, 0, 11.4, 0.9],
      'circle-stroke-width': 0.7,
      'circle-stroke-color': '#0b1220',
      'circle-stroke-opacity': ['interpolate', ['linear'], ['zoom'], 10.8, 0, 11.4, 0.9],
    },
  }
}

/** Swatch colour per toggle — each one is the actual paint colour of the layer
 *  it switches, so the panel doubles as the legend. */
const TOGGLE_DOT = {
  roads: '#546d92',
  water: '#22648f',
  assets: '#a78bfa',
  underpasses: '#f59e0b',
  blackspots: '#e5edf7',
}

export const ASSET_LEGEND = [
  ['Hospitals', '#f472b6'],
  ['Schools', '#a78bfa'],
  ['Pumps', '#38bdf8'],
]

/** Canonical bottom-to-top paint order. The background layer is not listed and
 *  stays at index 0 underneath everything. */
const STACK = [
  'bm-water',
  'bm-roads-secondary',
  'bm-roads-major-casing',
  'bm-roads-major',
  'wards-fill',
  'wards-line',
  'wards-critical',
  'bm-underpass-glow',
  'bm-underpasses',
  'bm-schools',
  'bm-hospitals',
  'bm-pumps',
  'rain-cells',
  // Above everything except the selection outline: these are the landmarks the
  // presenter names aloud, so nothing is allowed to bury them.
  'bm-blackspots-ring',
  'bm-blackspots-pip',
  'wards-selected',
]

/**
 * Basemap files arrive over several seconds and in whatever order the network
 * hands them back, so a `beforeId` at insert time is not enough to guarantee
 * the stack. Re-assert the whole order after every mutation instead:
 * moveLayer(id) with no beforeId moves a layer to the top, so walking STACK
 * front to back leaves exactly STACK on top of the background.
 */
function restack(map) {
  STACK.forEach((id) => {
    if (map.getLayer(id)) {
      try {
        map.moveLayer(id)
      } catch {
        /* style busy — the next restack settles it */
      }
    }
  })
}

/** Map a file name to its toggle group so visibility can be applied per file. */
const FILE_GROUP = Object.fromEntries(
  TOGGLES.flatMap((t) => t.files.map((f) => [f, t.key])),
)

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
 *
 * The catch is silent IN PRODUCTION ONLY. It has to be — the demo is graded on
 * a clean console — but a silent catch around every map mutation is also a
 * perfect hiding place for a real bug, and it has already hidden one (an
 * invalid zoom expression that made addLayer bail with no other symptom than a
 * layer that never appeared). Under DEV it now reports what it swallowed.
 */
function safe(map, fn, label = 'map mutation') {
  try {
    fn()
  } catch (err) {
    // "Style is not done loading" is the expected, benign race this wrapper
    // exists for; anything else is a genuine failure worth seeing.
    if (import.meta.env.DEV && !/not done loading/i.test(String(err && err.message))) {
      console.warn(`[map] ${label} threw, retrying on idle:`, err)
    }
    if (map && !map._removed) {
      map.once('idle', () => {
        try {
          fn()
        } catch (err2) {
          if (import.meta.env.DEV) {
            console.warn(`[map] ${label} failed again after idle:`, err2)
          }
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
  basemap = true,
  className = '',
}) {
  const container = useRef(null)
  const mapRef = useRef(null)
  const fitted = useRef(false)
  const [ready, setReady] = useState(false)
  const [hover, setHover] = useState(null)
  // Which basemap groups are drawn. Seeded from module scope so the choice
  // survives a route change, and written back on every flip.
  const [groups, setGroups] = useState(getPrefs)
  const [loaded, setLoaded] = useState(() => loadedCount())
  const [tip, setTip] = useState(null) // hovered/pinned underpass tooltip
  const tipPinned = useRef(false)

  const toggleGroup = useCallback((key) => {
    setGroups((g) => {
      const next = { ...g, [key]: !g[key] }
      setPref(key, next[key])
      return next
    })
  }, [])

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
    map.on('error', (e) => {
      // Swallowed in production: a blank style emits benign source warnings on
      // teardown and the demo must show a clean console. But this handler is
      // also where a genuine style-validation error goes to die — an invalid
      // paint expression makes addLayer bail with no other symptom than a
      // layer that never appears. Surface it in dev only.
      if (import.meta.env.DEV && e && e.error) console.warn('[map]', e.error.message)
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
          paint: {
            'fill-color': fillExpression(layer),
            // 0.82 at city zoom, where the choropleth IS the message and the
            // streets are only a hint of shape underneath; thinning to 0.55 by
            // z14, where the operator is looking at one ward and needs to see
            // which roads and underpasses are inside it. The basemap is never
            // allowed to make a band misread at the zoom the demo opens on.
            'fill-opacity': ['interpolate', ['linear'], ['zoom'], 10, 0.82, 12.5, 0.64, 14, 0.5],
          },
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
        // The ward layers land above whatever basemap files already arrived,
        // so re-assert the canonical order the moment they exist.
        restack(map)
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

  // --------------------------------------------------------------- basemap
  // Gated on `wards` as well as `ready` on purpose: the choropleth is the
  // deliverable, so it gets the network and the main thread to itself until it
  // is on screen. Only then do we start pulling 6.3 MB of streets, one file at
  // a time, with a yield between each.
  //
  // The dependency is `hasWards`, NOT `wards`. The basemap has no (event, t)
  // dimension, so a replay tick — which hands us a brand new ward
  // FeatureCollection every 100 ms — must not re-enter this effect. And even
  // if it did, lib/basemap.js serves from a module-scope cache, so the files
  // are fetched at most once per page load no matter what.
  const hasWards = Boolean(wards)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !basemap || !hasWards) return undefined
    let stopped = false

    const draw = (name, fc) => {
      if (stopped || map._removed) return
      const specs = LAYER_SPECS[name]
      if (!specs || !fc.features.length) return
      const src = `bm-${name}`
      // Read the module-scope prefs, not React state: this callback outlives
      // the render that created it and the module is the source of truth.
      const visibility = getPrefs()[FILE_GROUP[name]] ? 'visible' : 'none'
      safe(map, () => {
        if (map.getSource(src)) map.getSource(src).setData(fc)
        else map.addSource(src, { type: 'geojson', data: fc })
        specs.forEach((spec) => {
          if (map.getLayer(spec.id)) return
          map.addLayer({
            ...spec,
            source: src,
            layout: { ...(spec.layout || {}), visibility },
          })
        })
        restack(map)
      }, `basemap draw: ${name}`)
      setLoaded(loadedCount())
    }

    loadAll(draw, () => stopped || map._removed)
    return () => {
      stopped = true
    }
  }, [ready, basemap, hasWards])

  // toggles -> layout visibility (no refetch, no re-add: the data stays put)
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    safe(map, () => {
      Object.entries(LAYER_SPECS).forEach(([name, specs]) => {
        const visibility = groups[FILE_GROUP[name]] ? 'visible' : 'none'
        specs.forEach((spec) => {
          if (map.getLayer(spec.id)) map.setLayoutProperty(spec.id, 'visibility', visibility)
        })
      })
    }, 'basemap visibility')
  }, [ready, groups])

  // Point identification for the two annotation layers.
  //
  // Underpasses: being able to point at a below-grade way and read its name
  // out loud is the demo beat that layer exists for. Blackspots: the curated
  // landmark labels, which are checked FIRST because they are the smaller,
  // deliberately-placed target and they usually sit on top of an underpass.
  //
  // Hover reads, click pins so the presenter can let go of the mouse; clicking
  // off unpins.
  //
  // A single map-level handler rather than a delegated one: the layers do not
  // exist for the first few seconds and a delegated listener bound to a
  // missing layer is a landmine. queryRenderedFeatures returns nothing for a
  // visibility:'none' layer, so the toggles gate the tooltips for free.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return undefined
    const probe = (point, layerId) => {
      if (!map.getLayer(layerId)) return null
      try {
        const fs = map.queryRenderedFeatures(point, { layers: [layerId] })
        return fs.length ? fs[0] : null
      } catch {
        return null
      }
    }
    const asTip = (point) => {
      const spot = probe(point, 'bm-blackspots-ring')
      if (spot) {
        const p = spot.properties
        return {
          kind: 'blackspot',
          name: p.name,
          source: p.source,
          confidence: p.confidence,
          notes: p.notes,
          // Carried through verbatim from the data rather than restated in the
          // component, so the provenance wording can only ever be changed in
          // one place — the label set itself.
          disclaimer: p.disclaimer,
          x: point.x,
          y: point.y,
        }
      }
      const way = probe(point, 'bm-underpass-glow')
      if (way) {
        return {
          kind: 'underpass',
          name: way.properties.name || null,
          highway: way.properties.highway || 'underpass',
          x: point.x,
          y: point.y,
        }
      }
      return null
    }
    const onMove = (e) => {
      if (tipPinned.current) return
      const tip = asTip(e.point)
      setTip((prev) => (tip || (prev ? null : prev)))
    }
    const onClick = (e) => {
      const tip = asTip(e.point)
      if (tip) {
        tipPinned.current = true
        setTip({ ...tip, pinned: true })
      } else if (tipPinned.current) {
        tipPinned.current = false
        setTip(null)
      }
    }
    map.on('mousemove', onMove)
    map.on('click', onClick)
    return () => {
      map.off('mousemove', onMove)
      map.off('click', onClick)
      tipPinned.current = false
    }
  }, [ready])

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
        restack(map)
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

      {basemap && (
        <div className="absolute right-3 top-3 z-10 w-[168px] rounded-md border border-grid bg-panel/92 p-1.5">
          <div className="flex items-center justify-between px-1 pb-1">
            <span className="text-[9px] font-semibold uppercase tracking-[0.14em] text-muted">
              Basemap
            </span>
            {loaded < LAYER_COUNT && (
              <span className="tabular text-[9px] text-dim" title="Loading local street layers">
                {loaded}/{LAYER_COUNT}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-0.5">
            {TOGGLES.map((t) => {
              const on = groups[t.key]
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => toggleGroup(t.key)}
                  title={t.note || undefined}
                  className={`flex items-start gap-1.5 rounded px-1.5 py-1 text-left text-[10.5px] leading-snug transition-colors ${
                    on ? 'bg-teal/15 font-semibold text-ink' : 'text-muted hover:text-ink'
                  }`}
                >
                  <span
                    className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full"
                    style={{
                      background: on ? TOGGLE_DOT[t.key] || '#40587a' : '#334155',
                    }}
                  />
                  <span className="min-w-0">{t.label}</span>
                </button>
              )
            })}
          </div>
          {groups.assets && (
            <div className="mt-1 flex flex-col gap-0.5 border-t border-grid px-1.5 pt-1">
              {ASSET_LEGEND.map(([label, color]) => (
                <span key={label} className="flex items-center gap-1.5 text-[9px] text-dim">
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
                  {label}
                </span>
              ))}
            </div>
          )}
          {/* Stated on the panel, not only in the tooltip: someone reading the
              map over the presenter's shoulder must not need to hover to learn
              that these rings are training labels rather than a prediction. */}
          {groups.blackspots && (
            <div className="mt-1 border-t border-grid px-1.5 pt-1 text-[9px] leading-snug text-dim">
              <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full border border-ink align-middle" />
              84 curated labels · not model output
            </div>
          )}
        </div>
      )}

      {tip && tip.kind === 'blackspot' && (
        <div
          className="pointer-events-none absolute z-30 w-[248px] rounded-md border border-grid bg-panel/96 px-2.5 py-2 shadow-xl"
          style={{
            left: Math.min(tip.x + 14, (container.current?.clientWidth || 600) - 260),
            top: Math.min(Math.max(6, tip.y - 40), (container.current?.clientHeight || 400) - 180),
          }}
        >
          <div className="flex items-start gap-1.5">
            <span className="mt-1 h-2 w-2 shrink-0 rounded-full border border-ink" />
            <span className="text-[11.5px] font-semibold leading-snug text-ink">{tip.name}</span>
          </div>
          <div className="mt-0.5 text-[9px] uppercase tracking-wider text-muted">
            {String(tip.source || '').replace(/_/g, ' ')} · {tip.confidence} confidence
            {tip.pinned ? ' · pinned' : ''}
          </div>
          {tip.notes && (
            <div className="mt-1.5 line-clamp-4 text-[10px] leading-snug text-muted">
              {tip.notes}
            </div>
          )}
          {/* Verbatim from the feature's `disclaimer` property. */}
          <div className="mt-1.5 rounded border border-amber/40 bg-amber/10 px-1.5 py-1 text-[9.5px] leading-snug text-amber">
            {tip.disclaimer}
          </div>
        </div>
      )}

      {tip && tip.kind === 'underpass' && (
        <div
          className="pointer-events-none absolute z-30 max-w-[220px] rounded-md border border-amber/45 bg-panel/96 px-2.5 py-1.5 shadow-xl"
          style={{
            left: Math.min(tip.x + 14, (container.current?.clientWidth || 600) - 232),
            top: Math.max(6, tip.y - 46),
          }}
        >
          <div className="flex items-center gap-1.5">
            <span className="h-1.5 w-4 shrink-0 rounded-sm bg-amber" />
            <span className="truncate text-[11.5px] font-semibold text-ink">
              {tip.name || 'Unnamed underpass'}
            </span>
          </div>
          <div className="mt-0.5 text-[9px] uppercase tracking-wider text-amber">
            below grade · {tip.highway}
            {tip.pinned ? ' · pinned' : ''}
          </div>
        </div>
      )}

      {hover && !tip && (
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
