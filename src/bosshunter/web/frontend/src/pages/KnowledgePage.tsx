import { useEffect, useState } from 'react'
import { CheckCircle2, FileText, Upload } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Fact = { id: number; title: string; content: string; fact_status: string; public_allowed: number }
type Document = { id: number; original_name: string; parse_status: string; created_at: string; file_size: number }

export default function KnowledgePage() {
  const [facts, setFacts] = useState<Fact[]>([])
  const [documents, setDocuments] = useState<Document[]>([])
  const [notice, setNotice] = useState('')
  const refresh = async () => {
    const [d, f] = await Promise.all([fetch('/api/knowledge/documents'), fetch('/api/knowledge/facts')])
    setDocuments((await d.json()).documents || [])
    setFacts((await f.json()).facts || [])
  }
  useEffect(() => { void refresh() }, [])
  const upload = async (file?: File) => {
    if (!file) return
    const body = new FormData(); body.append('file', file)
    const response = await fetch('/api/knowledge/documents/upload', { method: 'POST', body })
    const data = await response.json(); setNotice(data.error || `已解析 ${data.facts_created || 0} 条经验事实`); if (response.ok) await refresh()
  }
  const confirmFact = async (fact: Fact) => {
    await fetch(`/api/knowledge/facts/${fact.id}`, { method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ fact_status: 'confirmed', public_allowed: true }) })
    await refresh()
  }
  return <div className="space-y-5">
    <div className="flex items-center justify-between"><div><h2 className="text-2xl font-black">个人知识库</h2><p className="mt-1 text-sm text-muted">上传真实经历，确认后才允许 AI 对外引用。</p></div><label className="inline-flex cursor-pointer items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-bold text-white"><Upload className="h-4 w-4" />上传资料<input hidden type="file" accept=".md,.txt,.docx,.xlsx,.pdf" onChange={e => void upload(e.target.files?.[0])} /></label></div>
    {notice && <div className="rounded-xl bg-[#FFF0E5] p-3 text-sm text-primary">{notice}</div>}
    <Card><CardHeader><CardTitle>已上传资料（{documents.length}）</CardTitle></CardHeader><CardContent><div className="grid gap-3 md:grid-cols-3">{documents.map(d => <div key={d.id} className="rounded-xl border border-card-border p-3"><FileText className="mb-2 h-5 w-5 text-primary" /><div className="font-bold">{d.original_name}</div><div className="text-xs text-muted">{d.parse_status} · {d.file_size} bytes</div></div>)}</div></CardContent></Card>
    <Card><CardHeader><CardTitle>经验事实（{facts.length}）</CardTitle></CardHeader><CardContent><div className="space-y-3">{facts.map(f => <div key={f.id} className="rounded-xl border border-card-border p-4"><div className="flex items-center justify-between gap-3"><div className="font-bold">{f.title}</div>{f.fact_status === 'confirmed' ? <span className="flex items-center gap-1 text-xs text-success"><CheckCircle2 className="h-4 w-4" />已确认</span> : <Button size="sm" onClick={() => void confirmFact(f)}>确认可对外使用</Button>}</div><p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-muted">{f.content}</p></div>)}</div></CardContent></Card>
  </div>
}
