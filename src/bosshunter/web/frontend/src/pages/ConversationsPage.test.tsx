import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import ConversationsPage from './ConversationsPage'
import ConversationDetailPage from './ConversationDetailPage'

const unreadConversation = {
  id: 'zhilian:delivery:job/1',
  hr_name: '刘先生',
  platform: 'zhilian',
  status: 'active',
  job_id: 'job/1',
  job_title: 'Python 后端开发工程师',
  job_company: '湖南省国银新材料有限公司',
  job_url: 'https://jobs.example.test/job/1',
  conversation_url: 'https://im.example.test/session/1',
  job_score: 86,
  message_count: 3,
  last_message_preview: '方便介绍一下相关项目经验吗？',
  has_unread: true,
  unread_count: 2,
}

function jsonResponse(body: unknown, ok = true) {
  return new Response(JSON.stringify(body), {
    status: ok ? 200 : 500,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('ConversationsPage', () => {
  const fetchMock = vi.fn()
  let readState: typeof unreadConversation | { [key: string]: unknown }

  beforeEach(() => {
    readState = { ...unreadConversation }
    vi.stubGlobal('fetch', fetchMock)
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url === '/api/conversations?sort=recent' && (!init?.method || init.method === 'GET')) {
        return jsonResponse({ conversations: [readState] })
      }
      if (url === '/api/conversations/zhilian%3Adelivery%3Ajob%2F1/sync' && init?.method === 'POST') {
        readState = { ...unreadConversation, message_count: 4 }
        return jsonResponse({ status: 'synced', platform_message_count: 4, message_count: 4, inserted: 1 })
      }
      if (url === '/api/conversations/zhilian%3Adelivery%3Ajob%2F1' && (!init?.method || init.method === 'GET')) {
        readState = { ...readState, has_unread: false, unread_count: 0 }
        return jsonResponse({
          conversation: { ...unreadConversation, has_unread: false, unread_count: 0 },
          messages: [{ id: 1, sender_type: 'hr', content: '方便介绍一下相关项目经验吗？' }],
          drafts: [],
        })
      }
      return jsonResponse({ error: `Unexpected request: ${url}` }, false)
    })
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('shows the linked job metadata and unread state, then syncs only the selected conversation', async () => {
    render(
      <MemoryRouter initialEntries={['/conversations']}>
        <Routes>
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/conversations/:id" element={<ConversationDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('刘先生')).toBeTruthy()
    expect(screen.getByText('湖南省国银新材料有限公司')).toBeTruthy()
    expect(screen.getByText('Python 后端开发工程师')).toBeTruthy()
    expect(screen.getByText('智联招聘')).toBeTruthy()
    expect(screen.getByText('AI 评分：86')).toBeTruthy()
    expect(screen.getByLabelText('2 条未读消息')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: '同步当前会话' }))

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/conversations/zhilian%3Adelivery%3Ajob%2F1/sync',
      { method: 'POST' },
    ))
    await waitFor(() => expect(screen.getByText('消息 4 条')).toBeTruthy())
    expect(screen.getByLabelText('2 条未读消息')).toBeTruthy()
    expect(screen.getByText(/刘先生：已同步，平台读取 4 条/)).toBeTruthy()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/sync'))).toHaveLength(1)

    fireEvent.click(screen.getByRole('link', { name: '查看本地会话' }))
    expect(await screen.findByText('方便介绍一下相关项目经验吗？')).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: '← 返回会话列表' }))
    await waitFor(() => expect(screen.queryByLabelText('2 条未读消息')).toBeNull())
  })
})
