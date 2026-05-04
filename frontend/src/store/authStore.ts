import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import apiClient from '../api/client'

interface AuthUser {
  id: string
  username: string
  role: 'viewer' | 'operator'
}

interface AuthStore {
  token: string | null
  user: AuthUser | null
  isAuthenticated: boolean

  login: (username: string, password: string) => Promise<void>
  logout: () => void
  restoreSession: () => void
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      token: 'dummy-token',
      user: { id: 'admin-id', username: 'admin', role: 'operator' },
      isAuthenticated: true,

      login: async (username: string, password: string) => {
        const resp = await apiClient.post<{
          access_token: string
          token_type: string
          user_id: string
          role: string
          username: string
        }>('/auth/login', { username, password })

        const { access_token, user_id, role, username: name } = resp.data

        set({
          token: access_token,
          user: { id: user_id, username: name, role: role as 'viewer' | 'operator' },
          isAuthenticated: true,
        })
      },

      logout: () => {
        set({ token: null, user: null, isAuthenticated: false })
      },

      restoreSession: () => {
        const { token, user } = get()
        if (token && user) {
          set({ isAuthenticated: true })
        }
      },
    }),
    {
      name: 'autoheal-auth',
      partialize: (state) => ({
        token: state.token,
        user: state.user,
      }),
    },
  ),
)
