import { useState, FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import toast from 'react-hot-toast'

export function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password.trim()) {
      toast.error('Username and password are required')
      return
    }
    setLoading(true)
    try {
      await login(username.trim(), password)
      toast.success('Welcome back!')
      navigate('/', { replace: true })
    } catch (err: any) {
      const msg = err?.error ?? err?.detail ?? 'Invalid credentials'
      toast.error(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'radial-gradient(ellipse at 60% 0%, #1a2a4a 0%, #0a0d1a 55%, #050709 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: "'Inter', sans-serif",
      padding: '1rem',
    }}>
      {/* Ambient glow blobs */}
      <div style={{
        position: 'fixed', top: '15%', left: '25%', width: 480, height: 480,
        background: 'radial-gradient(circle, rgba(0,212,170,0.07) 0%, transparent 70%)',
        borderRadius: '50%', pointerEvents: 'none',
      }} />
      <div style={{
        position: 'fixed', bottom: '20%', right: '20%', width: 320, height: 320,
        background: 'radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 70%)',
        borderRadius: '50%', pointerEvents: 'none',
      }} />

      <div style={{
        width: '100%',
        maxWidth: 420,
        position: 'relative',
        zIndex: 1,
      }}>
        {/* Logo + Title */}
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          <div style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 56,
            height: 56,
            borderRadius: 16,
            background: 'linear-gradient(135deg, #00D4AA 0%, #0ea5e9 100%)',
            marginBottom: '1rem',
            boxShadow: '0 8px 32px rgba(0,212,170,0.3)',
          }}>
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
            </svg>
          </div>
          <h1 style={{ color: '#fff', fontSize: '1.5rem', fontWeight: 700, margin: 0 }}>
            AutoHeal AI
          </h1>
          <p style={{ color: 'rgba(255,255,255,0.45)', fontSize: '0.875rem', marginTop: '0.375rem' }}>
            SRE Intelligence Platform
          </p>
        </div>

        {/* Card */}
        <form
          onSubmit={handleSubmit}
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            borderRadius: 20,
            padding: '2rem',
            backdropFilter: 'blur(12px)',
            boxShadow: '0 24px 60px rgba(0,0,0,0.4)',
          }}
        >
          <h2 style={{ color: '#fff', fontSize: '1.125rem', fontWeight: 600, margin: '0 0 1.5rem 0' }}>
            Sign in to your workspace
          </h2>

          {/* Username */}
          <div style={{ marginBottom: '1rem' }}>
            <label style={{ display: 'block', color: 'rgba(255,255,255,0.6)', fontSize: '0.8125rem', fontWeight: 500, marginBottom: '0.375rem' }}>
              Username
            </label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              style={{
                width: '100%',
                padding: '0.65rem 0.875rem',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 10,
                color: '#fff',
                fontSize: '0.9375rem',
                outline: 'none',
                transition: 'border-color 0.2s',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => e.target.style.borderColor = 'rgba(0,212,170,0.5)'}
              onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ display: 'block', color: 'rgba(255,255,255,0.6)', fontSize: '0.8125rem', fontWeight: 500, marginBottom: '0.375rem' }}>
              Password
            </label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              style={{
                width: '100%',
                padding: '0.65rem 0.875rem',
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 10,
                color: '#fff',
                fontSize: '0.9375rem',
                outline: 'none',
                transition: 'border-color 0.2s',
                boxSizing: 'border-box',
              }}
              onFocus={(e) => e.target.style.borderColor = 'rgba(0,212,170,0.5)'}
              onBlur={(e) => e.target.style.borderColor = 'rgba(255,255,255,0.1)'}
            />
          </div>

          {/* Submit */}
          <button
            id="login-submit"
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '0.75rem',
              background: loading
                ? 'rgba(0,212,170,0.4)'
                : 'linear-gradient(135deg, #00D4AA 0%, #0ea5e9 100%)',
              border: 'none',
              borderRadius: 10,
              color: '#fff',
              fontSize: '0.9375rem',
              fontWeight: 600,
              cursor: loading ? 'not-allowed' : 'pointer',
              transition: 'opacity 0.2s, transform 0.1s',
              letterSpacing: '0.02em',
            }}
            onMouseEnter={(e) => !loading && ((e.target as HTMLElement).style.opacity = '0.9')}
            onMouseLeave={(e) => !loading && ((e.target as HTMLElement).style.opacity = '1')}
          >
            {loading ? 'Signing in…' : 'Sign In'}
          </button>

          {/* Role hint */}
          <div style={{
            marginTop: '1.5rem',
            padding: '0.875rem',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 10,
          }}>
            <p style={{ color: 'rgba(255,255,255,0.4)', fontSize: '0.75rem', margin: 0, lineHeight: 1.6 }}>
              <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Default accounts</strong><br />
              <code style={{ color: '#00D4AA' }}>admin</code> / <code style={{ color: '#00D4AA' }}>admin123</code> — Operator<br />
              <code style={{ color: '#6366f1' }}>viewer</code> / <code style={{ color: '#6366f1' }}>viewer123</code> — Viewer
            </p>
          </div>
        </form>
      </div>
    </div>
  )
}
