// The rain field, drawn as a FIELD.
//
// The nowcast/forecast grids arrive as a 0.1° lattice — 7 rows × 8 columns, 56
// points over Delhi NCR. Painting one translucent MapLibre `circle` per point
// is the obvious thing and it is what this used to do; at that spacing it reads
// as a mechanical dot matrix stamped over the city, not as weather, and the
// regularity of the grid is the first thing the eye locks onto.
//
// So the lattice is interpolated into a continuous surface here and handed to
// MapLibre as ONE georeferenced raster (an `image` source under a `raster`
// layer), which is the same thing every real precipitation product does.
//
// THE THREE RULES THIS FILE ENFORCES
//
//   1. COLOUR IS ABSOLUTE. A pixel's hue is the interpolated probability run
//      through the SAME ramp (MAP_THEME[theme].ramp) that paints the ward
//      choropleth and fills the legend swatch. Nothing is renormalised, so the
//      legend under the map still reads the raster correctly.
//
//   2. ALPHA IS RELATIVE, AND IT IS WHAT HIDES THE EMPTY CELLS. Where a field
//      carries no signal it must not paint at all — a wall of flat low-end blue
//      over all of Delhi buries the choropleth and says nothing. Opacity ramps
//      from fully transparent to fully painted across the upper part of THIS
//      field's own range, so quiet areas disappear and the wet corner shows.
//      The colour still tells you what the number is; the alpha only tells you
//      where to look.
//
//   3. NO NETWORK, NO DEPENDENCY. Canvas 2D, a data: URL, and arithmetic.
//
// Interpolation is a Gaussian kernel average (Nadaraya–Watson) at
// sigma = 0.42 × lattice spacing. That is deliberately narrow: wider is
// smoother but flattens the peak a fifth-of-a-cell-wide storm cell sits on, and
// this surface has to keep its maximum honest against the ramp. Inverse-distance
// weighting was the alternative and was rejected — it puts a visible bullseye on
// every one of the 56 nodes, which is the dot grid again by another route.

const PX_PER_CELL = 26 // raster resolution; ~230 × 180 px for the Delhi lattice
const SIGMA_CELLS = 0.42 // kernel width, in lattice cells
const DEFAULT_STEP = 0.1 // degrees, if a single-row/column grid hides the spacing

function clamp01(v) {
  return v < 0 ? 0 : v > 1 ? 1 : v
}

/** Hermite ease between two edges — a hard alpha cutoff shows its own contour. */
function smoothstep(lo, hi, v) {
  if (hi <= lo) return v >= hi ? 1 : 0
  const t = clamp01((v - lo) / (hi - lo))
  return t * t * (3 - 2 * t)
}

function hexToRgb(hex) {
  const s = String(hex).replace('#', '')
  const n =
    s.length === 3
      ? parseInt(s[0] + s[0] + s[1] + s[1] + s[2] + s[2], 16)
      : parseInt(s.slice(0, 6), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/**
 * The ramp, pre-resolved into a 256-entry lookup table.
 *
 * `ramp` is the flat [stop, colour, stop, colour, …] array MapLibre's
 * `interpolate` expression takes, so the table below and the map's own
 * expressions are literally reading the same numbers — the raster cannot drift
 * away from the choropleth or the legend.
 */
function rampLut(ramp) {
  const stops = []
  for (let i = 0; i < ramp.length; i += 2) stops.push([ramp[i], hexToRgb(ramp[i + 1])])
  stops.sort((a, b) => a[0] - b[0])
  const lut = new Uint8Array(256 * 3)
  for (let i = 0; i < 256; i += 1) {
    const v = i / 255
    let k = 0
    while (k < stops.length - 2 && v > stops[k + 1][0]) k += 1
    const [v0, c0] = stops[k]
    const [v1, c1] = stops[Math.min(k + 1, stops.length - 1)]
    const t = v1 === v0 ? 0 : clamp01((v - v0) / (v1 - v0))
    lut[i * 3] = c0[0] + (c1[0] - c0[0]) * t
    lut[i * 3 + 1] = c0[1] + (c1[1] - c0[1]) * t
    lut[i * 3 + 2] = c0[2] + (c1[2] - c0[2]) * t
  }
  return lut
}

/** Smallest positive gap in a sorted axis — the lattice spacing, measured. */
function spacingOf(values) {
  const uniq = [...new Set(values.map((v) => Math.round(v * 1e6) / 1e6))].sort((a, b) => a - b)
  let best = Infinity
  for (let i = 1; i < uniq.length; i += 1) {
    const d = uniq[i] - uniq[i - 1]
    if (d > 1e-6 && d < best) best = d
  }
  return Number.isFinite(best) ? best : null
}

/**
 * Build the raster for a rain grid.
 *
 * @param  points [{lat, lon, value}] — the lattice; `value` is 0..1
 * @param  ramp   MAP_THEME[theme].ramp
 * @return {url, coordinates, max} for a MapLibre `image` source, or null when
 *         there is nothing worth painting (no points, or an all-zero field —
 *         in which case drawing NOTHING is the correct, honest output).
 */
export function buildRainField(points, ramp) {
  if (!Array.isArray(points) || points.length < 3) return null
  if (typeof document === 'undefined') return null

  const lats = points.map((p) => p.lat)
  const lons = points.map((p) => p.lon)
  const step = spacingOf(lats) || spacingOf(lons) || DEFAULT_STEP
  const pad = step / 2

  const west = Math.min(...lons) - pad
  const east = Math.max(...lons) + pad
  const south = Math.min(...lats) - pad
  const north = Math.max(...lats) + pad
  const spanX = east - west
  const spanY = north - south
  if (!(spanX > 0) || !(spanY > 0)) return null

  let vmax = 0
  for (const p of points) {
    const v = Number(p.value)
    if (Number.isFinite(v) && v > vmax) vmax = v
  }
  // A field with no signal paints nothing rather than a uniform low-end wash.
  if (vmax < 0.005) return null

  const w = Math.max(48, Math.min(768, Math.round((spanX / step) * PX_PER_CELL)))
  const h = Math.max(48, Math.min(768, Math.round((spanY / step) * PX_PER_CELL)))

  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return null
  const img = ctx.createImageData(w, h)
  const buf = img.data

  // Longitude degrees are shorter than latitude degrees at 28.6°N; without this
  // the kernel is an ellipse and the field looks stretched east-west.
  const cosLat = Math.cos(((north + south) / 2) * (Math.PI / 180))
  const sigma = SIGMA_CELLS * step
  const twoSigma2 = 2 * sigma * sigma

  // Rule 2: where the alpha ramp starts and ends. The absolute floor keeps a
  // genuinely dry field dry; the relative term is what makes a low-amplitude
  // field still legible instead of a uniform faint smear.
  //
  // Tuned by measurement, not taste. Decoding the raster off a live grid:
  //   0.20 / 0.62 of vmax -> 96% of pixels painted. A faint wash over the whole
  //                          of Delhi, i.e. the thing this rewrite exists to
  //                          stop, just without the visible dots.
  //   0.34 / 0.74 of vmax -> 45% clear, 31% faint, 18% mid, 5% at full alpha.
  //                          The quiet third of the city disappears, the wet
  //                          corner is unmistakable, the choropleth reads
  //                          through everywhere else. That is the shape wanted.
  // The absolute floor is the second guard, for a field whose maximum is itself
  // near zero — the Forecast view's q90-vs-204.5 mm case. Kept low (0.012) so
  // such a field still shows WHERE its tail is rather than blanking entirely;
  // a field under 0.005 everywhere already returned null above.
  const lo = Math.max(0.012, 0.34 * vmax)
  const hi = Math.max(lo + 0.02, 0.74 * vmax)

  const lut = rampLut(ramp)
  const n = points.length
  const px = new Float64Array(n)
  const py = new Float64Array(n)
  const pv = new Float64Array(n)
  for (let i = 0; i < n; i += 1) {
    px[i] = points[i].lon * cosLat
    py[i] = points[i].lat
    const v = Number(points[i].value)
    pv[i] = Number.isFinite(v) ? v : 0
  }

  // Feather the raster's own edge so the AOI does not read as a hard rectangle
  // pasted over the city.
  const featherX = Math.max(4, (PX_PER_CELL * pad) / step)
  const featherY = featherX

  for (let y = 0; y < h; y += 1) {
    const lat = north - ((y + 0.5) / h) * spanY
    const fy = smoothstep(0, featherY, Math.min(y, h - 1 - y))
    for (let x = 0; x < w; x += 1) {
      const lon = (west + ((x + 0.5) / w) * spanX) * cosLat
      let wsum = 0
      let acc = 0
      for (let i = 0; i < n; i += 1) {
        const dx = lon - px[i]
        const dy = lat - py[i]
        const wgt = Math.exp(-(dx * dx + dy * dy) / twoSigma2)
        wsum += wgt
        acc += wgt * pv[i]
      }
      if (wsum <= 1e-12) continue
      const v = acc / wsum
      const a = smoothstep(lo, hi, v) * fy * smoothstep(0, featherX, Math.min(x, w - 1 - x))
      if (a <= 0.004) continue
      const c = Math.round(clamp01(v) * 255) * 3
      const o = (y * w + x) * 4
      buf[o] = lut[c]
      buf[o + 1] = lut[c + 1]
      buf[o + 2] = lut[c + 2]
      buf[o + 3] = Math.round(a * 255)
    }
  }

  ctx.putImageData(img, 0, 0)
  return {
    url: canvas.toDataURL('image/png'),
    // MapLibre image sources want the corners clockwise from top-left.
    coordinates: [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ],
    max: vmax,
  }
}
