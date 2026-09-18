import { FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, KeyRound, Mail, Send, ShieldCheck } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

type EmailSettings = { enabled: boolean; auto_send: boolean; smtp_host: string; smtp_port: number; use_tls: boolean; username: string; from_email: string; to_email: string; password_set?: boolean; password?: string }
const defaults: EmailSettings = { enabled: false, auto_send: false, smtp_host: 'smtp.qq.com', smtp_port: 465, use_tls: true, username: '', from_email: '', to_email: '' }

export function EmailNotificationCard() {
  const [form, setForm] = useState<EmailSettings>(defaults)
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => { fetch('/api/notifications/email').then(response => response.json()).then(data => setForm(current => ({ ...current, ...(data.email || {}) }))) }, [])
  const update = (key: keyof EmailSettings, value: string | boolean | number) => setForm(current => ({ ...current, [key]: value }))
  const save = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setNotice(null)
    try {
      const response = await fetch('/api/notifications/email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: form }) })
      const data = await response.json()
      setNotice({ ok: response.ok, text: response.ok ? 'QQ 邮箱提醒配置已保存' : (data.error || '保存失败') })
      if (response.ok) setForm(current => ({ ...current, ...(data.email || {}), password: '' }))
    } finally { setSaving(false) }
  }

  return <Card className="overflow-hidden border-primary/15"><CardHeader className="bg-gradient-to-r from-[#FFF1E6] to-white"><div className="flex items-start gap-3"><div className="rounded-2xl bg-white p-3 text-primary shadow-sm"><Mail className="h-6 w-6" /></div><div><CardTitle className="text-base font-black text-foreground">QQ 邮箱人工接管提醒</CardTitle><p className="mt-1 text-xs leading-5 text-muted">当 HR 提到薪资、待遇等敏感话题时，先暂停该会话并提醒你人工处理。</p></div></div></CardHeader><CardContent className="pt-5"><form className="space-y-5" onSubmit={save}>
    <div className="grid gap-3 md:grid-cols-2"><label className="flex cursor-pointer items-center gap-3 rounded-2xl border border-card-border bg-[#FFFCFA] p-3 text-sm font-bold"><input type="checkbox" checked={form.enabled} onChange={e => update('enabled', e.target.checked)} className="h-4 w-4 accent-orange-500" /><span><span className="block">启用邮箱提醒</span><span className="mt-1 block text-xs font-normal text-muted">仅发送给你的 QQ 邮箱</span></span></label><label className="flex cursor-pointer items-center gap-3 rounded-2xl border border-card-border bg-[#FFFCFA] p-3 text-sm font-bold"><input type="checkbox" checked={form.auto_send} onChange={e => update('auto_send', e.target.checked)} className="h-4 w-4 accent-orange-500" /><span><span className="block">自动发送提醒</span><span className="mt-1 block text-xs font-normal text-muted">不发送任何 HR 消息</span></span></label></div>
    <div className="grid gap-4 md:grid-cols-2"><label><span className="mb-1.5 block text-xs font-bold">你的 QQ 邮箱</span><Input type="email" value={form.to_email} onChange={e => update('to_email', e.target.value)} placeholder="接收提醒，例如 123456@qq.com" /></label><label><span className="mb-1.5 block text-xs font-bold">QQ 邮箱授权码</span><Input type="password" value={form.password || ''} onChange={e => update('password', e.target.value)} placeholder={form.password_set ? '已保存，留空保持不变' : '填写 16 位授权码'} /></label><label><span className="mb-1.5 block text-xs font-bold">发件 QQ 邮箱</span><Input type="email" value={form.from_email} onChange={e => update('from_email', e.target.value)} placeholder="通常与收件邮箱相同" /></label><label><span className="mb-1.5 block text-xs font-bold">登录用户名</span><Input type="email" value={form.username} onChange={e => update('username', e.target.value)} placeholder="通常与发件邮箱相同" /></label></div>
    <div className="grid gap-3 rounded-2xl border border-blue-100 bg-blue-50/60 p-4 text-xs text-blue-900 md:grid-cols-3"><div className="flex gap-2"><ShieldCheck className="h-4 w-4 shrink-0" /><span>服务器：smtp.qq.com</span></div><div className="flex gap-2"><Send className="h-4 w-4 shrink-0" /><span>端口：465 · SSL/TLS</span></div><div className="flex gap-2"><KeyRound className="h-4 w-4 shrink-0" /><span>使用授权码，不是 QQ 登录密码</span></div></div>
    <div className="flex flex-wrap items-center justify-between gap-3"><div className="text-xs text-muted">授权码保存在本机 data/.email_credentials.yaml，不写入公共配置。</div><Button type="submit" disabled={saving}><Mail className="mr-2 h-4 w-4" />{saving ? '保存中...' : '保存 QQ 邮箱配置'}</Button></div>
    {notice && <div className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${notice.ok ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'}`}>{notice.ok && <CheckCircle2 className="h-4 w-4" />}{notice.text}</div>}
  </form></CardContent></Card>
}
