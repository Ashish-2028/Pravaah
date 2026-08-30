import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// PRAVAAH UI — all API calls are RELATIVE (/api/...). In dev they are proxied
// to the FastAPI server; in production FastAPI serves ui/dist from the same
// origin. Net effect: no CORS, ever, and the built app works with wifi off.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
  // `npm run preview` serves the real production bundle and proxies the same
  // way, so the offline dry-run can be done without restarting uvicorn.
  preview: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/static': 'http://localhost:8000',
    },
  },
  build: {
    chunkSizeWarningLimit: 2000,
  },
})
