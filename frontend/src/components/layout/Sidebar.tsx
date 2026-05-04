import { NavLink } from 'react-router-dom'
import { LayoutDashboard, AlertTriangle, Sliders, Target, Zap } from 'lucide-react'

const navItems = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, key: 'D' },
  { to: '/incidents', label: 'Incidents', icon: AlertTriangle, key: 'I' },
  { to: '/controls', label: 'Controls', icon: Sliders, key: 'C' },
  { to: '/slo', label: 'SLO', icon: Target, key: 'S' },
]

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-14 h-[calc(100vh-56px)] w-60 bg-navy-900 border-r border-white/5 flex flex-col z-20 transition-all duration-300">
      {/* Logo area */}
      <div className="flex items-center gap-3 px-5 py-6 border-b border-white/5">
        <div className="w-8 h-8 bg-gradient-to-br from-teal-400 to-teal-600 rounded-lg flex items-center justify-center">
          <Zap className="w-5 h-5 text-navy-950" />
        </div>
        <div>
          <p className="text-xs text-white/40 font-mono">v1.0.0</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ to, label, icon: Icon, key }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            aria-label={`Navigate to ${label} (${key})`}
            className={({ isActive }) =>
              `flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-200 group ${
                isActive
                  ? 'bg-teal-400/10 text-teal-400 border border-teal-400/20'
                  : 'text-white/50 hover:text-white hover:bg-white/5'
              }`
            }
          >
            <Icon className="w-4 h-4 flex-shrink-0" />
            <span className="text-sm font-medium flex-1">{label}</span>
            <kbd className="text-[10px] text-white/20 bg-white/5 px-1.5 py-0.5 rounded font-mono">
              {key}
            </kbd>
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-white/5">
        <p className="text-[11px] text-white/20 font-mono">AutoHeal AI</p>
        <p className="text-[10px] text-white/10">Self-Healing Microservices</p>
      </div>
    </aside>
  )
}
