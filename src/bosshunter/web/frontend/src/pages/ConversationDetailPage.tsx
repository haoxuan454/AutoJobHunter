import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowDown, BriefcaseBusiness, ExternalLink, Send, Sparkles, Trash2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Message = {
  id: number
  sender_type: string
  content: string
  message_time?: string | null
  created_at?: string | null
  is_ai_generated?: number
  is_sent?: number
}

type Draft = { id: number; draft_text: string; status: string; created_at: string }

type Conversation = {
  id: string
  hr_name?: string
  hr_title?: string
  status: string
  platform?: string
  company_id?: string
  job_id?: string
  conversation_url?: string
  job_url?: string
  job_url_reason?: string
  conversation_url_reason?: string
  pause_reason?: string
  job_title?: string
  job_company?: string
  job_score?: number
  message_count?: number
}

type Detail = { conversation: Conversation; messages: Message[]; drafts: Draft[] }

const PAUSED = ['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human']
const REPLY_PLATFORMS = new Set(['boss', 'zhilian'])

const PLATFORM_LABELS: Record<string, string> = {
  boss: 'BOSS 直聘',
  zhilian: '智联招聘',
  liepin: '猎聘',
  '51job': '前程无忧',
}

const PLATFORM_STYLES: Record<string, string> = {
  boss: 'border-orange-200 bg-orange-50 text-orange-800',
  zhilian: 'border-blue-200 bg-blue-50 text-blue-800',
  liepin: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  '51job': 'border-slate-200 bg-slate-50 text-slate-700',
}

const STATUS_LABELS: Record<string, string> = {
  new: '新会话',
  active: '活跃',
  waiting_reply: '等待回复',
  waiting_human: '等待人工确认',
  paused_salary: '薪资待确认',
  paused_risk: '风控暂停',
  paused_manual: '人工暂停',
  closed: '已关闭',
  failed: '失败',
}

function displayHrName(name?: string) {
  const value = String(name || '').trim()
  return value && value !== '未命名 HR' ? value : 'HR 信息待平台同步'
}

function messageTime(message: Message) {
  return message.message_time || message.created_at || ''
}

export default function ConversationDetailPage() {
  const { id = '' } = useParams()
  const [data, setData] = useState<Detail | null>(null)
  const [notice, setNotice] = useState('')
  const [composer, setComposer] = useState('')
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [nearBottom, setNearBottom] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const initialScrollDone = useRef(false)
  const replyAttemptRef = useRef<{ message: string; key: string } | null>(null)

  const refresh = async () => {
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`)
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || '会话加载失败')
    setData(payload as Detail)
  }

  useEffect(() => {
    initialScrollDone.current = false
    void refresh().catch(error => setNotice(error instanceof Error ? error.message : '会话加载失败'))
  }, [id])

  const orderedMessages = useMemo(() => {
    if (!data) return []
    // The API already returns the persisted platform order (the local message
    // id is the stable fallback for messages captured in the same snapshot).
    // Do not lexically sort platform-relative labels such as "昨天 14:16",
    // "星期四 15:31" and "10:41"; their text is not a chronological key.
    return [...data.messages].sort((a, b) => a.id - b.id)
  }, [data])

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    requestAnimationFrame(() => {
      if (!initialScrollDone.current || nearBottom) {
        element.scrollTop = element.scrollHeight
      }
      initialScrollDone.current = true
    })
  }, [orderedMessages.length, nearBottom])

  const onScroll = () => {
    const element = scrollRef.current
    if (!element) return
    setNearBottom(element.scrollHeight - element.clientHeight - element.scrollTop < 56)
  }

  const scrollToBottom = () => {
    const element = scrollRef.current
    if (!element) return
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
    setNearBottom(true)
  }

  const resume = async () => {
    if (!window.confirm('确认恢复这个 HR 会话的自动化处理吗？恢复后新的 HR 消息可以重新进入 AI 分析流程。')) return
    const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'active', reason: '用户人工恢复' }),
    })
    if (!response.ok) {
      setNotice('恢复失败')
      return
    }
    await refresh()
    setNotice('会话已恢复，后续新消息可以重新进入处理流程')
  }

  const copy = async (text: string) => {
    await navigator.clipboard?.writeText(text)
    setNotice('草稿已复制，可由你人工粘贴到招聘平台发送')
  }

  const generateDraft = async () => {
    setGenerating(true)
    setNotice('正在基于当前会话与已确认经历生成回复草稿…')
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/draft`, { method: 'POST' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || '草稿生成失败')
      setComposer(String(payload.draft?.draft_text || ''))
      await refresh()
      setNotice('草稿已生成，可编辑后人工确认发送')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '草稿生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const deleteDraft = async (draft: Draft) => {
    if (!window.confirm('确认删除这条历史草稿吗？删除后无法恢复。')) return
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/draft/${draft.id}`, { method: 'DELETE' })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || '草稿删除失败')
      await refresh()
      setNotice('历史草稿已删除')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '草稿删除失败')
    }
  }

  const sendReply = async () => {
    const message = composer.trim()
    if (!message || sending) return
    if (!window.confirm('确认将这段回复发送给当前会话的 HR 吗？发送前请再次核对岗位和内容。')) return
    setSending(true)
    setNotice('正在等待平台 DOM 验证发送结果…')
    try {
      const currentAttempt = replyAttemptRef.current
      const idempotencyKey = currentAttempt?.message === message
        ? currentAttempt.key
        : (globalThis.crypto?.randomUUID?.() || `reply-${Date.now()}-${Math.random().toString(36).slice(2)}`)
      replyAttemptRef.current = { message, key: idempotencyKey }
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}/reply/send`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, idempotency_key: idempotencyKey }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.error || payload.status || '发送未确认')
      setComposer('')
      replyAttemptRef.current = null
      await refresh()
      setNotice('平台已确认发送，消息已写入本地会话')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '发送未确认，未写入本地成功消息')
    } finally {
      setSending(false)
    }
  }

  if (!data) return <div className="text-muted">正在加载会话…{notice && <span className="ml-2 text-danger">{notice}</span>}</div>

  const conversation = data.conversation
  const platform = conversation.platform || 'unknown'
  const canReply = REPLY_PLATFORMS.has(platform)
  const senderLabel: Record<string, string> = { hr: 'HR', user: '我', ai: 'AI 草稿', system: '平台系统', unknown: '发送方未识别' }
  const statusLabel = STATUS_LABELS[conversation.status] || conversation.status

  return (
    <div className="space-y-5">
      <Link className="text-sm text-primary" to="/conversations">← 返回会话列表</Link>
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle>{displayHrName(conversation.hr_name)}</CardTitle>
              <div className="mt-1 text-sm text-muted">{conversation.hr_title || '招聘联系人'} · {statusLabel}</div>
            </div>
            <span className={`rounded-full border px-3 py-1 text-xs font-bold ${PLATFORM_STYLES[platform] || 'border-card-border bg-white text-muted'}`}>
              {PLATFORM_LABELS[platform] || platform}
            </span>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 rounded-xl border border-card-border bg-[#FFFCFA] p-4 text-sm md:grid-cols-2">
            <div><span className="text-muted">公司：</span><strong>{conversation.job_company || conversation.company_id || '公司信息待岗位池关联'}</strong></div>
            <div><span className="text-muted">岗位：</span><strong>{conversation.job_title || '岗位信息待岗位池关联'}</strong></div>
            <div><span className="text-muted">AI 评分：</span><strong className="text-primary">{typeof conversation.job_score === 'number' ? conversation.job_score : '未评分'}</strong></div>
            <div><span className="text-muted">消息：</span><strong>{orderedMessages.length} 条</strong></div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {conversation.conversation_url ? (
              <a href={conversation.conversation_url} target="_blank" rel="noreferrer">
                <Button className="gap-2" size="sm" variant="secondary"><ExternalLink className="h-4 w-4" /><span>打开平台 HR 会话</span></Button>
              </a>
            ) : <span className="text-sm text-muted">HR 会话链接未就绪：{conversation.conversation_url_reason || '平台尚未返回可验证的具体会话地址'}</span>}
            {conversation.job_url ? (
              <a href={conversation.job_url} target="_blank" rel="noreferrer">
                <Button className="gap-2" size="sm" variant="ghost"><BriefcaseBusiness className="h-4 w-4" /><span>查看平台岗位详情</span></Button>
              </a>
            ) : <span className="text-sm text-muted">岗位详情链接未就绪：{conversation.job_url_reason || '岗位池尚未保存真实平台地址'}</span>}
          </div>

          {conversation.pause_reason && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{conversation.pause_reason}</div>}
          {PAUSED.includes(conversation.status) && <Button className="mt-4" size="sm" onClick={() => void resume()}>人工确认后恢复自动化</Button>}

          <div ref={scrollRef} onScroll={onScroll} className="relative mt-4 max-h-[560px] space-y-3 overflow-y-auto rounded-2xl bg-[#FFFCFA] p-4">
            {orderedMessages.map(message => (
              <div key={message.id} className={`max-w-[86%] rounded-xl p-3 ${message.sender_type === 'hr' ? 'bg-[#FFF0E5]' : message.sender_type === 'system' || message.sender_type === 'unknown' ? 'mx-auto bg-slate-100' : 'ml-auto bg-gray-50'}`}>
                <div className="mb-1 text-xs font-bold text-muted">
                  {senderLabel[message.sender_type] || message.sender_type} · {messageTime(message)}
                  {message.is_ai_generated ? ' · AI 生成' : ''}{message.is_sent ? ' · 已发送' : ''}
                </div>
                <div className="whitespace-pre-wrap text-sm leading-6">{message.content}</div>
              </div>
            ))}
            {!orderedMessages.length && <div className="p-6 text-center text-muted">暂无已持久化消息。请在招聘平台中人工打开目标 HR 的聊天面板，再从会话卡片点击同步；同步不会发送消息。</div>}
            {!nearBottom && <Button className="sticky bottom-2 left-1/2 z-10 mx-auto flex gap-2 shadow-md" size="sm" variant="secondary" onClick={scrollToBottom}><ArrowDown className="h-4 w-4" /><span>回到底部</span></Button>}
          </div>
          {notice && <div className="mt-3 text-sm text-primary">{notice}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>回复草稿（仅供人工审核）</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {canReply ? (
              <Button className="gap-2" size="sm" variant="secondary" disabled={generating || sending} onClick={() => void generateDraft()}><Sparkles className="h-4 w-4" /><span>{generating ? '生成中' : 'AI 生成回复草稿'}</span></Button>
            ) : <span className="text-sm text-muted">{PLATFORM_LABELS[platform] || platform} 暂不支持从本地会话发送回复，请在平台内人工处理。</span>}
          </div>
          <textarea value={composer} onChange={event => { setComposer(event.target.value); if (replyAttemptRef.current?.message !== event.target.value.trim()) replyAttemptRef.current = null }} disabled={!canReply || sending} placeholder={canReply ? '点击 AI 生成草稿，或在这里编辑回复内容…' : '该平台暂不支持会话回复'} className="min-h-32 w-full rounded-xl border border-card-border bg-white p-3 text-sm leading-6 outline-none transition focus:border-primary" maxLength={2000} />
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
            <span>{composer.length}/2000 · AI 只生成草稿，发送前必须人工确认</span>
            <Button className="gap-2" size="sm" disabled={!canReply || !composer.trim() || sending} onClick={() => void sendReply()}><Send className="h-4 w-4" /><span>{sending ? '发送确认中' : '确认并发送'}</span></Button>
          </div>
          {data.drafts.map(draft => (
            <div key={draft.id} className="rounded-xl border border-card-border p-3">
              <div className="mb-2 text-xs text-muted">{draft.status} · {draft.created_at}</div>
              <p className="whitespace-pre-wrap text-sm leading-6">{draft.draft_text}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button className="gap-2" size="sm" variant="ghost" onClick={() => void copy(draft.draft_text)}><span>复制草稿</span></Button>
                <Button className="gap-2 text-danger" size="sm" variant="ghost" onClick={() => void deleteDraft(draft)}><Trash2 className="h-4 w-4" /><span>删除草稿</span></Button>
              </div>
            </div>
          ))}
          {data.drafts.length === 0 && <div className="text-sm text-muted">暂无草稿</div>}
        </CardContent>
      </Card>
    </div>
  )
}
