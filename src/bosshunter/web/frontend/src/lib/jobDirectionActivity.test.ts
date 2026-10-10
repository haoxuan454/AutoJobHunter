import { describe, expect, it } from 'vitest'
import { topJobDirections, type JobDirectionActivity } from './jobDirectionActivity'

const row = (label: string, message_count: number, hr_messages = 1): JobDirectionActivity => ({
  label, message_count, hr_messages, conversations: 1, replied_conversations: 1, reply_rate: 100,
})

describe('topJobDirections', () => {
  it('ranks actual activity, caps at 50 and preserves input order/data', () => {
    const rows = Array.from({ length: 100 }, (_, index) => row(`方向-${index}`, index + 1))
    const before = JSON.stringify(rows)
    const result = topJobDirections(rows)
    expect(result).toHaveLength(50)
    expect(result[0].message_count).toBe(100)
    expect(result[49].message_count).toBe(51)
    expect(JSON.stringify(rows)).toBe(before)
  })

  it('omits invalid and zero activity, breaks ties consistently', () => {
    const rows = [row('B', 2), row('A', 2), row('更多 HR 消息', 2, 2), row('空', 0), row('NaN', NaN), row('无限', Infinity)]
    expect(topJobDirections(rows).map(item => item.label)).toEqual(['更多 HR 消息', 'A', 'B'])
    expect(topJobDirections([])).toEqual([])
  })
})
