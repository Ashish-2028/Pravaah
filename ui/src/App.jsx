import { useEffect, useState } from 'react'
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import Command from './views/Command'
import Inundation from './views/Inundation'
import Replay from './views/Replay'
import Verify from './views/Verify'
import Nowcast from './views/Nowcast'
import Forecast from './views/Forecast'
import { api } from './lib/api'
import { useStore } from './lib/store'
import { ErrorBox, Spinner } from './components/ui'

function Boot({ children }) {
  const hydrateEvents = useStore((s) => s.hydrateEvents)
  const t = useStore((s) => s.t)
  const [error, setError] = useState(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    api
      .events()
      .then((d) => alive && hydrateEvents(d))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [hydrateEvents, nonce])

  if (error) {
    return (
      <div className="flex h-full items-center justify-center bg-bg p-8">
        <div className="w-full max-w-md">
          <div className="mb-3 text-center text-lg font-bold tracking-[0.18em] text-teal">
            PRAVAAH
          </div>
          <ErrorBox error={error} onRetry={() => { setError(null); setNonce((n) => n + 1) }} />
          <p className="mt-3 text-center text-xs leading-relaxed text-muted">
            Start the backend with <code className="text-ink">uvicorn serve.main:app --port 8000</code>
            {' '}from the repository root, then retry.
          </p>
        </div>
      </div>
    )
  }
  if (!t) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <div className="text-center">
          <div className="mb-2 text-lg font-bold tracking-[0.18em] text-teal">PRAVAAH</div>
          <Spinner label="Loading event catalogue" />
        </div>
      </div>
    )
  }
  return children
}

export default function App() {
  return (
    <HashRouter>
      <Boot>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/command" replace />} />
            <Route path="/command" element={<Command />} />
            <Route path="/inundation" element={<Inundation />} />
            <Route path="/replay" element={<Replay />} />
            <Route path="/verify" element={<Verify />} />
            <Route path="/nowcast" element={<Nowcast />} />
            <Route path="/forecast" element={<Forecast />} />
            <Route path="*" element={<Navigate to="/command" replace />} />
          </Routes>
        </AppShell>
      </Boot>
    </HashRouter>
  )
}
