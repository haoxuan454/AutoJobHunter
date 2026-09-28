import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { CircleHelp } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type Count = { status?: string; platform?: string; sender_type?: string; count: number }
type DailyTrend = { day: string; deliveries: number; replied_conversations: number; outgoing_messages: number; incoming_messages: number }
type JobDirection = { label: string; conversations: number; replied_conversations: number; hr_messages: number; reply_rate: number }
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
  platform_metrics: PlatformMetric[]
  hr_question_keywords: Keyword[]
}

const PLATFORM_NAMES: Record<string, string> = { boss: 'BOSS 直聘', zhilian: '智联招聘', liepin: '猎聘', '51job': '前程无忧' }
const STATUS_NAMES: Record<string, string> = {
  new: '新会话', active: '活跃', waiting_reply: '等待 HR 回复', waiting_human: '等待人工确认',
  paused_salary: '薪资待确认', paused_manual: '人工暂停', paused_risk: '风控暂停',
  replied: 'HR 已回复', closed: '已关闭', failed: '失败',
}
const ROLE_NAMES: Record<string, string> = { user: '我方消息', hr: 'HR 消息', ai: 'AI 草稿', system: '平台/系统提示', unknown: '发送方未识别' }
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
    ...row, label: labelForPlatform(row.platform), reply_rate: Number(row.reply_rate || 0),
  })), [data])
  const directionChart = useMemo(() => (data?.job_directions || []).map(row => ({ ...row, name: row.label })), [data])

  if (loading && !data) return <div className="text-muted">正在加载真实分析数据…</div>
  if (error && !data) return <div className="rounded-xl bg-red-50 p-4 text-sm text-danger">{error}</div>
  if (!data) return null

  const cards = [
    ['HR 会话', data.conversations_total], ['消息总数', data.messages_total],
    ['已确认可引用经验', data.confirmed_public_facts], ['薪资人工接管', data.salary_paused],
  ] as const

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h2 className="text-2xl font-black">对话分析</h2><p className="mt-1 text-sm text-muted">分析范围：岗位池关联的本地会话与消息；不会扫描招聘平台，也不包含未关联岗位的旧记录。</p></div>
        <button className="rounded-lg border border-card-border px-3 py-2 text-sm font-bold text-primary hover:bg-primary/5" onClick={() => void load()}>刷新真实数据</button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">{cards.map(([title, value]) => <Card key={title}><CardHeader><CardTitle>{title}</CardTitle></CardHeader><CardContent><div className="text-3xl font-black">{value}</div></CardContent></Card>)}</div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="每日投递与回复趋势" help="横轴是本地确认记录的日期（按天汇总，不是预测区间）。投递会话按首次确认的我方发送或平台默认招呼记录计数；有回复会话按首次 HR 消息日期计数。消息曲线展示当天双方消息条数。历史补建会话优先使用岗位已发送记录中的日期。">
          {data.daily_trend.length ? <ResponsiveContainer width="100%" height={300}><LineChart data={data.daily_trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis allowDecimals={false} /><Tooltip /><Legend /><Line type="monotone" dataKey="deliveries" name="投递会话" stroke="#2563eb" strokeWidth={2} /><Line type="monotone" dataKey="replied_conversations" name="有回复会话" stroke="#10b981" strokeWidth={2} /><Line type="monotone" dataKey="outgoing_messages" name="我方消息" stroke="#f97316" /><Line type="monotone" dataKey="incoming_messages" name="HR 消息" stroke="#8b5cf6" /></LineChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
        <ChartCard title="各平台联系与回复表现" help="按招聘平台汇总本地已关联岗位的会话数与回复率。回复率=至少收到过一条 HR 消息的会话数÷该平台会话数；样本少时比例仅供参考。">
          {platformChart.length ? <ResponsiveContainer width="100%" height={300}><BarChart data={platformChart}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis yAxisId="left" allowDecimals={false} /><YAxis yAxisId="right" orientation="right" unit="%" /><Tooltip /><Legend /><Bar yAxisId="left" dataKey="conversations" name="会话数" fill="#2563eb" radius={[6, 6, 0, 0]} /><Bar yAxisId="right" dataKey="reply_rate" name="回复率 %" fill="#10b981" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartCard title="岗位方向会话分布" help="扇区大小和标注百分比表示各岗位方向在全部已关联会话中的占比，不是 HR 回复率。悬停可查看完整岗位名称、会话数和该方向的 HR 回复率；样本少时比例仅供参考。">
          {directionChart.length ? <ResponsiveContainer width="100%" height={320}><PieChart><Pie data={directionChart} dataKey="conversations" nameKey="name" cx="42%" cy="50%" outerRadius={105} labelLine={false} label={({ percent }) => `${Math.round((percent || 0) * 100)}%`}>{directionChart.map((entry, index) => <Cell key={`${entry.name}-${index}`} fill={COLORS[index % COLORS.length]} />)}</Pie><Tooltip formatter={(value: number, _name: string, item: any) => [`${value} 个会话 · HR 回复率 ${item.payload.reply_rate}%`, item.payload.name]} /><Legend layout="vertical" verticalAlign="middle" align="right" width={190} formatter={(value: string) => value.length > 14 ? `${value.slice(0, 14)}…` : value} /></PieChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
        <ChartCard title="岗位方向回复率排行" help="将同类数据改为可比较的岗位方向回复率排行；每条显示会话样本和回复率。它回答的是‘哪些岗位方向目前更常收到 HR 回复’，不是 AI 评分效果，也不代表未来保证。">
          {directionChart.length ? <ResponsiveContainer width="100%" height={320}><BarChart data={[...directionChart].sort((a, b) => b.reply_rate - a.reply_rate || b.conversations - a.conversations).slice(0, 10)} layout="vertical" margin={{ left: 12, right: 20 }}><CartesianGrid strokeDasharray="3 3" /><XAxis type="number" domain={[0, 100]} unit="%" /><YAxis type="category" dataKey="name" width={130} tickFormatter={value => String(value).length > 10 ? `${String(value).slice(0, 10)}…` : value} /><Tooltip formatter={(value: number, _name: string, item: any) => [`${value}% · ${item.payload.replied_conversations}/${item.payload.conversations} 个会话`, item.payload.name]} /><Bar dataKey="reply_rate" name="HR 回复率" fill="#10b981" radius={[0, 6, 6, 0]} /></BarChart></ResponsiveContainer> : <Empty />}
        </ChartCard>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Breakdown title="会话状态" help="会话目前处于什么处理阶段，可快速看到等待回复、人工确认或暂停的数量。" rows={data.by_status.map(row => ({ label: STATUS_NAMES[row.status || ''] || row.status || '未知状态', count: row.count }))} />
        <Breakdown title="消息构成" help="按消息记录中的发送角色统计条数，帮助区分 HR 来信、我方已发送内容和平台/历史系统事件。未发送的 AI 回复草稿单独保存在草稿表中，不计入本图。" rows={data.messages_by_sender.map(row => ({ label: ROLE_NAMES[row.sender_type || ''] || row.sender_type || '未知角色', count: row.count }))} />
        <Card><CardHeader><CardTitle>HR 高频问题/原话</CardTitle><p className="text-xs leading-5 text-muted">按相同原文出现次数从高到低排列；可在下方区域滚动查看更多。</p></CardHeader><CardContent><div className="max-h-72 space-y-2 overflow-y-auto pr-2">{data.hr_question_keywords.length ? data.hr_question_keywords.map((row, index) => <div key={`${row.content}-${index}`} className="flex items-start justify-between gap-3 rounded-lg bg-primary/5 px-3 py-2 text-sm"><span className="min-w-0 whitespace-pre-wrap break-words text-slate-700">{row.content}</span><span className="shrink-0 rounded-full bg-white px-2 py-0.5 text-xs font-bold text-primary">×{row.count}</span></div>) : <Empty />}</div></CardContent></Card>
      </div>
    </div>
  )
}

function ChartCard({ title, help, children }: { title: string; help: string; children: React.ReactNode }) {
  return <Card><CardHeader><div className="flex items-center gap-2"><CardTitle>{title}</CardTitle><span className="group relative inline-flex" tabIndex={0}><CircleHelp className="h-4 w-4 cursor-help text-muted" aria-label={`${title}分析说明`} /><span role="tooltip" className="pointer-events-none absolute left-0 top-6 z-20 hidden w-72 rounded-xl border border-card-border bg-white p-3 text-xs font-normal leading-5 text-slate-700 shadow-xl group-hover:block group-focus-within:block">{help}</span></span></div></CardHeader><CardContent>{children}</CardContent></Card>
}

function Empty() {
  return <div className="flex h-36 items-center justify-center text-sm text-muted">暂无真实数据</div>
}

function Breakdown({ title, help, rows }: { title: string; help: string; rows: { label: string; count: number }[] }) {
  return <Card><CardHeader><div className="flex items-center gap-2"><CardTitle>{title}</CardTitle><span className="group relative inline-flex" tabIndex={0}><CircleHelp className="h-4 w-4 cursor-help text-muted" aria-label={`${title}分析说明`} /><span role="tooltip" className="pointer-events-none absolute left-0 top-6 z-20 hidden w-72 rounded-xl border border-card-border bg-white p-3 text-xs font-normal leading-5 text-slate-700 shadow-xl group-hover:block group-focus-within:block">{help}</span></span></div></CardHeader><CardContent className="space-y-2">{rows.length ? rows.map(row => <div key={row.label} className="flex justify-between text-sm"><span>{row.label}</span><span className="font-bold">{row.count}</span></div>) : <Empty />}</CardContent></Card>
}
