import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ConversationsPage from './ConversationsPage'

const cards = Array.from({ length: 60 }, (_, index) => ({
  id: `boss:delivery:${index}`, hr_name: `HR-${index + 1}`, platform: 'boss',
  status: 'active', job_id: `job-${index}`, job_title: '开发工程师', job_company: '示例公司',
  message_count: index + 1,
}))
const response = (conversations: unknown[]) => new Response(JSON.stringify({ conversations }))

function mount() {
  render(<MemoryRouter><ConversationsPage /></MemoryRouter>)
}

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('global conversation pagination', () => {
  it('pages the globally ordered list and promotes a fifth-page new chat to page one after sync', async () => {
    let ordered = [...cards]
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/conversations/sync') {
        ordered = [cards[59], ...cards.slice(0, 59)]
        return new Response(JSON.stringify({ results: [{ platform: 'boss', status: 'synced', inserted: 1 }] }))
      }
      return response(ordered)
    })
    vi.stubGlobal('fetch', fetchMock)
    mount()
    await screen.findByText('HR-1')
    expect(screen.getAllByRole('link', { name: '查看本地会话' })).toHaveLength(12)
    expect(screen.queryByText('HR-60')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '尾页' }))
    expect(screen.getByText('HR-60')).toBeTruthy()
    expect(screen.getByText(/第 5 \/ 5 页/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '同步已打开平台会话' }))
    await screen.findByText(/第 1 \/ 5 页/)
    expect(screen.getAllByRole('link', { name: /^HR-/ })[0].textContent).toBe('HR-60')
    // Changing page never reads the platform or fetches a per-page unsorted subset.
    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/conversations/sync')).toHaveLength(1)
  })

  it('applies user-selected ordering to all pages and resets page on page-size change', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(
      url.includes('frequency') ? [...cards].reverse() : cards,
    )))
    mount()
    await screen.findByText('HR-1')
    fireEvent.click(screen.getByRole('button', { name: '尾页' }))
    fireEvent.change(screen.getByLabelText('会话排序规则'), { target: { value: 'frequency' } })
    await waitFor(() => expect(screen.getAllByRole('link', { name: /^HR-/ })[0].textContent).toBe('HR-60'))
    expect(screen.getByText(/第 1 \/ 5 页/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '尾页' }))
    fireEvent.change(screen.getByLabelText('每页会话数'), { target: { value: '24' } })
    expect(screen.getAllByRole('link', { name: '查看本地会话' })).toHaveLength(24)
    expect(screen.getByText(/第 1 \/ 3 页/)).toBeTruthy()
  })

  it('clamps the page when its final card is deleted without deleting any other card', async () => {
    let ordered = cards.slice(0, 49)
    vi.stubGlobal('confirm', vi.fn(() => true))
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE') {
        ordered = ordered.slice(0, 48)
        return new Response('{}')
      }
      return response(ordered)
    })
    vi.stubGlobal('fetch', fetchMock)
    mount()
    await screen.findByText('HR-1')
    fireEvent.click(screen.getByRole('button', { name: '尾页' }))
    expect(screen.getByText('HR-49')).toBeTruthy()
    fireEvent.click(screen.getByTitle('删除本地会话'))
    await screen.findByText(/第 4 \/ 4 页/)
    expect(screen.queryByText('HR-49')).toBeNull()
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(1)
  })

  it('ignores an older response that resolves after the selected sorting request', async () => {
    let resolveOld!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('frequency')
      ? Promise.resolve(response([...cards].reverse()))
      : new Promise<Response>(resolve => { resolveOld = resolve })))
    mount()
    fireEvent.change(screen.getByLabelText('会话排序规则'), { target: { value: 'frequency' } })
    await screen.findByText('HR-60')
    resolveOld(response(cards))
    await waitFor(() => expect(screen.getAllByRole('link', { name: /^HR-/ })[0].textContent).toBe('HR-60'))
    expect(screen.queryByText('HR-1')).toBeNull()
  })
})
