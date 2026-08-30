import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// NOTE: deliberately NOT wrapped in <StrictMode>. Its double mount/unmount
// tears down and recreates the MapLibre instance; with maplibre-gl 6 the
// second instance's style never finishes loading (the worker pool is disposed
// with the first map), leaving a silent blank canvas. One map, one lifetime.
createRoot(document.getElementById('root')).render(<App />)
