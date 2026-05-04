import { useEffect, useState } from 'react'
import { Zap, Wifi, WifiOff, Loader2 } from 'lucide-react'
import { useDashboardStore } from '../../store/dashboardStore'
import { formatIstClock } from '../../utils/time'

export function TopBar() {
  const [now, setNow] = useState(new Date())
  const sseConnected = useDashboardStore((s) => s.sseConnected)
  const sseReconnecting = useDashboardStore((s) => s.sseReconnecting)

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-navy-900/80 backdrop-blur-md border-b border-white/5 flex items-center px-6 z-30">
      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 bg-gradient-to-br from-teal-400 to-teal-600 rounded-lg flex items-center justify-center shadow-lg shadow-teal-400/20">
          <Zap className="w-4 h-4 text-navy-950" />
        </div>
        <span className="text-white font-semibold text-sm tracking-wide">AutoHeal AI</span>
      </div>

      <div className="flex-1" />

      {/* Live clock */}
      <div className="font-mono text-sm text-white/40 mr-6">
        {formatIstClock(now)} IST
      </div>

      {/* SSE connection status */}
      <div className="flex items-center gap-2">
        {sseReconnecting ? (
          <>
            <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />
            <span className="text-xs text-amber-400 font-medium">Reconnecting...</span>
          </>
        ) : sseConnected ? (
          <>
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-teal-400" />
            </span>
            <Wifi className="w-4 h-4 text-teal-400" />
            <span className="text-xs text-teal-400 font-medium">Live</span>
          </>
        ) : (
          <>
            <WifiOff className="w-4 h-4 text-crimson-400" />
            <span className="text-xs text-crimson-400 font-medium">Disconnected</span>
          </>
        )}
      </div>
    </header>
  )
}
