import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpDown, MessageCircle, PauseCircle, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type SortMode = 'recent' | 'frequency' | 'created'
type Conversation = { id: string; hr_name: string; platform?: string; company_id?: string; job_id?: string; status: string; last_message_at?: string; round_count?: number; last_message_preview?: string }
const SORT_LABELS: Record<SortMode, string> = { recent: '最近聊天', frequency: '对话最频繁', created: '创建时间' }

export default function ConversationsPage() {
  const [items, setItems] = useState<Conversation[]>([])
  const [sort, setSort] = useState<SortMode>('recent')
  const [notice, setNotice] = useState('')
  const load = async () => { const response = await fetch(`/api/conversations?sort=${sort}`); const data = await response.json(); if (!response.ok) throw new Error(data.error || '会话加载失败'); setItems(data.conversations || []) }
  useEffect(() => { void load().catch(error => setNotice(error instanceof Error ? error.message : '会话加载失败')) }, [sort])
  const remove = async (item: Conversation) => {
    if (!window.confirm(`确定删除“${item.hr_name || '未命名 HR'}”的本地会话吗？\n\n只删除 AutoJobHunter 本地数据库内容，不会删除招聘平台上的聊天记录。`)) return
    const response = await fetch(`/api/conversations/${encodeURIComponent(item.id)}`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmation: 'DELETE_LOCAL_CONVERSATION' }) })
    const data = await response.json().catch(() => ({})); if (!response.ok) { setNotice(data.error || '删除失败'); return }
    setItems(current => current.filter(candidate => candidate.id !== item.id)); setNotice('本地会话及其消息已删除，招聘平台记录未改变')
  }
  return <div className="space-y-5"><div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-2xl font-black">HR 会话中心</h2><p className="mt-1 text-sm text-muted">每个平台、公司、岗位和 HR 都使用独立会话上下文。</p></div><label className="flex items-center gap-2 text-sm font-bold"><ArrowUpDown className="h-4 w-4 text-primary" />排序<select value={sort} onChange={event => setSort(event.target.value as SortMode)} className="rounded-xl border border-card-border bg-white px-3 py-2 font-normal">{Object.entries(SORT_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map(item => <Card key={item.id} className="h-full transition hover:border-primary"><CardHeader><div className="flex items-start justify-between gap-3"><Link to={`/conversations/${encodeURIComponent(item.id)}`} className="min-w-0 flex-1"><CardTitle><span className="flex items-center gap-2"><MessageCircle className="h-4 w-4 shrink-0 text-primary" />{item.hr_name || '未命名 HR'}</span></CardTitle></Link><Button variant="ghost" size="icon" title="删除本地会话" onClick={() => void remove(item)}><Trash2 className="h-4 w-4 text-danger" /></Button></div></CardHeader><CardContent><Link to={`/conversations/${encodeURIComponent(item.id)}`} className="block"><div className="text-sm">{item.company_id || '未记录公司'} · {item.job_id || '未记录岗位'}</div><div className="mt-2 flex flex-wrap gap-2 text-xs text-muted"><span>平台：{item.platform || '未记录'}</span><span>状态：{item.status}</span><span>对话 {item.round_count || 0} 轮</span></div>{item.last_message_at && <div className="mt-2 text-xs text-muted">最近：{item.last_message_at}</div>}{item.last_message_preview && <p className="mt-3 line-clamp-2 text-sm leading-5 text-muted">{item.last_message_preview}</p>}{['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human'].includes(item.status) && <div className="mt-3 flex items-center gap-1 text-xs text-danger"><PauseCircle className="h-4 w-4" />等待人工确认</div>}</Link></CardContent></Card>)}</div>{!items.length && <Card><CardContent className="p-8 text-center text-muted">暂无 HR 会话</CardContent></Card>}{notice && <p className="text-sm text-primary">{notice}</p>}</div>
}
