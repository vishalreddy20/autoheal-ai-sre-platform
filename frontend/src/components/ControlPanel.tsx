import { useState } from 'react'
import toast from 'react-hot-toast'
import { Database, Server, Gauge, Loader2 } from 'lucide-react'
import {
  simulateDbDown,
  simulateDbRestore,
  simulateServiceDown,
  simulateServiceRestore,
  simulateSlow,
  simulateSlowRestore,
} from '../api/endpoints'
import type { ApiError } from '../types'

function ActionButton({
  label,
  onClick,
  variant = 'default',
  disabled = false,
  loading = false,
  ariaLabel,
}: {
  label: string
  onClick: () => void
  variant?: 'danger' | 'success' | 'default' | 'warning'
  disabled?: boolean
  loading?: boolean
  ariaLabel: string
}) {
  const colors = {
    danger: 'bg-crimson-400/20 text-crimson-400 border-crimson-400/30 hover:bg-crimson-400/30',
    success: 'bg-teal-400/20 text-teal-400 border-teal-400/30 hover:bg-teal-400/30',
    warning: 'bg-amber-400/20 text-amber-400 border-amber-400/30 hover:bg-amber-400/30',
    default: 'bg-white/5 text-white/70 border-white/10 hover:bg-white/10',
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      aria-label={ariaLabel}
      className={`flex items-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed ${colors[variant]}`}
    >
      {loading && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
      {label}
    </button>
  )
}

async function withToast(fn: () => Promise<unknown>, successMsg: string) {
  try {
    await fn()
    toast.success(successMsg)
  } catch (err) {
    const e = err as ApiError
    toast.error(`${e.error ?? 'Error'} [${e.request_id ?? 'unknown'}]`)
  }
}

export function ControlPanel() {
  const [dbLoading, setDbLoading] = useState(false)
  const [svcLoading, setSvcLoading] = useState(false)
  const [delayLoading, setDelayLoading] = useState(false)
  const [selectedService, setSelectedService] = useState('user-service')
  const [delayService, setDelayService] = useState('user-service')
  const [delayMs, setDelayMs] = useState(500)

  const services = ['user-service', 'task-service', 'api-gateway']

  return (
    <div className="space-y-6">
      {/* DB Simulation */}
      <div className="glass-card rounded-xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-8 h-8 bg-crimson-400/10 rounded-lg flex items-center justify-center">
            <Database className="w-4 h-4 text-crimson-400" />
          </div>
          <div>
            <h3 className="text-white font-semibold text-sm">Database Simulation</h3>
            <p className="text-white/30 text-xs">Simulate DB failure across all services</p>
          </div>
        </div>
        <div className="flex gap-3">
          <ActionButton
            label="Simulate DB Failure"
            variant="danger"
            loading={dbLoading}
            ariaLabel="Simulate database failure"
            onClick={async () => {
              setDbLoading(true)
              await withToast(() => simulateDbDown(), 'DB failure simulated')
              setDbLoading(false)
            }}
          />
          <ActionButton
            label="Restore DB"
            variant="success"
            loading={dbLoading}
            ariaLabel="Restore database"
            onClick={async () => {
              setDbLoading(true)
              await withToast(() => simulateDbRestore(), 'DB restored')
              setDbLoading(false)
            }}
          />
        </div>
      </div>

      {/* Service Control */}
      <div className="glass-card rounded-xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-8 h-8 bg-amber-400/10 rounded-lg flex items-center justify-center">
            <Server className="w-4 h-4 text-amber-400" />
          </div>
          <div>
            <h3 className="text-white font-semibold text-sm">Service Control</h3>
            <p className="text-white/30 text-xs">Stop or restore individual microservices</p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <select
            value={selectedService}
            onChange={(e) => setSelectedService(e.target.value)}
            aria-label="Select service to control"
            className="bg-navy-800 border border-white/10 text-white/70 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-teal-400/50"
          >
            {services.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <ActionButton
            label="Stop Service"
            variant="danger"
            loading={svcLoading}
            ariaLabel={`Stop ${selectedService}`}
            onClick={async () => {
              setSvcLoading(true)
              await withToast(() => simulateServiceDown(selectedService), `${selectedService} stopped`)
              setSvcLoading(false)
            }}
          />
          <ActionButton
            label="Restore Service"
            variant="success"
            loading={svcLoading}
            ariaLabel={`Restore ${selectedService}`}
            onClick={async () => {
              setSvcLoading(true)
              await withToast(() => simulateServiceRestore(selectedService), `${selectedService} restored`)
              setSvcLoading(false)
            }}
          />
        </div>
      </div>

      {/* Latency Injection */}
      <div className="glass-card rounded-xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-8 h-8 bg-teal-400/10 rounded-lg flex items-center justify-center">
            <Gauge className="w-4 h-4 text-teal-400" />
          </div>
          <div>
            <h3 className="text-white font-semibold text-sm">Latency Injection</h3>
            <p className="text-white/30 text-xs">Inject artificial latency to trigger AutoHeal</p>
          </div>
        </div>
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <select
              value={delayService}
              onChange={(e) => setDelayService(e.target.value)}
              aria-label="Select service for latency injection"
              className="bg-navy-800 border border-white/10 text-white/70 text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-teal-400/50"
            >
              {services.filter((s) => s !== 'api-gateway').map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <div className="flex-1">
              <div className="flex justify-between text-xs text-white/40 mb-1">
                <span>100ms</span>
                <span className="text-teal-400 font-mono font-bold">{delayMs}ms</span>
                <span>2000ms</span>
              </div>
              <input
                type="range"
                min={100}
                max={2000}
                step={100}
                value={delayMs}
                onChange={(e) => setDelayMs(Number(e.target.value))}
                aria-label="Set artificial delay in milliseconds"
                className="w-full accent-teal-400"
              />
            </div>
          </div>
          <div className="flex gap-3">
            <ActionButton
              label="Inject Delay"
              variant="warning"
              loading={delayLoading}
              ariaLabel="Inject artificial delay"
              onClick={async () => {
                setDelayLoading(true)
                await withToast(
                  () => simulateSlow(delayService, delayMs),
                  `${delayMs}ms delay injected into ${delayService}`,
                )
                setDelayLoading(false)
              }}
            />
            <ActionButton
              label="Remove Delay"
              variant="success"
              loading={delayLoading}
              ariaLabel="Remove artificial delay"
              onClick={async () => {
                setDelayLoading(true)
                await withToast(
                  () => simulateSlowRestore(delayService),
                  `Delay removed from ${delayService}`,
                )
                setDelayLoading(false)
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
