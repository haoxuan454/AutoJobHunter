import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import DashboardPage from './DashboardPage'

const job = (id: string) => ({ id, company: id, title: '岗位', salary: '', city: '', experience: '', status: 'ready', score: 80, greeting: '您好', greeting_selection: 'original', greeting_review_status: 'confirmed' })
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
let deleteResponse: Response
const fetchMock = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
  if (String(url) === '/api/jobs/soft-delete') return deleteResponse
  if (String(url) === '/api/workbench') return response({
    funnel: {}, funnel_today: {}, task: null, last_task: null, needs_resume: [],
    send_errors: [job('failed-1'), job('failed-2')],
    pending_greetings: [job('greet-1')], pending_confirmation: [job('ready-1')],
    send_quota: { daily_limit: 30, sent: 0, remaining: 30, exhausted: false },
  })
  return response([])
})
const deleteCalls = () => fetchMock.mock.calls.filter(([url, init]) => String(url) === '/api/jobs/soft-delete' && init?.method === 'POST')

describe('workbench backlog deletion boundaries', () => {
  beforeEach(() => {
    deleteResponse = response({ affected_count: 1 })
    fetchMock.mockClear()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('confirm', vi.fn(() => true))
  })
  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('isolates selection and deletes only the selected queue IDs', async () => {
    render(<DashboardPage view="workbench" />)
    const failed = await screen.findByRole('region', { name: '发送失败待处理积压' })
    fireEvent.click(within(failed).getByRole('button', { name: '全选发送失败待处理' }))
    expect(within(failed).getAllByRole('checkbox').every(el => (el as HTMLInputElement).checked)).toBe(true)
    expect((within(screen.getByRole('region', { name: '待发送招呼语积压' })).getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    expect((within(screen.getByRole('region', { name: '今日待确认岗位积压' })).getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
    fireEvent.click(within(failed).getByRole('button', { name: '移入回收站 2' }))
    expect((await screen.findAllByText('已将 1 个积压岗位移入回收站。')).length).toBeGreaterThan(0)
    expect(JSON.parse(String(deleteCalls()[0][1]?.body)).job_ids).toEqual(['failed-1', 'failed-2'])
  })

  it('does not request deletion when confirmation is cancelled', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false))
    render(<DashboardPage view="workbench" />)
    const failed = await screen.findByRole('region', { name: '发送失败待处理积压' })
    fireEvent.click(within(failed).getAllByRole('button', { name: '删除积压' })[0])
    expect(deleteCalls()).toHaveLength(0)
  })

  it('preserves selected cards on an active-task conflict and shows the error', async () => {
    deleteResponse = response({ error: '任务运行中不能删除' }, 409)
    render(<DashboardPage view="workbench" />)
    const failed = await screen.findByRole('region', { name: '发送失败待处理积压' })
    fireEvent.click(within(failed).getAllByRole('checkbox')[0])
    fireEvent.click(within(failed).getByRole('button', { name: '移入回收站 1' }))
    await screen.findAllByText('任务运行中不能删除')
    expect((within(failed).getAllByRole('checkbox')[0] as HTMLInputElement).checked).toBe(true)
    expect(screen.queryByText(/已将.*移入回收站/)).toBeNull()
  })

  it('reports zero affected rows honestly for a single-card delete', async () => {
    deleteResponse = response({ affected_count: 0, not_found: ['failed-1'] })
    render(<DashboardPage view="workbench" />)
    const failed = await screen.findByRole('region', { name: '发送失败待处理积压' })
    fireEvent.click(within(failed).getAllByRole('button', { name: '删除积压' })[0])
    await screen.findAllByText('已将 0 个积压岗位移入回收站。')
    expect(JSON.parse(String(deleteCalls()[0][1]?.body)).job_ids).toEqual(['failed-1'])
  })
})
