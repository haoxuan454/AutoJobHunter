import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { MessageCircle, PauseCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Conversation = { id: string; hr_name: string; company_url?: string; company_id?: string; job_id?: string; status: string; last_message_at?: string; pause_reason?: string }
export default function ConversationsPage() {
  const [items, setItems] = useState<Conversation[]>([])
  useEffect(() => { fetch('/api/conversations').then(r => r.json()).then(d => setItems(d.conversations || [])) }, [])
  return <div className="space-y-5"><div><h2 className="text-2xl font-black">HR 会话中心</h2><p className="mt-1 text-sm text-muted">每个 HR 独立会话，消息只增量入库，不自动发送。</p></div><div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map(item => <Link key={item.id} to={`/conversations/${item.id}`}><Card className="h-full transition hover:border-primary"><CardHeader><CardTitle><span className="flex items-center gap-2"><MessageCircle className="h-4 w-4 text-primary" />{item.hr_name || '未命名 HR'}</span></CardTitle></CardHeader><CardContent><div className="text-sm">会话：{item.id}</div><div className="mt-2 text-xs text-muted">状态：{item.status}</div>{item.status === 'paused_salary' && <div className="mt-3 flex items-center gap-1 text-xs text-danger"><PauseCircle className="h-4 w-4" />等待人工处理</div>}</CardContent></Card></Link>)}</div>{items.length === 0 && <Card><CardContent className="p-8 text-center text-muted">暂无 HR 会话。可通过 API 或后续平台同步创建。</CardContent></Card>}</div>
}
