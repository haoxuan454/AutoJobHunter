import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, FileSearch, RefreshCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

type LogItem = { source: string; line: string; line_number: number }
type LogResponse = { items: LogItem[]; page: number; page_size: number; total: number; has_more: boolean; truncated: boolean }

export default function LogsPage() {
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('all')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<LogResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const params = new URLSearchParams({ source, page: String(page), page_size: '50' })
      if (query.trim()) params.set('query', query.trim())
      const response = await fetch(`/api/logs?${params.toString()}`)
      const body = await response.json()
      if (!response.ok) throw new Error(body.error || '读取日志失败')
      setData(body)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '读取日志失败')
    } finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [source, page, query])
  useEffect(() => { setPage(1) }, [source, query])

  return <div className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="flex items-center gap-2 text-2xl font-black"><FileSearch className="h-6 w-6 text-primary" />运行日志</h2><p className="mt-1 text-sm text-muted">查看服务、任务、浏览器和投递错误。敏感凭据会自动脱敏，日志按最新优先展示。</p></div>
      <Button variant="secondary" onClick={() => void load()} disabled={loading}><RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />刷新</Button>
    </div>
    <Card><CardContent className="flex flex-col gap-3 pt-5 md:flex-row md:items-center">
      <label className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><input aria-label="模糊搜索日志" value={query} onChange={event => setQuery(event.target.value)} placeholder="按错误、岗位、平台或任务模糊搜索" className="w-full rounded-xl border border-card-border bg-[#FFFCFA] py-2.5 pl-9 pr-3 text-sm outline-none focus:border-primary" /></label>
      <select aria-label="日志来源" value={source} onChange={event => setSource(event.target.value)} className="rounded-xl border border-card-border bg-white px-3 py-2.5 text-sm"><option value="all">全部来源</option><option value="web.err">服务错误</option><option value="web.out">服务运行</option><option value="task">任务日志</option></select>
    </CardContent></Card>
    {error && <div className="rounded-xl bg-red-50 p-4 text-sm text-danger">{error}</div>}
    {data?.truncated && <div className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">日志过多，仅读取最近一段内容；请先缩小搜索范围或翻页查看。</div>}
    <Card><CardHeader><CardTitle className="flex items-center justify-between"><span>日志明细</span><span className="text-xs font-normal text-muted">共 {data?.total || 0} 条 · 最新在前</span></CardTitle></CardHeader><CardContent>
      <div className="max-h-[62vh] overflow-auto rounded-xl border border-card-border bg-slate-950 p-3 font-mono text-xs leading-6 text-slate-100">{loading && !data ? <div className="text-slate-400">正在读取…</div> : data?.items.length ? data.items.map((item, index) => <div key={`${item.source}-${item.line_number}-${index}`} className="whitespace-pre-wrap border-b border-slate-800 py-1 last:border-0"><span className="mr-3 text-sky-300">[{item.source}]</span>{item.line}</div>) : <div className="text-slate-400">当前没有匹配的日志。</div>}</div>
      <div className="mt-4 flex items-center justify-between text-sm"><span>第 {data?.page || page} 页</span><div className="flex gap-2"><Button variant="secondary" size="sm" disabled={page <= 1 || loading} onClick={() => setPage(value => value - 1)}><ChevronLeft className="mr-1 h-4 w-4" />上一页</Button><Button variant="secondary" size="sm" disabled={!data?.has_more || loading} onClick={() => setPage(value => value + 1)}>下一页<ChevronRight className="ml-1 h-4 w-4" /></Button></div></div>
    </CardContent></Card>
  </div>
}
