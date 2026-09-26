import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpDown, BriefcaseBusiness, ExternalLink, MessageCircle, PauseCircle, RefreshCw, Trash2 } from 'lucide-react'
import { PLATFORM_LABELS, PLATFORM_SHORT_LABELS } from '@/lib/platforms'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type SortMode = 'recent' | 'frequency' | 'created'
type Conversation = {
  id: string
  hr_name: string
  platform?: string
  company_id?: string
  job_id?: string
  status: string
  last_message_at?: string
  last_sync_at?: string
  round_count?: number
  message_count?: number
  last_message_preview?: string
  job_title?: string
  job_company?: string
  job_url?: string
  conversation_url?: string
  conversation_url_available?: boolean
  conversation_url_reason?: string
  job_url_available?: boolean
  job_url_reason?: string
  hr_profile_url?: string
  job_score?: number
  job_status?: string
}

const SORT_LABELS: Record<SortMode, string> = { recent: '最近聊天', frequency: '对话最频繁', created: '创建时间' }
const SYNC_STATUS_LABELS: Record<string, string> = {
  synced: '已同步',
  empty: '没有已加载会话',
  empty_messages: '已定位但没有消息 DOM',
  no_active_conversation: '已发现联系人但未读取当前聊天',
  unmatched: '未匹配岗位池',
  ambiguous: '岗位匹配歧义',
  not_loaded: '当前会话未加载',
  error: '读取失败',
}
const PLATFORM_STYLES: Record<string, string> = {
  boss: 'border-orange-200 bg-orange-50 text-orange-800',
  zhilian: 'border-blue-200 bg-blue-50 text-blue-800',
  liepin: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  '51job': 'border-slate-200 bg-slate-50 text-slate-700',
}

export default function ConversationsPage() {
  const [items, setItems] = useState<Conversation[]>([])
  const [sort, setSort] = useState<SortMode>('recent')
  const [notice, setNotice] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [syncingId, setSyncingId] = useState('')

  const load = async () => {
    const response = await fetch(`/api/conversations?sort=${sort}`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '会话加载失败')
    setItems(data.conversations || [])
  }

  const sync = async () => {
    setSyncing(true)
    setNotice('正在读取已打开的平台会话…')
    try {
      const response = await fetch('/api/conversations/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ platforms: ['boss', 'zhilian', 'liepin'] }) })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.error || '会话同步失败')
      const results = Array.isArray(data.results) ? data.results : []
      const failed = results.filter((item: { status?: string }) => !['synced', 'empty'].includes(item.status || '')).length
      const summary = results.map((item: { platform?: string; conversation_id?: string; status?: string; message_count?: number; inserted?: number }) => `${item.platform || '平台'}${item.conversation_id ? `·${item.conversation_id}` : ''}：${SYNC_STATUS_LABELS[item.status || ''] || item.status || '未知'}（读取 ${item.message_count || 0}，新增 ${item.inserted || 0}）`).join('；')
      setNotice(`${failed ? '同步部分完成' : '同步完成'}：仅处理本地会话卡片；${summary || '没有本地会话返回结果'}`)
      await load()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '会话同步失败')
    } finally {
      setSyncing(false)
    }
  }

  const syncOne = async (item: Conversation) => {
    setSyncingId(item.id)
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(item.id)}/sync`, { method: 'POST' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok && data.status !== 'not_loaded') throw new Error(data.error || '当前会话同步失败')
      setNotice(data.status === 'not_loaded' ? '当前 HR 会话未在已打开的平台页面中加载' : `已同步 ${data.message_count || 0} 条当前会话消息`)
      await load()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '当前会话同步失败')
    } finally {
      setSyncingId('')
    }
  }

  useEffect(() => { void load().catch(error => setNotice(error instanceof Error ? error.message : '会话加载失败')) }, [sort])

  const remove = async (item: Conversation) => {
    if (!window.confirm(`确定删除“${item.hr_name || '未命名 HR'}”的本地会话吗？\n\n只删除 AutoJobHunter 本地数据库内容，不会删除招聘平台上的聊天记录。`)) return
    const response = await fetch(`/api/conversations/${encodeURIComponent(item.id)}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation: 'DELETE_LOCAL_CONVERSATION' }) })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) { setNotice(data.error || '删除失败'); return }
    setItems(current => current.filter(candidate => candidate.id !== item.id))
    setNotice('本地会话及其消息已删除，招聘平台记录未改变')
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-2xl font-black">HR 会话中心</h2>
          <p className="mt-1 text-sm text-muted">按平台、公司、岗位和 HR 查看完整沟通上下文。</p>
        </div>
        <div className="flex items-center gap-3">
          <Button disabled={syncing} onClick={() => void sync()} title="同步已打开平台会话">
            <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
            {syncing ? '同步中…' : '同步已打开平台会话'}
          </Button>
          <label className="flex items-center gap-2 text-sm font-bold">
            <ArrowUpDown className="h-4 w-4 text-primary" />排序
            <select value={sort} onChange={event => setSort(event.target.value as SortMode)} className="rounded-xl border border-card-border bg-white px-3 py-2 font-normal">
              {Object.entries(SORT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(item => {
          const platform = item.platform || 'unknown'
          const platformLabel = PLATFORM_SHORT_LABELS[platform] || PLATFORM_LABELS[platform] || platform
          const platformClass = PLATFORM_STYLES[platform] || 'border-card-border bg-white text-muted'
          const hasMatchedJob = Boolean(item.job_id && (item.job_title || item.job_company))
          const jobTitle = hasMatchedJob ? (item.job_title || '岗位标题未记录') : '尚未匹配岗位池'
          const company = hasMatchedJob ? (item.job_company || item.company_id || '公司未记录') : '尚未匹配岗位池'
          return (
            <Card key={item.id} className="h-full transition hover:border-primary">
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <Link to={`/conversations/${encodeURIComponent(item.id)}`} className="min-w-0 flex-1">
                    <CardTitle><span className="flex items-center gap-2"><MessageCircle className="h-4 w-4 shrink-0 text-primary" />{item.hr_name || '未命名 HR'}</span></CardTitle>
                  </Link>
                  <span className={`shrink-0 rounded-full border px-2 py-1 text-xs font-bold ${platformClass}`}>{platformLabel}</span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="text-sm font-bold">{company}</div>
                  <div className="flex items-start gap-2 text-sm text-muted"><BriefcaseBusiness className="mt-0.5 h-4 w-4 shrink-0" /><span>{jobTitle}</span></div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted">
                    <span className="rounded-full bg-primary/10 px-2 py-1 font-bold text-primary">AI 评分：{typeof item.job_score === 'number' ? item.job_score : '未评分'}</span>
                    <span>消息 {item.message_count || 0} 条</span><span>状态：{item.status}</span>
                  </div>
                  {item.last_message_preview && <p className="line-clamp-2 text-sm leading-5 text-muted">{item.last_message_preview}</p>}
                  {item.last_sync_at && <div className="text-xs text-muted">最近同步：{item.last_sync_at}</div>}
                  <div className="flex flex-wrap items-center gap-2 pt-2">
                    <Button size="sm" variant="secondary" disabled={syncingId === item.id} onClick={() => void syncOne(item)}><RefreshCw className={`h-3.5 w-3.5 ${syncingId === item.id ? 'animate-spin' : ''}`} />{syncingId === item.id ? '同步中' : '同步当前会话'}</Button>
                    <Link to={`/conversations/${encodeURIComponent(item.id)}`}><Button size="sm" variant="ghost">查看本地会话</Button></Link>
                    {item.conversation_url ? <a href={item.conversation_url} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost" title="打开对应招聘平台的 HR 会话"><MessageCircle className="h-4 w-4" />打开平台 HR 对话</Button></a> : <Button size="sm" variant="ghost" disabled title={item.conversation_url_reason || '平台尚未返回具体 HR 会话地址'}><MessageCircle className="h-4 w-4" />HR 会话链接未就绪</Button>}
                    {item.job_url ? <a href={item.job_url} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost"><ExternalLink className="h-4 w-4" />查看平台岗位详情</Button></a> : <Button size="sm" variant="ghost" disabled title={item.job_url_reason || '尚未保存平台岗位详情地址'}><ExternalLink className="h-4 w-4" />岗位链接未就绪</Button>}
                    <Button className="ml-auto" variant="ghost" size="icon" title="删除本地会话" onClick={() => void remove(item)}><Trash2 className="h-4 w-4 text-danger" /></Button>
                  </div>
                  {['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human'].includes(item.status) && <div className="flex items-center gap-1 text-xs text-danger"><PauseCircle className="h-4 w-4" />等待人工确认</div>}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
      {!items.length && <Card><CardContent className="p-8 text-center text-muted">暂无 HR 会话</CardContent></Card>}
      {notice && <p className="text-sm text-primary">{notice}</p>}
    </div>
  )
}
