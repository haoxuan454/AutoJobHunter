import { describe, expect, it } from 'vitest'
import { formatConversationTime } from './conversationDisplay'

describe('formatConversationTime', () => {
  it('formats UTC API timestamps as China Standard Time', () => {
    expect(formatConversationTime('2026-09-28T04:35:02+00:00')).toBe('2026-09-28 12:35:02')
    expect(formatConversationTime('2026-09-28 10:15:13')).toBe('2026-09-28 18:15:13')
  })

  it('preserves empty and invalid values safely', () => {
    expect(formatConversationTime()).toBe('')
    expect(formatConversationTime('not-a-date')).toBe('not-a-date')
  })
})
