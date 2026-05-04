import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import { TopBar } from './components/layout/TopBar'
import { Sidebar } from './components/layout/Sidebar'
import { Dashboard } from './pages/Dashboard'
import { Incidents } from './pages/Incidents'
import { Controls } from './pages/Controls'
import { SLO } from './pages/SLO'
import { useSSE } from './hooks/useSSE'
import { useAuthStore } from './store/authStore'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchInterval: false,
      retry: 2,
    },
  },
})

function KeyboardNav() {
  const navigate = useNavigate()
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) return
      switch (e.key.toUpperCase()) {
        case 'D': navigate('/'); break
        case 'I': navigate('/incidents'); break
        case 'C': navigate('/controls'); break
        case 'S': navigate('/slo'); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigate])
  return null
}

function AppShell() {
  useSSE()
  const { user, logout } = useAuthStore()

  return (
    <div className="min-h-screen bg-navy-950 text-white">
      <TopBar user={user} onLogout={logout} />
      <Sidebar />
      <main className="ml-60 pt-14 min-h-screen">
        <div className="p-6 max-w-7xl">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/controls" element={<Controls />} />
            <Route path="/slo" element={<SLO />} />
            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
      <KeyboardNav />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* AppShell contains the main layouts and routes */}
          <Route path="/*" element={<AppShell />} />
        </Routes>
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
              background: '#1A1D2E',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.08)',
              fontSize: '13px',
              fontFamily: 'Inter, sans-serif',
            },
            success: { iconTheme: { primary: '#00D4AA', secondary: '#0F1117' } },
            error:   { iconTheme: { primary: '#EF4444', secondary: '#0F1117' } },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
