const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

/** Parse API timestamps; legacy SQLite values without an offset are UTC. */
export function parseConversationTime(value?: string | null): Date | null {
  if (!value) return null
  const raw = String(value).trim()
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const date = new Date(hasOffset ? raw : `${raw.replace(' ', 'T')}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Format an API ISO timestamp for users in China without changing storage. */
export function formatConversationTime(value?: string | null): string {
  if (!value) return ''
  const date = parseConversationTime(value)
  if (!date) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date).replace(/\//g, '-')
}
