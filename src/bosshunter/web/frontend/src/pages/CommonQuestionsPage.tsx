import { useEffect, useState } from 'react'
import { BrainCircuit, Check, ChevronDown, ChevronUp, Eye, ListChecks, Pencil, RefreshCw, Search, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

type CommonQuestion = { id: number; question: string; answer: string; occurrence_count: number; updated_at: string }
type SortMode = 'occurrence' | 'updated'

export default function CommonQuestionsPage() {
  const [questions, setQuestions] = useState<CommonQuestion[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortMode>('occurrence')
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState({ question: '', answer: '' })

  const readJson = async (response: Response) => {
    const text = await response.text()
    try { return JSON.parse(text) } catch { throw new Error(response.ok ? '服务器返回了无法解析的数据' : `共性问题接口不可用（HTTP ${response.status}）`) }
  }

  const load = async (nextQuery = query, nextSort = sort) => {
    try {
      const params = new URLSearchParams({ sort: nextSort })
      if (nextQuery.trim()) params.set('q', nextQuery.trim())
      const response = await fetch(`/api/common-questions?${params.toString()}`)
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error || '读取共性问题失败')
      setQuestions(data.questions || [])
    } catch (error) { setNotice(error instanceof Error ? error.message : '读取共性问题失败') }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => { void load() }, 220)
    return () => window.clearTimeout(timer)
  }, [query, sort])

  const toggleExpanded = (id: number) => {
    setExpandedIds(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  const summarize = async () => {
    setBusy(true)
    try {
      const response = await fetch('/api/common-questions/summarize', { method: 'POST' })
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error || '汇总失败')
      await load(); setNotice(`已完成增量汇总，本次处理 ${data.count || 0} 条`)
    } catch (error) { setNotice(error instanceof Error ? error.message : '汇总失败') }
    finally { setBusy(false) }
  }

  const remove = async (id: number) => {
    if (!window.confirm('确定从数据库删除这条共性问题吗？')) return
    const response = await fetch(`/api/common-questions/${id}`, { method: 'DELETE' })
    if (response.ok) { setQuestions(items => items.filter(item => item.id !== id)); setNotice('已从数据库删除') }
    else setNotice('删除失败，请检查服务是否为最新版本')
  }

  const beginEdit = (item: CommonQuestion) => { setEditingId(item.id); setDraft({ question: item.question, answer: item.answer }); setNotice('') }
  const cancelEdit = () => { setEditingId(null); setDraft({ question: '', answer: '' }) }

  const saveEdit = async () => {
    if (editingId === null) return
    setBusy(true)
    try {
      const response = await fetch(`/api/common-questions/${editingId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(draft) })
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error || '保存失败')
      setQuestions(items => items.map(item => item.id === editingId ? data.question : item))
      cancelEdit(); setNotice('已同步保存到数据库')
    } catch (error) { setNotice(error instanceof Error ? error.message : '保存失败') }
    finally { setBusy(false) }
  }

  return <div className="space-y-5">
    <div className="rounded-3xl border border-teal-100 bg-teal-50/60 p-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-start gap-3"><div className="rounded-2xl bg-teal-600 p-3 text-white"><ListChecks className="h-6 w-6" /></div><div><h2 className="text-2xl font-black">共性问题库</h2><p className="mt-1 text-sm text-muted">只保留脱敏后的 HR 问题与回复，不保存公司、姓名、薪资和会话标识。</p></div></div>
        <Button onClick={() => void summarize()} disabled={busy}><RefreshCw className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`} />{busy ? '汇总中' : '手动增量汇总'}</Button>
      </div>
    </div>
    <div className="flex flex-col gap-3 rounded-2xl border border-card-border bg-white p-4 shadow-sm md:flex-row md:items-center">
      <label className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" /><input value={query} onChange={event => setQuery(event.target.value)} className="w-full rounded-xl border border-card-border bg-[#FFFCFA] py-2.5 pl-9 pr-3 text-sm outline-none focus:border-teal-500" placeholder="按 HR 提问内容模糊搜索" aria-label="搜索共性问题" /></label>
      <label className="flex shrink-0 items-center gap-2 text-sm font-bold text-muted"><span>排序</span><select value={sort} onChange={event => setSort(event.target.value as SortMode)} className="rounded-xl border border-card-border bg-white px-3 py-2 font-normal text-foreground" aria-label="共性问题排序"><option value="occurrence">累计命中次数（高到低）</option><option value="updated">最新同步时间</option></select></label>
    </div>
    {notice && <div className="rounded-xl bg-[#FFF0E5] p-3 text-sm text-primary">{notice}</div>}
    <div className="grid auto-rows-fr gap-4 md:grid-cols-2">
      {questions.map(item => {
        const expanded = expandedIds.has(item.id)
        return <article key={item.id} className="flex h-full min-w-0 flex-col rounded-3xl border border-card-border bg-white p-5 shadow-sm">
          {editingId === item.id ? <div className="space-y-3"><input value={draft.question} onChange={e => setDraft({ ...draft, question: e.target.value })} className="w-full rounded-xl border border-card-border p-3 text-sm font-bold outline-none focus:border-teal-500" placeholder="HR 问题" /><textarea value={draft.answer} onChange={e => setDraft({ ...draft, answer: e.target.value })} className="min-h-32 w-full rounded-xl border border-card-border p-3 text-sm leading-6 outline-none focus:border-teal-500" placeholder="参考回复" /><div className="flex justify-end gap-2"><Button variant="secondary" size="sm" onClick={cancelEdit}><X className="mr-1 h-4 w-4" />取消</Button><Button size="sm" onClick={() => void saveEdit()} disabled={busy}><Check className="mr-1 h-4 w-4" />保存到数据库</Button></div></div> : <>
            <div className="flex min-h-12 items-start justify-between gap-3"><div className="flex min-w-0 gap-2"><BrainCircuit className="mt-1 h-5 w-5 shrink-0 text-teal-600" /><h3 className="line-clamp-2 min-w-0 font-black leading-6">{item.question}</h3></div><div className="flex shrink-0 gap-2"><Button variant="secondary" size="sm" onClick={() => beginEdit(item)} aria-label="编辑共性问题" title="编辑"><Pencil className="h-4 w-4" /></Button><Button variant="secondary" size="sm" onClick={() => void remove(item.id)} aria-label="删除共性问题" title="删除"><Trash2 className="h-4 w-4 text-danger" /></Button></div></div>
            <div className={`mt-4 overflow-hidden rounded-2xl bg-[#FFFCFA] p-4 text-sm leading-6 text-foreground ${expanded ? '' : 'line-clamp-4 h-24'}`}>{item.answer}</div>
            <Button variant="ghost" size="sm" className="mt-2 w-full justify-center text-teal-700 hover:bg-teal-50" onClick={() => toggleExpanded(item.id)}>{expanded ? <><ChevronUp className="mr-1 h-4 w-4" />收起内容</> : <><Eye className="mr-1 h-4 w-4" />预览全部内容<ChevronDown className="ml-1 h-4 w-4" /></>}</Button>
            <div className="mt-auto flex justify-between pt-3 text-xs text-muted"><span>累计命中 {item.occurrence_count} 次</span><span>{item.updated_at}</span></div>
          </>}
        </article>
      })}
      {!questions.length && <div className="col-span-full rounded-3xl border border-dashed border-card-border bg-white p-10 text-center text-sm text-muted">{query ? '没有匹配的共性问题' : '暂无共性问题。先在 AI 回复演练中模拟几轮，再点击手动增量汇总。'}</div>}
    </div>
  </div>
}
