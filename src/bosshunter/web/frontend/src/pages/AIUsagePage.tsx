import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type UsageRow = { purpose?: string; provider?: string; model?: string; calls: number; total_tokens: number; total_cost: number }
type Usage = { summary: { calls: number; input_tokens: number; output_tokens: number; total_tokens: number; estimated_calls: number; total_cost: number }; by_purpose: UsageRow[]; by_model: UsageRow[]; series: Array<{ bucket: string; calls: number; total_tokens: number; total_cost: number }> }

export default function AIUsagePage() {
  const [usage, setUsage] = useState<Usage | null>(null)
  const [granularity, setGranularity] = useState<'day' | 'hour'>('day')
  const [days, setDays] = useState('7')
  const [error, setError] = useState('')
  const load = async () => {
    const end = new Date()
    const start = new Date(end.getTime() - Number(days || 7) * 86400000)
    try { const response = await fetch(`/api/ai-usage?start=${encodeURIComponent(start.toISOString().slice(0, 19).replace('T', ' '))}&end=${encodeURIComponent(end.toISOString().slice(0, 19).replace('T', ' '))}&granularity=${granularity}`, { cache: 'no-store' }); const data = await response.json(); if (!response.ok) throw new Error(data.error || '读取模型消耗失败'); setUsage(data); setError('') } catch (cause) { setError(cause instanceof Error ? cause.message : '读取模型消耗失败') }
  }
  useEffect(() => { void load() }, [granularity, days])
  if (error) return <div className="rounded-xl bg-red-50 p-4 text-sm text-danger">{error}</div>
  if (!usage) return <div className="text-muted">正在加载模型消耗…</div>
  const summary = usage.summary
  return <div className="space-y-5">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-2xl font-black">AI Token 消耗</h2><p className="mt-1 text-sm text-muted">统计模型调用次数、输入/输出 Token、功能消耗和费用估算。不会保存提示词或回复正文。</p></div><div className="flex gap-2"><select value={days} onChange={e => setDays(e.target.value)} className="rounded-xl border border-card-border bg-white px-3 py-2 text-sm"><option value="1">最近 1 天</option><option value="7">最近 7 天</option><option value="30">最近 30 天</option><option value="90">最近 90 天</option></select><select value={granularity} onChange={e => setGranularity(e.target.value as 'day' | 'hour')} className="rounded-xl border border-card-border bg-white px-3 py-2 text-sm"><option value="day">按天</option><option value="hour">按小时</option></select><button onClick={() => void load()} className="rounded-xl bg-primary px-4 py-2 text-sm font-bold text-white">刷新</button></div></div>
    <div className="grid gap-4 md:grid-cols-4"><Metric title="调用次数" value={summary.calls} /><Metric title="总 Token" value={summary.total_tokens.toLocaleString()} /><Metric title="输入 / 输出" value={`${summary.input_tokens.toLocaleString()} / ${summary.output_tokens.toLocaleString()}`} /><Metric title="预计费用" value={summary.total_cost > 0 ? `$${summary.total_cost.toFixed(4)}` : '未配置价格'} /></div>
    {summary.estimated_calls > 0 && <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">其中 {summary.estimated_calls} 次没有从接口拿到 usage，Token 使用量为本地估算；费用需要在 AI 配置中填写每百万 Token 价格后才会计算。</div>}
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]"><Card><CardHeader><CardTitle>Token 消耗趋势</CardTitle></CardHeader><CardContent><div className="h-72"><ResponsiveContainer width="100%" height="100%"><LineChart data={usage.series}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="bucket" fontSize={11} /><YAxis /><Tooltip /><Line type="monotone" dataKey="total_tokens" name="总 Token" stroke="#6366f1" strokeWidth={3} /></LineChart></ResponsiveContainer></div></CardContent></Card><Card><CardHeader><CardTitle>功能调用次数</CardTitle></CardHeader><CardContent><div className="h-72"><ResponsiveContainer width="100%" height="100%"><BarChart data={usage.by_purpose}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="purpose" angle={-25} textAnchor="end" height={70} fontSize={11} /><YAxis /><Tooltip /><Bar dataKey="calls" name="调用次数" fill="#10b981" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div></CardContent></Card></div>
    <div className="grid gap-4 md:grid-cols-2"><Card><CardHeader><CardTitle>按功能消耗</CardTitle></CardHeader><CardContent className="space-y-3">{usage.by_purpose.length ? usage.by_purpose.map(row => <div key={row.purpose} className="flex items-center justify-between rounded-xl bg-[#FFFCFA] p-3 text-sm"><span className="font-bold">{row.purpose}</span><span>{row.calls} 次 · {Number(row.total_tokens || 0).toLocaleString()} Token</span></div>) : <p className="text-sm text-muted">暂无模型调用记录</p>}</CardContent></Card><Card><CardHeader><CardTitle>按模型 / 服务商</CardTitle></CardHeader><CardContent className="space-y-3">{usage.by_model.length ? usage.by_model.map(row => <div key={`${row.provider}-${row.model}`} className="flex items-center justify-between rounded-xl bg-[#FFFCFA] p-3 text-sm"><span className="font-bold">{row.model || row.provider || '未标识模型'}</span><span>{row.calls} 次 · {Number(row.total_tokens || 0).toLocaleString()} Token</span></div>) : <p className="text-sm text-muted">暂无模型调用记录</p>}</CardContent></Card></div>
  </div>
}

function Metric({ title, value }: { title: string; value: string | number }) { return <Card><CardHeader className="pb-2"><CardTitle>{title}</CardTitle></CardHeader><CardContent><div className="text-2xl font-black">{value}</div></CardContent></Card> }
