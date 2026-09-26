import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { BriefcaseBusiness, ExternalLink } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type Message = {
  id: number
  sender_type: string
  content: string
  message_time?: string
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
  job_score_reason?: string
  message_count?: number
}

type Detail = { conversation: Conversation; messages: Message[]; drafts: Draft[] }

const PAUSED = ['paused_salary', 'paused_manual', 'paused_risk', 'waiting_human']

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

export default function ConversationDetailPage() {
  const { id = '' } = useParams()
  const [data, setData] = useState<Detail | null>(null)
  const [notice, setNotice] = useState('')

  const refresh = () => fetch(`/api/conversations/${encodeURIComponent(id)}`).then(async response => {
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || '会话加载失败')
    return payload as Detail
  }).then(setData)

  useEffect(() => {
    void refresh().catch(error => setNotice(error instanceof Error ? error.message : '会话加载失败'))
  }, [id])

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

  if (!data) return <div className="text-muted">正在加载会话…{notice && <span className="ml-2 text-danger">{notice}</span>}</div>

  const conversation = data.conversation
  const platform = conversation.platform || 'unknown'
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
            <div><span className="text-muted">消息：</span><strong>{data.messages.length} 条</strong></div>
          </div>

          <div className="mt-4 flex flex-wrap gap-2">
            {conversation.conversation_url && (
              <a href={conversation.conversation_url} target="_blank" rel="noreferrer">
                <Button className="gap-2" size="sm" variant="secondary"><ExternalLink className="h-4 w-4" /><span>打开平台 HR 会话</span></Button>
              </a>
            )}
            {conversation.job_url && (
              <a href={conversation.job_url} target="_blank" rel="noreferrer">
                <Button className="gap-2" size="sm" variant="ghost"><BriefcaseBusiness className="h-4 w-4" /><span>查看平台岗位详情</span></Button>
              </a>
            )}
          </div>

          {conversation.pause_reason && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-danger">{conversation.pause_reason}</div>}
          {PAUSED.includes(conversation.status) && <Button className="mt-4" size="sm" onClick={() => void resume()}>人工确认后恢复自动化</Button>}

          <div className="mt-4 max-h-[560px] space-y-3 overflow-y-auto rounded-2xl bg-[#FFFCFA] p-4">
            {data.messages.map(message => (
              <div key={message.id} className={`max-w-[86%] rounded-xl p-3 ${message.sender_type === 'hr' ? 'bg-[#FFF0E5]' : message.sender_type === 'system' || message.sender_type === 'unknown' ? 'mx-auto bg-slate-100' : 'ml-auto bg-gray-50'}`}>
                <div className="mb-1 text-xs font-bold text-muted">
                  {senderLabel[message.sender_type] || message.sender_type} · {message.message_time || ''}
                  {message.is_ai_generated ? ' · AI 生成' : ''}{message.is_sent ? ' · 已发送' : ''}
                </div>
                <div className="whitespace-pre-wrap text-sm leading-6">{message.content}</div>
              </div>
            ))}
            {data.messages.length === 0 && <div className="p-6 text-center text-muted">暂无已持久化消息。请在招聘平台中人工打开目标 HR 的聊天面板，再从会话卡片点击同步；同步不会发送消息。</div>}
          </div>
          {notice && <div className="mt-3 text-sm text-primary">{notice}</div>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>回复草稿（仅供人工审核）</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {data.drafts.map(draft => (
            <div key={draft.id} className="rounded-xl border border-card-border p-3">
              <div className="mb-2 text-xs text-muted">{draft.status} · {draft.created_at}</div>
              <p className="whitespace-pre-wrap text-sm leading-6">{draft.draft_text}</p>
              <Button className="mt-3" size="sm" onClick={() => void copy(draft.draft_text)}>复制草稿</Button>
            </div>
          ))}
          {data.drafts.length === 0 && <div className="text-sm text-muted">暂无草稿</div>}
        </CardContent>
      </Card>
    </div>
  )
}
