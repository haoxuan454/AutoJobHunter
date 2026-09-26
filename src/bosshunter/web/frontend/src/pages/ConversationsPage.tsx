import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowUpDown,
  BriefcaseBusiness,
  MessageCircle,
  PauseCircle,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type SortMode = 'recent' | 'frequency' | 'created'

type Conversation = {
  id: string
  hr_name?: string
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
  job_url_reason?: string
  conversation_url?: string
  job_score?: number
  job_status?: string
  has_unread?: number | boolean
  unread_count?: number
}

type SyncResult = {
  platform?: string
  conversation_id?: string
  status?: string
  message_count?: number
  inserted?: number
  history_complete?: boolean
  history_label?: string
}

const SORT_LABELS: Record<SortMode, string> = {
  recent: '最近活跃',
  frequency: '对话最频繁',
  created: '创建时间',
}

const PLATFORM_LABELS: Record<string, string> = {
  boss: 'BOSS 直聘',
  zhilian: '智联招聘',
  liepin: '猎聘',
  '51job': '前程无忧',
}

const PLATFORM_STYLES: Record<string, string> = {
  boss: 'border-orange-200 bg-orange-50 text-orange-800',
  zhilian: 'border-blue-200 bg-blue-50 text-blue-800',
  liepin: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  '51job': 'border-slate-200 bg-slate-50 text-slate-700',
}

const SYNC_STATUS_LABELS: Record<string, string> = {
  synced: '已同步',
  empty: '已定位，暂无新消息',
  empty_messages: '已定位但未读到聊天消息',
  no_active_conversation: '没有可同步的本地会话',
  unmatched: '未匹配到对应岗位',
  ambiguous: '匹配到多个候选，未写入',
  scan_incomplete: '会话列表仍在加载，扫描未完成，未写入',
  not_loaded: '目标聊天当前未加载',
  risk_blocked: '平台安全验证拦截',
  error: '读取失败',
}

function displayHrName(name?: string) {
  const value = String(name || '').trim()
  return value && value !== '未命名 HR' ? value : 'HR 信息待平台同步'
}

function hasUnread(item: Conversation) {
  return Boolean(item.has_unread) || Number(item.unread_count || 0) > 0
}

function syncStatusLabel(status?: string) {
  return SYNC_STATUS_LABELS[status || ''] || status || '待同步'
}

export default function ConversationsPage() {
  const [items, setItems] = useState<Conversation[]>([])
  const [sort, setSort] = useState<SortMode>('recent')
  const [notice, setNotice] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [syncingId, setSyncingId] = useState('')

  const load = async () => {
    const response = await fetch(`/api/conversations?sort=${sort}`)
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.error || '会话加载失败')
    setItems(data.conversations || [])
  }

  const sync = async () => {
    setSyncing(true)
    setNotice('正在同步本地会话卡片对应的平台聊天…')
    try {
      const response = await fetch('/api/conversations/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platforms: ['boss', 'zhilian', 'liepin'] }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.error || '会话同步失败')
      const results = Array.isArray(data.results) ? data.results as SyncResult[] : []
      const failed = results.filter(item => !['synced', 'empty'].includes(item.status || '')).length
      const summary = results
        .map(item => `${PLATFORM_LABELS[item.platform || ''] || item.platform || '平台'}：${syncStatusLabel(item.status)}（消息 ${item.message_count || 0}，新增 ${item.inserted || 0}）`)
        .join('；')
      setNotice(`${failed ? '同步部分完成' : '同步完成'}：${summary || '没有本地会话返回结果'}`)
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
      const historyNote = typeof data.history_complete === 'boolean'
        ? (data.history_complete ? '，已到达平台可读取的历史边界' : '，平台未确认历史边界，当前展示已加载消息')
        : ''
      setNotice(`${displayHrName(item.hr_name)}：${syncStatusLabel(data.status)}，读取 ${data.message_count || 0} 条平台消息${historyNote}`)
      await load()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '当前会话同步失败')
    } finally {
      setSyncingId('')
    }
  }

  useEffect(() => {
    void load().catch(error => setNotice(error instanceof Error ? error.message : '会话加载失败'))
  }, [sort])

  const remove = async (item: Conversation) => {
    if (!window.confirm(`确定删除“${displayHrName(item.hr_name)}”的本地会话吗？\n\n只删除本地数据库内容，不会删除招聘平台上的聊天记录。`)) return
    const response = await fetch(`/api/conversations/${encodeURIComponent(item.id)}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirmation: 'DELETE_LOCAL_CONVERSATION' }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) {
      setNotice(data.error || '删除失败')
      return
    }
    setNotice('本地会话已删除；后续同步不会自动恢复这张卡片')
    await load()
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-primary">已投递岗位的本地会话投影</p>
          <h2 className="text-2xl font-black">HR 会话中心</h2>
          <p className="mt-1 text-sm text-muted">这里只展示岗位池中已确认投递成功的 HR，不会自动导入平台上的陌生联系人。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-muted">
            <ArrowUpDown className="h-4 w-4" />
            <select value={sort} onChange={event => setSort(event.target.value as SortMode)} className="rounded-xl border border-card-border bg-white px-3 py-2 font-normal">
              {Object.entries(SORT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <Button disabled={syncing} onClick={() => void sync()} title="只同步会话中心已有卡片对应的已打开平台会话">
            <RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />
            <span>{syncing ? '同步中…' : '同步已打开平台会话'}</span>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map(item => {
          const platform = item.platform || 'unknown'
          const platformLabel = PLATFORM_LABELS[platform] || platform
          const platformClass = PLATFORM_STYLES[platform] || 'border-card-border bg-white text-muted'
          const hasMatchedJob = Boolean(item.job_id && (item.job_title || item.job_company))
          const jobTitle = hasMatchedJob ? item.job_title || '岗位标题待同步' : '岗位信息待岗位池关联'
          const company = hasMatchedJob ? item.job_company || item.company_id || '公司信息待同步' : '公司信息待岗位池关联'
          const unread = hasUnread(item)

          return (
            <Card key={item.id} className={`h-full transition hover:border-primary ${unread ? 'border-red-200 shadow-[0_0_0_1px_rgba(239,68,68,0.08)]' : ''}`}>
              <CardHeader>
                <div className="flex items-start justify-between gap-3">
                  <Link to={`/conversations/${encodeURIComponent(item.id)}`} className="min-w-0 flex-1">
                    <CardTitle>
                      <span className="flex items-center gap-2">
                        <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
                          <MessageCircle className="h-4 w-4 text-primary" />
                          {unread && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-white" aria-label={`${item.unread_count || 1} 条未读消息`} />}
                        </span>
                        <span className="truncate">{displayHrName(item.hr_name)}</span>
                        {unread && <span className="shrink-0 rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-600">{item.unread_count || '新'}</span>}
                      </span>
                    </CardTitle>
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
                    <span>消息 {item.message_count || 0} 条</span>
                    <span>状态：{item.status}</span>
                  </div>
                  {item.last_message_preview && <p className="line-clamp-2 text-sm leading-5 text-muted">{item.last_message_preview}</p>}
                  {item.last_sync_at && <div className="text-xs text-muted">最近同步：{item.last_sync_at}</div>}
                  <div className="flex flex-wrap items-center gap-2 pt-2">
                    <Button className="gap-2" size="sm" variant="secondary" disabled={syncingId === item.id} onClick={() => void syncOne(item)}>
                      <RefreshCw className={`h-3.5 w-3.5 ${syncingId === item.id ? 'animate-spin' : ''}`} />
                      <span>{syncingId === item.id ? '同步中' : '同步当前会话'}</span>
                    </Button>
                    <Link to={`/conversations/${encodeURIComponent(item.id)}`}>
                      <Button className="gap-2" size="sm" variant="ghost"><MessageCircle className="h-3.5 w-3.5" /><span>查看本地会话</span></Button>
                    </Link>
                    {item.job_url ? (
                      <a href={item.job_url} target="_blank" rel="noreferrer">
                        <Button className="gap-2" size="sm" variant="ghost"><BriefcaseBusiness className="h-3.5 w-3.5" /><span>查看平台岗位详情</span></Button>
                      </a>
                    ) : (
                      <Button size="sm" variant="ghost" disabled title={item.job_url_reason || '尚未保存平台岗位详情地址'}>
                        <BriefcaseBusiness className="h-3.5 w-3.5" /><span>岗位链接未就绪</span>
                      </Button>
                    )}
                    <Button className="ml-auto" variant="ghost" size="icon" title="删除本地会话" onClick={() => void remove(item)}>
                      <Trash2 className="h-4 w-4 text-danger" />
                    </Button>
                  </div>
                  {['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human'].includes(item.status) && <div className="flex items-center gap-1 text-xs text-danger"><PauseCircle className="h-4 w-4" /><span>等待人工确认</span></div>}
                </div>
              </CardContent>
            </Card>
          )
        })}
      </div>
      {!items.length && <Card><CardContent className="p-8 text-center text-muted">暂无已确认投递的 HR 会话</CardContent></Card>}
      {notice && <p className="text-sm text-primary">{notice}</p>}
    </div>
  )
}
