import axios from 'axios'
import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 10_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ── Request interceptor — inject JWT + request ID ──────────────────────────
apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  config.headers['X-Request-ID'] = crypto.randomUUID()

  // Inject stored Bearer token on every request (except /auth/login & /auth/register)
  const skipAuth = ['/auth/login', '/auth/register'].some(
    (p) => config.url?.startsWith(p),
  )
  if (!skipAuth) {
    try {
      const raw = localStorage.getItem('autoheal-auth')
      if (raw) {
        const { state } = JSON.parse(raw) as { state: { token: string | null } }
        if (state?.token) {
          config.headers['Authorization'] = `Bearer ${state.token}`
        }
      }
    } catch {
      // Ignore parse errors — unauthenticated requests will get 401 from server
    }
  }

  return config
})

// ── Response interceptor — extract request ID; handle 401 globally ─────────
apiClient.interceptors.response.use(
  (response: AxiosResponse) => response,
  (error: AxiosError) => {
    const requestId =
      error.response?.headers?.['x-request-id'] ??
      error.config?.headers?.['X-Request-ID'] ??
      'unknown'

    // 401 handling removed as login is disabled

    return Promise.reject({
      error: (error.response?.data as Record<string, string>)?.error ?? error.message,
      detail: (error.response?.data as Record<string, string>)?.detail,
      request_id: requestId,
      status: error.response?.status,
    })
  },
)

export default apiClient
