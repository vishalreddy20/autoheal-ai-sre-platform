import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Doughnut } from 'react-chartjs-2'

ChartJS.register(ArcElement, Tooltip, Legend)

interface Props {
  label: string
  value: number | null
  target: number
}

function getTone(value: number | null): {
  text: string
  bg: string
  stroke: string
} {
  if (value === null) return { text: 'text-slate-400', bg: 'bg-slate-400/10', stroke: '#94A3B8' }
  if (value >= 99) return { text: 'text-teal-400', bg: 'bg-teal-400/10', stroke: '#00D4AA' }
  if (value >= 95) return { text: 'text-amber-400', bg: 'bg-amber-400/10', stroke: '#F59E0B' }
  return { text: 'text-red-500', bg: 'bg-red-500/10', stroke: '#EF4444' }
}

export function SLOGauge({ label, value, target }: Props) {
  const tone = getTone(value)
  const normalizedValue = value ?? 0
  const remaining = Math.max(0, 100 - normalizedValue)

  const data = {
    datasets: [
      {
        data: [value, remaining],
        backgroundColor: [tone.stroke, 'rgba(255,255,255,0.05)'],
        borderWidth: 0,
        hoverOffset: 4,
        circumference: 270,
        rotation: -135,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: true,
    cutout: '75%',
    plugins: {
      legend: { display: false },
      tooltip: { enabled: false },
    },
  }

  return (
    <div className="glass-card rounded-xl p-6 flex flex-col items-center gap-4">
      <div className="relative h-[120px] w-[160px]">
        <Doughnut data={data} options={options} />
        {/* Center text */}
        <div className="absolute inset-0 top-[10%] flex flex-col items-center justify-center">
          <span className={`font-mono text-2xl font-bold ${tone.text}`}>
            {value === null ? '—' : `${value.toFixed(1)}%`}
          </span>
        </div>
      </div>
      <div className="text-center">
        <p className="text-white/70 text-sm font-medium">{label}</p>
        <p className="text-white/30 text-xs mt-0.5">Target: {target}%</p>
      </div>
      {/* Compliance indicator */}
      <div className={`w-full text-center text-xs font-bold py-1 rounded ${tone.text} ${tone.bg}`}>
        {value === null ? 'Awaiting live data' : value >= target ? '✓ SLO MET' : '⚠ SLO BREACHED'}
      </div>
    </div>
  )
}
