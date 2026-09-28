import { describe, expect, it } from 'vitest'
import { formatHistoryTime } from './historyDisplay'

describe('formatHistoryTime', () => {
  it('treats legacy SQLite timestamps as UTC and formats Shanghai time', () => {
    expect(formatHistoryTime('2026-09-28 04:08:13')).toBe('09-28 12:08')
  })

  it('does not double-convert explicit offsets', () => {
    expect(formatHistoryTime('2026-09-28T12:08:13+08:00')).toBe('09-28 12:08')
    expect(formatHistoryTime('2026-09-28T04:08:13Z')).toBe('09-28 12:08')
  })
})
