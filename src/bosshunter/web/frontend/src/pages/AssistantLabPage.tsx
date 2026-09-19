import { useEffect, useState } from 'react'
import { Bot, FlaskConical, Send, ShieldCheck, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'

type LabMessage = { id: number; sender_type: 'hr' | 'ai'; content: string }
type LabFact = { id: number; title: string; content: string }

export default function AssistantLabPage() {
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<LabMessage[]>([])
  const [facts, setFacts] = useState<LabFact[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    fetch('/api/assistant-lab/session').then(res => res.json()).then(data => {
      setSessionId(data.session?.id || ''); setMessages(data.messages || [])
    }).catch(() => setNotice('无法读取本地演练沙盒'))
  }, [])

  const submit = async () => {
    if (!text.trim() || busy) return
    setBusy(true); setNotice('正在读取已确认经历并生成本地草稿...')
    try {
      const res = await fetch('/api/assistant-lab/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sessionId, content: text }) })
      const data = await res.json(); if (!res.ok) throw new Error(data.error || '演练失败')
      setSessionId(data.session.id); setMessages(data.messages || []); setFacts(data.retrieved_facts || []); setText('')
      setNotice(`已生成本地草稿（${data.generation_mode === 'configured_model' ? '统一模型' : '本地证据模板'}），未发送`)
    } catch (error) { setNotice(error instanceof Error ? error.message : '演练失败') }
    finally { setBusy(false) }
  }

  const reset = async () => {
    const res = await fetch('/api/assistant-lab/reset', { method: 'POST' }); const data = await res.json()
    setSessionId(data.session?.id || ''); setMessages(data.messages || []); setFacts([]); setNotice('演练会话已清空，仅清空沙盒')
  }

  return <div className="space-y-4">
    <div className="rounded-3xl border border-indigo-100 bg-indigo-50/60 p-5">
      <div className="flex items-start gap-3"><div className="rounded-2xl bg-indigo-600 p-3 text-white"><FlaskConical className="h-5 w-5" /></div><div><h2 className="text-xl font-black">AI 回复演练</h2><p className="mt-1 text-sm text-muted">模拟 HR 提问，观察模型如何结合你已确认的个人经历生成回复。</p></div></div>
      <div className="mt-4 flex items-center gap-2 rounded-2xl border border-indigo-200 bg-white px-3 py-2 text-xs text-indigo-700"><ShieldCheck className="h-4 w-4" />严格本地沙盒：不打开 Chrome、不连接 BOSS、不发送任何消息、不写入真实 HR 会话</div>
    </div>
    <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
      <section className="rounded-3xl border border-card-border bg-white p-5"><div className="mb-4 flex items-center justify-between"><h3 className="font-black">模拟 HR 会话</h3><Button variant="secondary" size="sm" onClick={reset}>清空演练</Button></div><div className="min-h-[360px] space-y-3 rounded-2xl bg-[#FFFCFA] p-4">{messages.map(item => <div key={item.id} className={`flex gap-2 ${item.sender_type === 'ai' ? 'justify-end' : ''}`}><div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 ${item.sender_type === 'ai' ? 'bg-indigo-600 text-white' : 'border border-card-border bg-white'}`}><div className="mb-1 flex items-center gap-1 text-[11px] font-bold opacity-70">{item.sender_type === 'ai' ? <><Bot className="h-3 w-3" />AI 草稿</> : <><UserRound className="h-3 w-3" />模拟 HR</>}</div>{item.content}</div></div>)}{!messages.length && <p className="py-28 text-center text-sm text-muted">输入一个 HR 问题开始演练，例如“你之前用 Python 做过什么？”</p>}</div><div className="mt-3 flex gap-2"><textarea value={text} onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void submit() } }} placeholder="输入模拟 HR 的问题，Enter 发送，Shift+Enter 换行" className="min-h-20 flex-1 rounded-2xl border border-card-border p-3 text-sm outline-none focus:border-indigo-500" /><Button onClick={() => void submit()} disabled={busy || !text.trim()}><Send className="mr-2 h-4 w-4" />{busy ? '生成中' : '演练'}</Button></div>{notice && <p className="mt-3 text-xs text-indigo-700">{notice}</p>}</section>
      <aside className="rounded-3xl border border-card-border bg-white p-5"><h3 className="font-black">本轮回复依据</h3><p className="mt-1 text-xs text-muted">只展示确认且允许对外使用的个人事实。</p><div className="mt-4 space-y-3">{facts.map(fact => <div key={fact.id} className="rounded-2xl bg-emerald-50 p-3"><div className="text-sm font-bold text-emerald-800">{fact.title}</div><p className="mt-1 line-clamp-4 text-xs leading-5 text-emerald-900/80">{fact.content}</p></div>)}{!facts.length && <p className="text-sm text-muted">发送问题后显示命中的经历。</p>}</div><div className="mt-6 rounded-2xl bg-slate-50 p-3 text-xs leading-5 text-muted"><b>sent: false</b><br />演练结果只保存在 data/sandbox/autojobhunter-sandbox.db。</div></aside>
    </div>
  </div>
}
