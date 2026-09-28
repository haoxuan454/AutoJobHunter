const SHANGHAI_TIME_ZONE = 'Asia/Shanghai'

/**
 * Parse history timestamps from the API. SQLite CURRENT_TIMESTAMP values have
 * no offset and are stored as UTC; explicit offsets remain authoritative.
 */
export function parseHistoryTime(value?: string | null): Date | null {
  if (!value) return null
  const raw = String(value).trim()
  const hasOffset = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T')
  const date = new Date(hasOffset ? normalized : `${normalized}Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

/** Render dashboard history in China Standard Time, never browser-local time. */
export function formatHistoryTime(value?: string | null): string {
  if (!value) return ''
  const date = parseHistoryTime(value)
  if (!date) return value
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: SHANGHAI_TIME_ZONE,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date).replace(/\//g, '-')
}
