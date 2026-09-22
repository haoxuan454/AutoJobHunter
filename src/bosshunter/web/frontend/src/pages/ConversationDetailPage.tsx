import { Link, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Message = { id: number; sender_type: string; content: string; message_time?: string }
type Draft = { id: number; draft_text: string; status: string; created_at: string }
type Conversation = { id: string; hr_name: string; status: string; platform?: string; company_id?: string; job_id?: string; pause_reason?: string }
type Detail = { conversation: Conversation; messages: Message[]; drafts: Draft[] }
const PAUSED = ['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human']

export default function ConversationDetailPage() {
  const { id = '' } = useParams(); const [data, setData] = useState<Detail | null>(null); const [notice, setNotice] = useState('')
  const refresh = () => fetch(`/api/conversations/${encodeURIComponent(id)}`).then(r => r.json()).then(setData)
  useEffect(() => { void refresh() }, [id])
  const resume = async () => { if (!window.confirm('确认恢复这个 HR 会话的自动化处理吗？恢复后新的 HR 消息可以重新进入 AI 分析流程。')) return; const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'active', reason: '用户人工恢复' }) }); if (!response.ok) { setNotice('恢复失败'); return } await refresh(); setNotice('会话已恢复，后续新消息可以重新进入处理流程') }
  const copy = async (text: string) => { await navigator.clipboard?.writeText(text); setNotice('草稿已复制，可由你人工粘贴到招聘平台发送') }
  if (!data) return <div className="text-muted">正在加载会话…</div>
  return <div className="space-y-5"><Link className="text-sm text-primary" to="/conversations">← 返回会话列表</Link><Card><CardHeader><CardTitle>{data.conversation.hr_name || '未命名 HR'} · {data.conversation.status}</CardTitle><div className="text-sm text-muted">{data.conversation.platform || '未知平台'} · {data.conversation.company_id || '未记录公司'} · {data.conversation.job_id || '未记录岗位'}</div></CardHeader><CardContent>{data.conversation.pause_reason && <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{data.conversation.pause_reason}</div>}{PAUSED.includes(data.conversation.status) && <Button size="sm" onClick={() => void resume()}>人工确认后恢复自动化</Button>}<div className="mt-4 max-h-[560px] space-y-3 overflow-y-auto rounded-2xl bg-[#FFFCFA] p-4">{data.messages.map(m => <div key={m.id} className={`max-w-[86%] rounded-xl p-3 ${m.sender_type === 'hr' ? 'bg-[#FFF0E5]' : 'ml-auto bg-gray-50'}`}><div className="mb-1 text-xs font-bold text-muted">{m.sender_type === 'hr' ? 'HR' : '求职者'} · {m.message_time || ''}</div><div className="whitespace-pre-wrap text-sm leading-6">{m.content}</div></div>)}{data.messages.length === 0 && <div className="p-6 text-center text-muted">暂无消息</div>}</div></CardContent></Card><Card><CardHeader><CardTitle>回复草稿（仅供人工审核）</CardTitle></CardHeader><CardContent className="space-y-3">{data.drafts.map(d => <div key={d.id} className="rounded-xl border border-card-border p-3"><div className="mb-2 text-xs text-muted">{d.status} · {d.created_at}</div><p className="whitespace-pre-wrap text-sm leading-6">{d.draft_text}</p><Button className="mt-3" size="sm" onClick={() => void copy(d.draft_text)}>复制草稿</Button></div>)}{data.drafts.length === 0 && <div className="text-sm text-muted">暂无草稿</div>}{notice && <div className="text-sm text-primary">{notice}</div>}</CardContent></Card></div>
}
