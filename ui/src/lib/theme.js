// PRAVAAH theming.
//
// ONE VARIABLE SWAP. Every colour the DOM uses is a Tailwind v4 `@theme`
// custom property (see index.css), so a theme is nothing but a different set
// of values for the same names, applied by stamping `data-theme` on <html>.
// No component reads a theme name to pick a colour, and there are no
// `dark:`/`light:` variants anywhere.
//
// The MAP is the exception that has to be handled explicitly: MapLibre paint
// properties are JSON values inside a WebGL style, not CSS, so they cannot
// read a custom property. MAP_THEME below is the map's copy of the palette and
// MapCanvas re-applies it on every theme change.
//
// Default is DARK: this is a control-room screen. LIGHT exists for projectors
// that wash out dark backgrounds, which is a real failure mode in a demo hall.

import { create } from 'zustand'

const KEY = 'pravaah.theme'

export const THEMES = ['dark', 'light']

function initial() {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    /* private mode / storage disabled — fall through to the default */
  }
  return 'dark'
}

/** Stamp the document. Called at module load so there is no flash of the
 *  wrong theme before React mounts. */
export function applyTheme(theme) {
  const root = document.documentElement
  root.dataset.theme = theme
  root.style.colorScheme = theme
  const meta = document.querySelector('meta[name="color-scheme"]')
  if (meta) meta.setAttribute('content', theme)
}

export const useTheme = create((set, get) => ({
  theme: initial(),
  setTheme: (theme) => {
    applyTheme(theme)
    try {
      localStorage.setItem(KEY, theme)
    } catch {
      /* the choice simply will not survive a reload */
    }
    set({ theme })
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}))

applyTheme(useTheme.getState().theme)

// ---------------------------------------------------------------- map palette
//
// Keys are semantic, not literal colours, so the two variants stay in step.
// The risk RAMP keeps the same hue progression in both themes — blue → teal →
// amber → red — because the legend is read the same way on either ground; only
// the luminance is retuned so the low end is visible against the page.

export const MAP_THEME = {
  dark: {
    ground: '#0b1220',
    wardLine: '#1f2b40',
    wardSelected: '#e5edf7',
    wardCritical: '#ef4444',
    roadMajorLow: '#33465f',
    roadMajorMid: '#546d92',
    roadMajorHigh: '#7089ad',
    roadCasing: '#0d1523',
    roadSecondaryLow: '#2b3c53',
    roadSecondaryHigh: '#516684',
    river: '#22648f',
    canal: '#1d5678',
    stream: '#1a4667',
    drain: '#173a55',
    underpass: '#f59e0b',
    underpassPed: '#a9761d',
    blackspot: '#e5edf7',
    assetHalo: '#0b1220',
    // The Sandbox storm footprint. Amber everywhere in this app means "this is
    // a caveat, read it" — the archive banner, the underpasses, the evidence
    // boundary — and a user-invented storm is exactly that, so it does not get
    // a colour from the risk ramp.
    storm: '#f59e0b',
    ramp: [
      0.0, '#17304d',
      0.25, '#0e7490',
      0.45, '#14b8a6',
      0.6, '#f59e0b',
      0.8, '#ef4444',
      1.0, '#ff6b6b',
    ],
  },
  light: {
    ground: '#e9eef5',
    wardLine: '#9fb2c9',
    wardSelected: '#0f1b2d',
    wardCritical: '#b91c1c',
    // Roads on a light ground follow the paper-map convention: near-white
    // fills with a grey casing, so the choropleth above them still reads.
    roadMajorLow: '#c3cfdd',
    roadMajorMid: '#ffffff',
    roadMajorHigh: '#ffffff',
    roadCasing: '#9aabc0',
    roadSecondaryLow: '#d3dde9',
    roadSecondaryHigh: '#ffffff',
    river: '#5b9dd0',
    canal: '#6ba7d6',
    stream: '#84b6dd',
    drain: '#9cc4e3',
    underpass: '#c2680a',
    underpassPed: '#c99a4e',
    blackspot: '#0f1b2d',
    assetHalo: '#ffffff',
    storm: '#b45309',
    ramp: [
      0.0, '#dbe7f3',
      0.25, '#5fb0c4',
      0.45, '#0f9e8f',
      0.6, '#e08a09',
      0.8, '#e04b4b',
      1.0, '#c62828',
    ],
  },
}

/** CSS gradient string for the map legend, built from the same ramp the map
 *  paints with so the two can never drift apart. */
export function rampGradient(theme) {
  const ramp = MAP_THEME[theme].ramp
  const stops = []
  for (let i = 0; i < ramp.length; i += 2) {
    stops.push(`${ramp[i + 1]} ${Math.round(ramp[i] * 100)}%`)
  }
  return `linear-gradient(90deg,${stops.join(',')})`
}

/** Chart colours for recharts, which also cannot read CSS variables. */
export const CHART_THEME = {
  dark: { grid: '#1f2b40', axis: '#5d738f', tick: '#8ba0bd', tooltipBg: '#111a2c', line: '#14b8a6' },
  light: { grid: '#cbd7e6', axis: '#74869d', tick: '#4a5f7a', tooltipBg: '#ffffff', line: '#0f766e' },
}

export function useChartTheme() {
  return CHART_THEME[useTheme((s) => s.theme)]
}
