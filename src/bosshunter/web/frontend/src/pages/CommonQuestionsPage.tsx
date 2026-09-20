import { useEffect, useState } from 'react'
import { BrainCircuit, Check, ListChecks, Pencil, RefreshCw, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

type CommonQuestion = { id: number; question: string; answer: string; occurrence_count: number; updated_at: string }

export default function CommonQuestionsPage() {
  const [questions, setQuestions] = useState<CommonQuestion[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState({ question: '', answer: '' })
  const readJson = async (response: Response) => { const text = await response.text(); try { return JSON.parse(text) } catch { throw new Error(response.ok ? '服务器返回了无法解析的数据' : `共性问题接口不可用（HTTP ${response.status}），请重启项目服务`) } }
  const load = async () => { try { const response = await fetch('/api/common-questions'); const data = await readJson(response); setQuestions(data.questions || []) } catch (error) { setNotice(error instanceof Error ? error.message : '读取共性问题失败') } }
  useEffect(() => { void load() }, [])
  const summarize = async () => { setBusy(true); try { const response = await fetch('/api/common-questions/summarize', { method: 'POST' }); const data = await readJson(response); if (!response.ok) throw new Error(data.error || '汇总失败'); setQuestions(data.questions || []); setNotice(`已完成增量汇总，本次处理 ${data.count || 0} 条`)} catch (error) { setNotice(error instanceof Error ? error.message : '汇总失败') } finally { setBusy(false) } }
  const remove = async (id: number) => { if (!window.confirm('确定从数据库删除这条共性问题吗？')) return; const response = await fetch(`/api/common-questions/${id}`, { method: 'DELETE' }); if (response.ok) { setQuestions(items => items.filter(item => item.id !== id)); setNotice('已从数据库删除') } else { setNotice('删除失败，请检查服务是否为最新版本') } }
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
    <div className="rounded-3xl border border-teal-100 bg-teal-50/60 p-5"><div className="flex flex-wrap items-center justify-between gap-4"><div className="flex items-start gap-3"><div className="rounded-2xl bg-teal-600 p-3 text-white"><ListChecks className="h-6 w-6" /></div><div><h2 className="text-2xl font-black">共性问题库</h2><p className="mt-1 text-sm text-muted">只保存脱敏后的 HR 问题与回复，不保存公司、姓名、薪资和会话标识。</p></div></div><Button onClick={() => void summarize()} disabled={busy}><RefreshCw className={`mr-2 h-4 w-4 ${busy ? 'animate-spin' : ''}`} />{busy ? '汇总中' : '手动增量汇总'}</Button></div></div>
    {notice && <div className="rounded-xl bg-[#FFF0E5] p-3 text-sm text-primary">{notice}</div>}
    <div className="grid gap-4 md:grid-cols-2">{questions.map(item => <article key={item.id} className="rounded-3xl border border-card-border bg-white p-5 shadow-sm">{editingId === item.id ? <div className="space-y-3"><input value={draft.question} onChange={e => setDraft({ ...draft, question: e.target.value })} className="w-full rounded-xl border border-card-border p-3 text-sm font-bold outline-none focus:border-teal-500" placeholder="HR 问题" /><textarea value={draft.answer} onChange={e => setDraft({ ...draft, answer: e.target.value })} className="min-h-32 w-full rounded-xl border border-card-border p-3 text-sm leading-6 outline-none focus:border-teal-500" placeholder="参考回复" /><div className="flex justify-end gap-2"><Button variant="secondary" size="sm" onClick={cancelEdit}><X className="mr-1 h-4 w-4" />取消</Button><Button size="sm" onClick={() => void saveEdit()} disabled={busy}><Check className="mr-1 h-4 w-4" />保存到数据库</Button></div></div> : <><div className="flex items-start justify-between gap-3"><div className="flex gap-2"><BrainCircuit className="mt-1 h-5 w-5 shrink-0 text-teal-600" /><h3 className="font-black leading-6">{item.question}</h3></div><div className="flex gap-2"><Button variant="secondary" size="sm" onClick={() => beginEdit(item)} aria-label="编辑共性问题"><Pencil className="h-4 w-4" /></Button><Button variant="secondary" size="sm" onClick={() => void remove(item.id)} aria-label="删除共性问题"><Trash2 className="h-4 w-4 text-danger" /></Button></div></div><div className="mt-4 rounded-2xl bg-[#FFFCFA] p-4 text-sm leading-6 text-foreground">{item.answer}</div><div className="mt-3 flex justify-between text-xs text-muted"><span>累计命中 {item.occurrence_count} 次</span><span>{item.updated_at}</span></div></>}</article>)}{!questions.length && <div className="col-span-full rounded-3xl border border-dashed border-card-border bg-white p-10 text-center text-sm text-muted">暂无共性问题。先在“AI 回复演练”中模拟几轮，再点击手动增量汇总。</div>}</div>
  </div>
}
