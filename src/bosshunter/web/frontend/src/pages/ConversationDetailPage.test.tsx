import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ConversationDetailPage from './ConversationDetailPage'

const initialMessages = [
  { id: 2, sender_type: 'hr', content: '最新的 HR 消息', message_time: '2026-09-27 10:02' },
  { id: 1, sender_type: 'user', content: '较早的招呼语', message_time: '2026-09-27 10:01', is_sent: 1 },
]

const conversation = {
  id: 'conv-1', hr_name: '刘先生', status: 'active', platform: 'boss',
  job_id: 'job-1', job_title: 'Python 工程师', job_company: '示例公司', job_score: 82,
  conversation_url: 'https://www.zhipin.com/web/geek/chat',
  job_url: 'https://www.zhipin.com/job_detail/123.html', message_count: 2,
}

function jsonResponse(body: unknown, ok = true) {
  return new Response(JSON.stringify(body), {
    status: ok ? 200 : 500,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ConversationDetailPage', () => {
  const fetchMock = vi.fn()
  let sentMessage = ''

  beforeEach(() => {
    sentMessage = ''
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/conversations/conv-1' && (!init?.method || init.method === 'GET')) {
        const messages = sentMessage
          ? [...initialMessages, { id: 3, sender_type: 'user', content: sentMessage, is_sent: 1 }]
          : initialMessages
        return jsonResponse({ conversation, messages, drafts: [] })
      }
      if (url === '/api/conversations/conv-1/draft' && init?.method === 'POST') {
        return jsonResponse({ draft: { id: 1, draft_text: 'AI 建议：可以介绍相关项目经验。', status: 'draft', created_at: '2026-09-27' } })
      }
      if (url === '/api/conversations/conv-1/reply/send' && init?.method === 'POST') {
        sentMessage = JSON.parse(String(init.body)).message
        return jsonResponse({ status: 'sent' })
      }
      return jsonResponse({ error: `Unexpected request: ${url}` }, false)
    })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('renders chronological messages and requires human confirmation before sending an edited draft', async () => {
    render(
      <MemoryRouter initialEntries={['/conversations/conv-1']}>
        <Routes><Route path="/conversations/:id" element={<ConversationDetailPage />} /></Routes>
      </MemoryRouter>,
    )

    const older = await screen.findByText('较早的招呼语')
    const latest = screen.getByText('最新的 HR 消息')
    expect(older.compareDocumentPosition(latest) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'AI 生成回复草稿' }))
    const editor = await screen.findByDisplayValue('AI 建议：可以介绍相关项目经验。')
    fireEvent.change(editor, { target: { value: '我已核对并编辑的回复内容。' } })

    const confirmMock = vi.mocked(window.confirm)
    confirmMock.mockReturnValueOnce(false)
    fireEvent.click(screen.getByRole('button', { name: '确认并发送' }))
    await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1))
    expect(fetchMock).not.toHaveBeenCalledWith('/api/conversations/conv-1/reply/send', expect.anything())

    fireEvent.click(screen.getByRole('button', { name: '确认并发送' }))
    await waitFor(() => expect(sentMessage).toBe('我已核对并编辑的回复内容。'))
    expect(await screen.findByText('平台已确认发送，消息已写入本地会话')).toBeTruthy()
    expect(screen.getByText('我已核对并编辑的回复内容。')).toBeTruthy()
    const sendCall = fetchMock.mock.calls.find(([url]) => String(url) === '/api/conversations/conv-1/reply/send')
    expect(sendCall).toBeTruthy()
    expect(JSON.parse(String(sendCall?.[1]?.body))).toMatchObject({ message: '我已核对并编辑的回复内容。' })
  })
})
