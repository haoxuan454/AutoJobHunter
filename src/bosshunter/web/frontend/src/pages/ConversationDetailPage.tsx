import { Link, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Message = { id: number; sender_type: string; content: string; message_time?: string }
type Draft = { id: number; draft_text: string; status: string; created_at: string }
type Conversation = { id: string; hr_name: string; status: string; pause_reason?: string }
type Detail = { conversation: Conversation; messages: Message[]; drafts: Draft[] }

export default function ConversationDetailPage() {
  const { id = '' } = useParams(); const [data, setData] = useState<Detail | null>(null); const [notice, setNotice] = useState('')
  const refresh = () => fetch(`/api/conversations/${id}`).then(r => r.json()).then(setData)
  useEffect(() => { void refresh() }, [id])
  const resume = async () => { await fetch(`/api/conversations/${id}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'active', reason: '用户人工恢复' }) }); await refresh() }
  const copy = async (text: string) => { await navigator.clipboard?.writeText(text); setNotice('草稿已复制，可由你人工粘贴到招聘平台发送') }
  if (!data) return <div className="text-muted">正在加载会话…</div>
  return <div className="space-y-5"><Link className="text-sm text-primary" to="/conversations">← 返回会话列表</Link><Card><CardHeader><CardTitle>{data.conversation.hr_name || '未命名 HR'} · {data.conversation.status}</CardTitle></CardHeader><CardContent>{data.conversation.pause_reason && <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{data.conversation.pause_reason}</div>}{data.conversation.status === 'paused_salary' && <Button size="sm" onClick={() => void resume()}>人工确认后恢复会话</Button>}<div className="mt-4 space-y-3">{data.messages.map(m => <div key={m.id} className={`rounded-xl p-3 ${m.sender_type === 'hr' ? 'bg-[#FFF0E5]' : 'bg-gray-50'}`}><div className="mb-1 text-xs font-bold text-muted">{m.sender_type} · {m.message_time || ''}</div><div className="whitespace-pre-wrap text-sm leading-6">{m.content}</div></div>)}</div>{data.messages.length === 0 && <div className="p-6 text-center text-muted">暂无消息</div>}</CardContent></Card><Card><CardHeader><CardTitle>回复草稿（仅供人工审核）</CardTitle></CardHeader><CardContent className="space-y-3">{data.drafts.map(d => <div key={d.id} className="rounded-xl border border-card-border p-3"><div className="mb-2 text-xs text-muted">{d.status} · {d.created_at}</div><p className="whitespace-pre-wrap text-sm leading-6">{d.draft_text}</p><Button className="mt-3" size="sm" onClick={() => void copy(d.draft_text)}>复制草稿</Button></div>)}{data.drafts.length === 0 && <div className="text-sm text-muted">暂无草稿</div>}{notice && <div className="text-sm text-primary">{notice}</div>}</CardContent></Card></div>
}
