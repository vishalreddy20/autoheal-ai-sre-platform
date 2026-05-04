import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js'
import { Line, Bar } from 'react-chartjs-2'
import type { MetricPoint } from '../types'
import { formatIstTime } from '../utils/time'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Title,
  Tooltip,
  Legend,
  Filler,
)

interface LineChartProps {
  title: string
  datasets: Array<{
    label: string
    data: MetricPoint[]
    color: string
  }>
  yUnit?: string
}

export function MetricsLineChart({ title, datasets, yUnit = '' }: LineChartProps) {
  const allTs = datasets.flatMap((d) => d.data.map((p) => p.ts))
  const uniqueTs = Array.from(new Set(allTs)).sort()
  const labels = uniqueTs.map((t) => formatIstTime(new Date(t)))

  const chartData = {
    labels,
    datasets: datasets.map((ds) => {
      const valueMap = new Map(ds.data.map((p) => [p.ts, p.value]))
      return {
        label: ds.label,
        data: uniqueTs.map((t) => valueMap.get(t) ?? null),
        borderColor: ds.color,
        backgroundColor: `${ds.color}18`,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 2,
      }
    }),
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: {
        labels: { color: 'rgba(255,255,255,0.5)', font: { size: 11, family: 'Inter' } },
      },
      title: {
        display: true,
        text: title,
        color: 'rgba(255,255,255,0.8)',
        font: { size: 13, weight: 'bold' as const, family: 'Inter' },
        padding: { bottom: 12 },
      },
      tooltip: {
        backgroundColor: 'rgba(19,21,30,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1,
        titleColor: 'rgba(255,255,255,0.8)',
        bodyColor: 'rgba(255,255,255,0.6)',
        callbacks: {
          label: (ctx: { dataset: { label?: string }; raw: unknown }) =>
            ` ${ctx.dataset.label}: ${Number(ctx.raw).toFixed(3)}${yUnit}`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 10, family: 'JetBrains Mono' }, maxTicksLimit: 8 },
      },
      y: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 10, family: 'JetBrains Mono' } },
        beginAtZero: true,
      },
    },
  }

  return (
    <div className="glass-card rounded-xl p-5 h-[240px]">
      <Line data={chartData} options={options} />
    </div>
  )
}

interface BarChartProps {
  title: string
  labels: string[]
  values: number[]
  color?: string
}

export function MetricsBarChart({ title, labels, values, color = '#00D4AA' }: BarChartProps) {
  const chartData = {
    labels,
    datasets: [
      {
        label: 'Count',
        data: values,
        backgroundColor: `${color}60`,
        borderColor: color,
        borderWidth: 1,
        borderRadius: 4,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: {
      legend: { display: false },
      title: {
        display: true,
        text: title,
        color: 'rgba(255,255,255,0.8)',
        font: { size: 13, weight: 'bold' as const, family: 'Inter' },
        padding: { bottom: 12 },
      },
      tooltip: {
        backgroundColor: 'rgba(19,21,30,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        borderWidth: 1,
        titleColor: 'rgba(255,255,255,0.8)',
        bodyColor: 'rgba(255,255,255,0.6)',
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 10, family: 'JetBrains Mono' } },
      },
      y: {
        grid: { color: 'rgba(255,255,255,0.04)' },
        ticks: { color: 'rgba(255,255,255,0.3)', font: { size: 10, family: 'JetBrains Mono' } },
        beginAtZero: true,
      },
    },
  }

  return (
    <div className="glass-card rounded-xl p-5 h-[240px]">
      <Bar data={chartData} options={options} />
    </div>
  )
}
