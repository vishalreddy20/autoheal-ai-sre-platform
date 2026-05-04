import { ControlPanel } from '../components/ControlPanel'

export function Controls() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold text-white mb-1">Chaos Controls</h1>
        <p className="text-white/30 text-sm">
          Inject failures to trigger AutoHeal. Incidents appear in real time on the dashboard.
        </p>
      </div>

      <ControlPanel />

      <div className="glass-card rounded-xl p-6 border border-teal-400/10">
        <h3 className="text-teal-400 font-semibold text-sm mb-4">Demo Walkthrough</h3>
        <ol className="space-y-3 text-sm text-white/50">
          <li className="flex gap-3">
            <span className="text-teal-400 font-mono font-bold flex-shrink-0">1.</span>
            Click <strong className="text-white/70">Simulate DB Failure</strong>, then watch user-service and task-service return 503s.
          </li>
          <li className="flex gap-3">
            <span className="text-teal-400 font-mono font-bold flex-shrink-0">2.</span>
            AutoHeal Engine detects the issue within 5s and creates a <strong className="text-white/70">critical incident</strong>.
          </li>
          <li className="flex gap-3">
            <span className="text-teal-400 font-mono font-bold flex-shrink-0">3.</span>
            Check the <strong className="text-white/70">Incidents page</strong> for real-time updates.
          </li>
          <li className="flex gap-3">
            <span className="text-teal-400 font-mono font-bold flex-shrink-0">4.</span>
            Click <strong className="text-white/70">Restore DB</strong> and AutoHeal marks the incident as resolved.
          </li>
          <li className="flex gap-3">
            <span className="text-teal-400 font-mono font-bold flex-shrink-0">5.</span>
            Try <strong className="text-white/70">Inject Delay (800ms+)</strong>, then AutoHeal throttles traffic and monitors recovery.
          </li>
        </ol>
      </div>
    </div>
  )
}
