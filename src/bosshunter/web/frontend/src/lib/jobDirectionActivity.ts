export const JOB_DIRECTION_LIMIT = 50

export type JobDirectionActivity = {
  label: string
  conversations: number
  replied_conversations: number
  hr_messages: number
  message_count: number
  reply_rate: number
}

/** Rank persisted conversations by actual two-way activity, not reply percentage. */
export function topJobDirections(rows: JobDirectionActivity[]): JobDirectionActivity[] {
  return [...rows]
    .filter(row => Number.isFinite(row.message_count) && row.message_count > 0)
    .sort((a, b) => b.message_count - a.message_count
      || b.hr_messages - a.hr_messages
      || b.conversations - a.conversations
      || a.label.localeCompare(b.label, 'zh-CN'))
    .slice(0, JOB_DIRECTION_LIMIT)
}
