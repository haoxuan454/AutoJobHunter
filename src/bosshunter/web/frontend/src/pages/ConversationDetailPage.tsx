import { Link, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Message = { id: number; sender_type: string; content: string; message_time?: string }
type Conversation = { id: string; hr_name: string; status: string; pause_reason?: string }
export default function ConversationDetailPage() {
  const { id = '' } = useParams(); const [data, setData] = useState<{conversation: Conversation; messages: Message[]} | null>(null)
  useEffect(() => { fetch(`/api/conversations/${id}`).then(r => r.json()).then(setData) }, [id])
  if (!data) return <div className="text-muted">正在加载会话…</div>
  return <div className="space-y-5"><Link className="text-sm text-primary" to="/conversations">← 返回会话列表</Link><Card><CardHeader><CardTitle>{data.conversation.hr_name || '未命名 HR'} · {data.conversation.status}</CardTitle></CardHeader><CardContent>{data.conversation.pause_reason && <div className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{data.conversation.pause_reason}</div>}<div className="space-y-3">{data.messages.map(m => <div key={m.id} className={`rounded-xl p-3 ${m.sender_type === 'hr' ? 'bg-[#FFF0E5]' : 'bg-gray-50'}`}><div className="mb-1 text-xs font-bold text-muted">{m.sender_type} · {m.message_time || ''}</div><div className="whitespace-pre-wrap text-sm leading-6">{m.content}</div></div>)}</div>{data.messages.length === 0 && <div className="p-6 text-center text-muted">暂无消息</div>}</CardContent></Card></div>
}
