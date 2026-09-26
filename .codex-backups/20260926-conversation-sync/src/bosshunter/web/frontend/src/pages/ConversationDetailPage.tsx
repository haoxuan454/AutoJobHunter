import { Link, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { BriefcaseBusiness, ExternalLink, RefreshCw } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { PLATFORM_LABELS, PLATFORM_SHORT_LABELS } from '@/lib/platforms'

type Message = { id: number; sender_type: string; content: string; message_time?: string; is_ai_generated?: number; is_sent?: number; raw_payload_json?: string }
type Draft = { id: number; draft_text: string; status: string; created_at: string }
type Conversation = { id: string; hr_name: string; hr_title?: string; status: string; platform?: string; company_id?: string; job_id?: string; conversation_url?: string; conversation_url_reason?: string; job_url?: string; job_url_reason?: string; hr_profile_url?: string; company_url?: string; pause_reason?: string; job_title?: string; job_company?: string; job_score?: number; job_score_reason?: string; job_status?: string; message_count?: number }
type Detail = { conversation: Conversation; messages: Message[]; drafts: Draft[] }
const PAUSED = ['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human']
const PLATFORM_STYLES: Record<string, string> = { boss: 'border-orange-200 bg-orange-50 text-orange-800', zhilian: 'border-blue-200 bg-blue-50 text-blue-800', liepin: 'border-emerald-200 bg-emerald-50 text-emerald-800' }

export default function ConversationDetailPage() {
  const { id = '' } = useParams()
  const [data, setData] = useState<Detail | null>(null)
  const [notice, setNotice] = useState('')
  const [syncing, setSyncing] = useState(false)
  const refresh = () => fetch(`/api/conversations/${encodeURIComponent(id)}`).then(r => r.json()).then(setData)
  useEffect(() => { void refresh() }, [id])
  const sync = async () => {
    setSyncing(true)
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/sync`, { method: 'POST' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok && payload.status !== 'not_loaded') throw new Error(payload.error || '同步失败')
      const status = String(payload.status || '')
      const statusLabel: Record<string, string> = { not_loaded: '当前会话未在已打开的平台页面中加载，旧消息已保留', empty_messages: '已定位当前平台会话，但没有读取到真实聊天消息，旧消息已保留', unmatched: '当前平台会话未能唯一匹配岗位池，未写入新会话', ambiguous: '当前平台会话匹配到多个岗位，未写入新会话', synced: `已读取 ${payload.message_count || 0} 条平台消息` }
      setNotice(statusLabel[status] || (response.ok ? `同步完成，读取 ${payload.message_count || 0} 条平台消息` : payload.error || '同步失败'))
      await refresh()
    } catch (error) { setNotice(error instanceof Error ? error.message : '同步失败') } finally { setSyncing(false) }
  }
  const resume = async () => { if (!window.confirm('确认恢复这个 HR 会话的自动化处理吗？恢复后新的 HR 消息可以重新进入 AI 分析流程。')) return; const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'active', reason: '用户人工恢复' }) }); if (!response.ok) { setNotice('恢复失败'); return } await refresh(); setNotice('会话已恢复，后续新消息可以重新进入处理流程') }
  const copy = async (text: string) => { await navigator.clipboard?.writeText(text); setNotice('草稿已复制，可由你人工粘贴到招聘平台发送') }
  if (!data) return <div className="text-muted">正在加载会话…</div>
  const conversation = data.conversation
  const platform = conversation.platform || 'unknown'
  const senderLabel: Record<string, string> = { hr: 'HR', user: '我', ai: 'AI 草稿', system: '平台系统' }
  return <div className="space-y-5">
    <Link className="text-sm text-primary" to="/conversations">← 返回会话列表</Link>
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><CardTitle>{conversation.hr_name || '未命名 HR'}</CardTitle><div className="mt-1 text-sm text-muted">{conversation.hr_title || '招聘联系人'} · {conversation.status}</div></div>
          <span className={`rounded-full border px-3 py-1 text-xs font-bold ${PLATFORM_STYLES[platform] || 'border-card-border bg-white text-muted'}`}>{PLATFORM_SHORT_LABELS[platform] || PLATFORM_LABELS[platform] || platform}</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 rounded-xl border border-card-border bg-[#FFFCFA] p-4 text-sm md:grid-cols-2">
          <div><span className="text-muted">公司：</span><strong>{conversation.job_company || conversation.company_id || '尚未匹配岗位池'}</strong></div>
          <div><span className="text-muted">岗位：</span><strong>{conversation.job_title || '尚未匹配岗位池'}</strong></div>
          <div><span className="text-muted">AI 评分：</span><strong className="text-primary">{typeof conversation.job_score === 'number' ? conversation.job_score : '岗位匹配后显示'}</strong></div>
          <div><span className="text-muted">消息：</span><strong>{data.messages.length} 条</strong></div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" disabled={syncing} onClick={() => void sync()}><RefreshCw className={`h-4 w-4 ${syncing ? 'animate-spin' : ''}`} />{syncing ? '同步中…' : '同步当前会话'}</Button>
          {conversation.conversation_url ? <a href={conversation.conversation_url} target="_blank" rel="noreferrer"><Button size="sm" variant="secondary"><ExternalLink className="h-4 w-4" />打开平台 HR 对话</Button></a> : <Button size="sm" variant="secondary" disabled title={conversation.conversation_url_reason || '平台尚未返回具体 HR 会话地址'}><ExternalLink className="h-4 w-4" />HR 会话链接未就绪</Button>}
          {conversation.job_url ? <a href={conversation.job_url} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost"><BriefcaseBusiness className="h-4 w-4" />查看平台岗位详情</Button></a> : <Button size="sm" variant="ghost" disabled title={conversation.job_url_reason || '尚未保存平台岗位详情地址'}><BriefcaseBusiness className="h-4 w-4" />岗位链接未就绪</Button>}
        </div>
        {conversation.pause_reason && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{conversation.pause_reason}</div>}
        {PAUSED.includes(conversation.status) && <Button className="mt-4" size="sm" onClick={() => void resume()}>人工确认后恢复自动化</Button>}
        <div className="mt-4 max-h-[560px] space-y-3 overflow-y-auto rounded-2xl bg-[#FFFCFA] p-4">
          {data.messages.map(message => <div key={message.id} className={`max-w-[86%] rounded-xl p-3 ${message.sender_type === 'hr' ? 'bg-[#FFF0E5]' : message.sender_type === 'system' ? 'mx-auto bg-slate-100' : 'ml-auto bg-gray-50'}`}><div className="mb-1 text-xs font-bold text-muted">{senderLabel[message.sender_type] || message.sender_type} · {message.message_time || ''}{message.is_ai_generated ? ' · AI 生成' : ''}{message.is_sent ? ' · 已发送' : ''}</div><div className="whitespace-pre-wrap text-sm leading-6">{message.content}</div></div>)}
          {data.messages.length === 0 && <div className="p-6 text-center text-muted">暂无已持久化消息。请确认平台当前打开的是目标 HR 的聊天面板；同步不会导航、点击、滚动或发送消息。</div>}
        </div>
        {notice && <div className="mt-3 text-sm text-primary">{notice}</div>}
      </CardContent>
    </Card>
    <Card><CardHeader><CardTitle>回复草稿（仅供人工审核）</CardTitle></CardHeader><CardContent className="space-y-3">{data.drafts.map(d => <div key={d.id} className="rounded-xl border border-card-border p-3"><div className="mb-2 text-xs text-muted">{d.status} · {d.created_at}</div><p className="whitespace-pre-wrap text-sm leading-6">{d.draft_text}</p><Button className="mt-3" size="sm" onClick={() => void copy(d.draft_text)}>复制草稿</Button></div>)}{data.drafts.length === 0 && <div className="text-sm text-muted">暂无草稿</div>}</CardContent></Card>
  </div>
}
