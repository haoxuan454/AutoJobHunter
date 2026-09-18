import { FormEvent, useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'

type EmailSettings = { enabled: boolean; auto_send: boolean; smtp_host: string; smtp_port: number; use_tls: boolean; username: string; from_email: string; to_email: string; password_set?: boolean }
const empty: EmailSettings = { enabled: false, auto_send: false, smtp_host: '', smtp_port: 465, use_tls: true, username: '', from_email: '', to_email: '' }

export default function NotificationPage() {
  const [form, setForm] = useState<EmailSettings & { password?: string }>(empty)
  const [notice, setNotice] = useState('')
  useEffect(() => { fetch('/api/notifications/email').then(r => r.json()).then(d => setForm({ ...empty, ...(d.email || {}) })) }, [])
  const update = (key: string, value: string | boolean | number) => setForm(current => ({ ...current, [key]: value }))
  const save = async (event: FormEvent) => {
    event.preventDefault()
    const response = await fetch('/api/notifications/email', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: form }) })
    const data = await response.json(); setNotice(data.error || '邮箱通知配置已保存')
    if (response.ok) setForm(current => ({ ...current, ...(data.email || {}), password: '' }))
  }
  return <div className="max-w-2xl space-y-5"><div><h2 className="text-2xl font-black">邮箱通知</h2><p className="mt-1 text-sm text-muted">薪资话题会先暂停当前 HR 会话，再按这里的配置通知你。</p></div><Card><CardHeader><CardTitle>SMTP 配置</CardTitle></CardHeader><CardContent><form className="space-y-4" onSubmit={save}><label className="flex gap-2 text-sm"><input type="checkbox" checked={form.enabled} onChange={e => update('enabled', e.target.checked)} />启用邮箱通知</label><label className="flex gap-2 text-sm"><input type="checkbox" checked={form.auto_send} onChange={e => update('auto_send', e.target.checked)} />自动发送人工接管提醒</label><div className="grid gap-3 md:grid-cols-2">{([['smtp_host', 'SMTP 主机'], ['smtp_port', 'SMTP 端口'], ['username', '用户名'], ['from_email', '发件人'], ['to_email', '收件邮箱']] as const).map(([key, label]) => <label key={key} className="text-sm"><span className="mb-1 block font-bold">{label}</span><input className="w-full rounded-lg border p-2" value={String(form[key] ?? '')} onChange={e => update(key, key === 'smtp_port' ? Number(e.target.value) : e.target.value)} /></label>)}<label className="text-sm"><span className="mb-1 block font-bold">密码</span><input type="password" className="w-full rounded-lg border p-2" placeholder={form.password_set ? '已保存，留空保持不变' : ''} value={form.password || ''} onChange={e => update('password', e.target.value)} /></label></div><Button type="submit">保存配置</Button>{notice && <div className="text-sm text-primary">{notice}</div>}</form></CardContent></Card></div>
}
