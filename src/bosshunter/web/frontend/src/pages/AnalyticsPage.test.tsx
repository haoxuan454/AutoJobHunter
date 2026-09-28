import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import AnalyticsPage from './AnalyticsPage'

const sampleAnalytics = {
  conversations_total: 3,
  messages_total: 5,
  confirmed_public_facts: 2,
  salary_paused: 1,
  by_status: [{ status: 'waiting_reply', count: 2 }, { status: 'paused_salary', count: 1 }],
  messages_by_sender: [{ sender_type: 'hr', count: 3 }, { sender_type: 'user', count: 2 }],
  by_platform: [],
  daily_trend: [{ day: '2026-09-27', deliveries: 2, replied_conversations: 1, outgoing_messages: 2, incoming_messages: 3 }],
  job_directions: [
    { label: 'Python 后端工程师', conversations: 2, replied_conversations: 1, hr_messages: 2, reply_rate: 50 },
    { label: 'Java 平台研发工程师', conversations: 1, replied_conversations: 0, hr_messages: 0, reply_rate: 0 },
  ],
  platform_metrics: [{ platform: 'zhilian', conversations: 2, replied_conversations: 1, reply_rate: 50 }],
  hr_question_keywords: [
    { content: '可以介绍一下你的项目吗？', count: 4 },
    { content: '你的期望薪资是多少？', count: 2 },
  ],
}

describe('AnalyticsPage', () => {
  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(sampleAnalytics), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    })))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('explains chart purpose, uses Chinese labels, and replaces score-rate analysis with job direction performance', async () => {
    const { container } = render(<AnalyticsPage />)
    expect(await screen.findByText('每日投递与回复趋势')).toBeTruthy()
    const tooltips = Array.from(container.querySelectorAll('[role="tooltip"]'))
      .map(node => node.textContent || '')
    expect(tooltips.some(text => /横轴是本地确认记录的日期/.test(text))).toBe(true)
    expect(screen.getByText('岗位方向回复率排行')).toBeTruthy()
    expect(screen.getByText(/哪些岗位方向目前更常收到 HR 回复/)).toBeTruthy()
    expect(screen.queryByText('AI 评分区间与 HR 回复率')).toBeNull()
    expect(screen.getByText('等待 HR 回复')).toBeTruthy()
    expect(screen.getByText('我方消息')).toBeTruthy()
    expect(screen.getByText(/按相同原文出现次数从高到低排列/)).toBeTruthy()
  })
})
