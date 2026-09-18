import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Count = { status?: string; platform?: string; sender_type?: string; count: number }
type Analytics = {
  conversations_total: number
  messages_total: number
  confirmed_public_facts: number
  salary_paused: number
  by_status: Count[]
  messages_by_sender: Count[]
  by_platform: Count[]
}

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    fetch('/api/conversations/analytics')
      .then(response => response.ok ? response.json() : Promise.reject(new Error('load failed')))
      .then(setData)
      .catch(() => setError('暂时无法读取分析数据'))
  }, [])
  if (error) return <div className="rounded-xl bg-red-50 p-4 text-sm text-danger">{error}</div>
  if (!data) return <div className="text-muted">正在加载分析数据…</div>
  const cards = [['HR 会话', data.conversations_total], ['消息总数', data.messages_total], ['已确认可引用经验', data.confirmed_public_facts], ['薪资人工接管', data.salary_paused]]
  return <div className="space-y-5">
    <div><h2 className="text-2xl font-black">对话分析</h2><p className="mt-1 text-sm text-muted">统计来自本地真实会话与知识库记录。</p></div>
    <div className="grid gap-4 md:grid-cols-4">{cards.map(([title, value]) => <Card key={title}><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><div className="text-3xl font-black">{value}</div></CardContent></Card>)}</div>
    <div className="grid gap-4 md:grid-cols-3"><Breakdown title="按状态" rows={data.by_status.map(row => ({ label: row.status || '', count: row.count }))} /><Breakdown title="按平台" rows={data.by_platform.map(row => ({ label: row.platform || '', count: row.count }))} /><Breakdown title="按消息角色" rows={data.messages_by_sender.map(row => ({ label: row.sender_type || '', count: row.count }))} /></div>
  </div>
}

function Breakdown({ title, rows }: { title: string; rows: { label: string; count: number }[] }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2">{rows.length ? rows.map(row => <div key={row.label} className="flex justify-between text-sm"><span>{row.label}</span><span className="font-bold">{row.count}</span></div>) : <div className="text-sm text-muted">暂无数据</div>}</CardContent></Card>
}
