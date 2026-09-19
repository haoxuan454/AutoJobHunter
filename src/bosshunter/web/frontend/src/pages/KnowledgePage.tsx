import { useEffect, useState } from 'react'
import { CheckCircle2, FileText, Trash2, Upload, ShieldCheck } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Fact = { id: number; title: string; content: string; fact_status: string; public_allowed: number }
type Document = { id: number; original_name: string; parse_status: string; created_at: string; file_size: number }

export default function KnowledgePage() {
  const [facts, setFacts] = useState<Fact[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [notice, setNotice] = useState('')
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [expandedFactId, setExpandedFactId] = useState<number | null>(null)

  const refresh = async () => {
    const [documentsResponse, factsResponse] = await Promise.all([
      fetch('/api/knowledge/documents'),
      fetch('/api/knowledge/facts'),
    ])
    setDocuments((await documentsResponse.json()).documents || [])
    setFacts((await factsResponse.json()).facts || [])
  }

  useEffect(() => { void refresh() }, [])

  const upload = async (file?: File) => {
    if (!file) return
    const body = new FormData()
    body.append('file', file)
    const response = await fetch('/api/knowledge/documents/upload', { method: 'POST', body })
    const data = await response.json()
    setNotice(data.error || `已解析 ${data.facts_created || 0} 条经验事实`)
    if (response.ok) await refresh()
  }

  const deleteDocument = async (document: Document) => {
    if (!window.confirm(`确定删除“${document.original_name}”吗？该资料及其解析出的经验事实都会被删除。`)) return
    setDeletingId(document.id)
    try {
      const response = await fetch(`/api/knowledge/documents/${document.id}`, { method: 'DELETE' })
      const data = await response.json()
      setNotice(response.ok ? `已删除 ${document.original_name}` : (data.error || '删除失败'))
      if (response.ok) await refresh()
    } finally {
      setDeletingId(null)
    }
  }

  const confirmFact = async (fact: Fact) => {
    await fetch(`/api/knowledge/facts/${fact.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fact_status: 'confirmed', public_allowed: true }),
    })
    await refresh()
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col justify-between gap-4 rounded-3xl border border-primary/15 bg-gradient-to-br from-[#FFF1E6] via-white to-[#FFF9F4] p-5 md:flex-row md:items-center">
        <div className="flex items-start gap-3">
          <div className="rounded-2xl bg-primary p-3 text-white shadow-lg shadow-primary/20"><ShieldCheck className="h-6 w-6" /></div>
          <div><h2 className="text-2xl font-black">个人知识库</h2><p className="mt-1 text-sm text-muted">上传真实经历，确认后 AI 才能引用；错误资料可以随时删除。</p></div>
        </div>
        <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-bold text-white shadow-md shadow-primary/20 transition hover:bg-primary/90">
          <Upload className="h-4 w-4" />上传资料
          <input hidden type="file" accept=".md,.txt,.docx,.xlsx,.pdf" onChange={e => void upload(e.target.files?.[0])} />
        </label>
      </div>
      {notice && <div className="rounded-xl border border-primary/15 bg-[#FFF0E5] p-3 text-sm text-primary" role="status">{notice}</div>}

      <Card>
        <CardHeader><CardTitle className="flex items-center justify-between"><span>已上传资料</span><span className="rounded-full bg-[#FFF0E5] px-2.5 py-1 text-xs font-black text-primary">{documents.length} 份</span></CardTitle></CardHeader>
        <CardContent>
          {documents.length === 0 ? <p className="rounded-2xl border border-dashed p-8 text-center text-sm text-muted">还没有资料，上传简历之外的项目经历、工作复盘或技术文档。</p> : <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{documents.map(document => (
            <div key={document.id} className="group flex items-start gap-3 rounded-2xl border border-card-border bg-[#FFFCFA] p-4 transition hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
              <div className="rounded-xl bg-white p-2 text-primary shadow-sm"><FileText className="h-5 w-5" /></div>
              <div className="min-w-0 flex-1"><div className="truncate font-bold" title={document.original_name}>{document.original_name}</div><div className="mt-1 text-xs text-muted">{document.parse_status} · {(document.file_size / 1024).toFixed(1)} KB</div></div>
              <Button type="button" variant="ghost" size="icon" className="shrink-0 text-danger" title="删除资料" aria-label={`删除 ${document.original_name}`} disabled={deletingId === document.id} onClick={() => void deleteDocument(document)}><Trash2 className="h-4 w-4" /></Button>
            </div>
          ))}</div>}
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle className="flex items-center justify-between"><span>经验事实</span><span className="rounded-full bg-[#F1F8F4] px-2.5 py-1 text-xs font-black text-success">{facts.length} 条</span></CardTitle></CardHeader><CardContent><div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{facts.length === 0 && <p className="col-span-full text-sm text-muted">上传资料后，解析出的经验事实会显示在这里。</p>}{facts.map(fact => { const expanded = expandedFactId === fact.id; return <div key={fact.id} className="rounded-2xl border border-card-border bg-[#FFFCFA] p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="truncate font-bold" title={fact.title}>{fact.title}</div><div className="mt-1 text-xs text-muted">{fact.fact_status === 'confirmed' ? '已确认，可供 AI 使用' : '待确认'}</div></div>{fact.fact_status === 'confirmed' ? <CheckCircle2 className="h-4 w-4 shrink-0 text-success" /> : <Button size="sm" onClick={() => void confirmFact(fact)}>确认使用</Button>}</div><p className={`mt-3 whitespace-pre-wrap text-sm leading-6 text-muted ${expanded ? '' : 'line-clamp-4'}`}>{fact.content}</p><button type="button" className="mt-3 text-xs font-bold text-primary hover:underline" onClick={() => setExpandedFactId(expanded ? null : fact.id)}>{expanded ? '收起内容' : '预览全部内容'}</button></div> })}</div></CardContent></Card>
    </div>
  )
}
