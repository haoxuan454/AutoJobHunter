import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Count = { status?: string; platform?: string; sender_type?: string; count: number }
type DailyTrend = { day: string; deliveries: number; replied_conversations: number; outgoing_messages: number; incoming_messages: number }
type JobDirection = { label: string; conversations: number; hr_messages: number }
type ScoreReplyRate = { score_range: string; conversations: number; replied_conversations: number }
type PlatformMetric = { platform: string; conversations: number; replied_conversations: number; reply_rate: number }
type Keyword = { content: string; count: number }
type Analytics = {
  conversations_total: number
  messages_total: number
  confirmed_public_facts: number
  salary_paused: number
  by_status: Count[]
  messages_by_sender: Count[]
  by_platform: Count[]
  daily_trend: DailyTrend[]
  job_directions: JobDirection[]
  score_reply_rate: ScoreReplyRate[]
  platform_metrics: PlatformMetric[]
  hr_question_keywords: Keyword[]
}

const PLATFORM_NAMES: Record<string, string> = { boss: 'BOSS 直聘', zhilian: '智联招聘', liepin: '猎聘', '51job': '前程无忧' }
const COLORS = ['#f97316', '#2563eb', '#10b981', '#64748b', '#8b5cf6', '#ec4899']

const labelForPlatform = (value: string) => PLATFORM_NAMES[value] || value || '未知平台'

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const response = await fetch('/api/conversations/analytics')
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || '分析数据加载失败')
      setData(payload as Analytics)
      setError('')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '暂时无法读取分析数据')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const platformChart = useMemo(() => (data?.platform_metrics || []).map(row => ({
    ...row,
    label: labelForPlatform(row.platform),
    reply_rate: Number(row.reply_rate || 0),
  })), [data])
  const directionChart = useMemo(() => (data?.job_directions || []).map(row => ({ ...row, name: row.label })), [data])
  const scoreChart = useMemo(() => (data?.score_reply_rate || []).map(row => ({
    ...row,
    reply_rate: row.conversations ? Math.round(row.replied_conversations * 1000 / row.conversations) / 10 : 0,
  })), [data])

  if (loading && !data) return <div className="text-muted">正在加载真实分析数据…</div>
  if (error && !data) return <div className="rounded-xl bg-red-50 p-4 text-sm text-danger">{error}</div>
  if (!data) return null

  const cards = [
    ['HR 会话', data.conversations_total],
    ['消息总数', data.messages_total],
    ['已确认可引用经验', data.confirmed_public_facts],
    ['薪资人工接管', data.salary_paused],
  ] as const

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-2xl font-black">对话分析</h2><p className="mt-1 text-sm text-muted">所有图表均来自本地已持久化的岗位、会话与消息，不填充模拟数据。</p></div>
        <button className="rounded-lg border border-card-border px-3 py-2 text-sm font-bold text-primary hover:bg-primary/5" onClick={() => void load()}>刷新真实数据</button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">{cards.map(([title, value]) => <Card key={title}><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><div className="text-3xl font-black">{value}</div></CardContent></Card>)}</div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="每日投递与回复趋势">
          {data.daily_trend.length ? <ResponsiveContainer width="100%" height={300}><LineChart data={data.daily_trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Line type="monotone" dataKey="deliveries" name="投递会话" stroke="#2563eb" strokeWidth={2} /><Line type="monotone" dataKey="replied_conversations" name="有回复会话" stroke="#10b981" strokeWidth={2} /><Line type="monotone" dataKey="outgoing_messages" name="我方消息" stroke="#f97316" /><Line type="monotone" dataKey="incoming_messages" name="HR 消息" stroke="#8b5cf6" /></LineChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
        <ChartCard title="平台投递量与回复率">
          {platformChart.length ? <ResponsiveContainer width="100%" height={300}><BarChart data={platformChart}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis yAxisId="left" allowDecimals={false} /><YAxis yAxisId="right" orientation="right" unit="%" /><Tooltip /><Legend /><Bar yAxisId="left" dataKey="conversations" name="会话数" fill="#2563eb" radius={[6, 6, 0, 0]} /><Bar yAxisId="right" dataKey="reply_rate" name="回复率 %" fill="#10b981" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="岗位方向分布">
          {directionChart.length ? <ResponsiveContainer width="100%" height={300}><PieChart><Pie data={directionChart} dataKey="conversations" nameKey="name" cx="50%" cy="50%" outerRadius={105} label>{directionChart.map((entry, index) => <Cell key={`${entry.name}-${index}`} fill={COLORS[index % COLORS.length]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
        <ChartCard title="AI 评分区间与 HR 回复率">
          {scoreChart.length ? <ResponsiveContainer width="100%" height={300}><BarChart data={scoreChart}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="score_range" /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Bar dataKey="conversations" name="会话数" fill="#8b5cf6" radius={[6, 6, 0, 0]} /><Bar dataKey="replied_conversations" name="有回复会话" fill="#10b981" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Breakdown title="按会话状态" rows={data.by_status.map(row => ({ label: row.status || '', count: row.count }))} />
        <Breakdown title="按消息角色" rows={data.messages_by_sender.map(row => ({ label: row.sender_type || '', count: row.count }))} />
        <Card><CardHeader><CardTitle>HR 高频问题/原话</CardTitle></CardHeader><CardContent className="flex min-h-36 flex-wrap content-start gap-2">{data.hr_question_keywords.length ? data.hr_question_keywords.map((row, index) => <span key={`${row.content}-${index}`} className="rounded-full bg-primary/10 px-3 py-1.5 text-sm text-primary" style={{ fontSize: `${Math.min(18, 12 + Math.min(row.count, 6))}px` }}>{row.content} <small className="font-bold">×{row.count}</small></span>) : <Empty />}</CardContent></Card>
      </div>
    </div>
  )
}

function ChartCard({ title, children }: { title: string; children: React.ReactNode }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent>{children}</CardContent></Card>
}

function Empty() {
  return <div className="flex h-36 items-center justify-center text-sm text-muted">暂无真实数据</div>
}

function Breakdown({ title, rows }: { title: string; rows: { label: string; count: number }[] }) {
  return <Card><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent className="space-y-2">{rows.length ? rows.map(row => <div key={row.label} className="flex justify-between text-sm"><span>{row.label}</span><span className="font-bold">{row.count}</span></div>) : <Empty />}</CardContent></Card>
}
