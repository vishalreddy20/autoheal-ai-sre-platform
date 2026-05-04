import apiClient from './client'
import type { Incident, SimulationState } from '../types'

// ── Auth ──────────────────────────────────────────────────────────────────────
export const login = (username: string, password: string) =>
  apiClient.post<{ access_token: string; user_id: string; role: string; username: string }>(
    '/auth/login', { username, password }
  )

export const fetchMe = () =>
  apiClient.get<{ id: string; username: string; role: string }>('/auth/me')

export const registerUser = (username: string, password: string, role: string) =>
  apiClient.post('/auth/register', { username, password, role })

// ── Health ────────────────────────────────────────────────────────────────────
export const fetchHealth = () =>
  apiClient.get<{ status: string; service: string; ts: string }>('/health')

// ── Users ─────────────────────────────────────────────────────────────────────
export const fetchUsers = (page = 1, limit = 20) =>
  apiClient.get('/api/users', { params: { page, limit } })

export const createUser = (name: string, email: string) =>
  apiClient.post('/api/users', { name, email })

export const deleteUser = (id: string) =>
  apiClient.delete(`/api/users/${id}`)

// ── Tasks ─────────────────────────────────────────────────────────────────────
export const fetchTasks = (page = 1, limit = 20, status?: string) =>
  apiClient.get('/api/tasks', { params: { page, limit, ...(status ? { status } : {}) } })

export const createTask = (userId: string, title: string) =>
  apiClient.post('/api/tasks', { user_id: userId, title })

export const updateTaskStatus = (id: string, status: string) =>
  apiClient.patch(`/api/tasks/${id}/status`, { status })

// ── Incidents ─────────────────────────────────────────────────────────────────
export const fetchIncidents = (service?: string) =>
  apiClient.get<{ incidents: Incident[] }>('/api/incidents/recent', {
    params: { service: service ?? 'api-gateway' },
  })

export const fetchAllIncidents = () =>
  apiClient.get<{ incidents: Incident[] }>('/api/incidents')

// ── Simulate ──────────────────────────────────────────────────────────────────
export const simulateDbDown = () =>
  apiClient.post('/simulate/db-down')

export const simulateDbRestore = () =>
  apiClient.post('/simulate/db-restore')

export const simulateServiceDown = (service: string) =>
  apiClient.post('/simulate/service-down', { service })

export const simulateServiceRestore = (service: string) =>
  apiClient.post('/simulate/service-restore', { service })

export const simulateSlow = (service: string, delay_ms: number) =>
  apiClient.post('/simulate/slow', { service, delay_ms })

export const simulateSlowRestore = (service: string) =>
  apiClient.post('/simulate/slow-restore', { service })

export const fetchSimulationState = () =>
  apiClient.get<SimulationState>('/simulate/state')
