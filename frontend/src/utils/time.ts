const IST_TIME_ZONE = 'Asia/Kolkata'

function formatParts(date: Date, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: IST_TIME_ZONE,
    hour12: false,
    ...options,
  }).formatToParts(date)

  return Object.fromEntries(parts.map((part) => [part.type, part.value]))
}

export function formatIstClock(date: Date): string {
  const parts = formatParts(date, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  return `${parts.hour}:${parts.minute}:${parts.second}`
}

export function formatIstDateTime(date: Date): string {
  const parts = formatParts(date, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`
}

export function formatIstTime(date: Date): string {
  const parts = formatParts(date, {
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${parts.hour}:${parts.minute}`
}