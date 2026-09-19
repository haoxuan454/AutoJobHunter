import { NavLink } from 'react-router-dom'
import { Activity, BarChart3, BookOpen, BriefcaseBusiness, FlaskConical, Heart, LayoutDashboard, MessageSquare, Radar, Rocket, Settings } from 'lucide-react'
import { useEffect, useState } from 'react'

const navItems = [
  { to: '/assistant-lab', icon: FlaskConical, label: 'AI 回复演练' },
  { to: '/', icon: LayoutDashboard, label: '工作台' },
  { to: '/jobs', icon: BriefcaseBusiness, label: '岗位池' },
  { to: '/monitor', icon: Radar, label: '监测执行' },
  { to: '/knowledge', icon: BookOpen, label: '个人知识库' },
  { to: '/conversations', icon: MessageSquare, label: 'HR 会话' },
  { to: '/analytics', icon: BarChart3, label: '数据分析' },
  { to: '/config', icon: Settings, label: '配置' },
]

interface SidebarProps { pendingReplies?: number }

export function Sidebar({ pendingReplies: pendingRepliesProp }: SidebarProps) {
  const [pendingReplies, setPendingReplies] = useState(pendingRepliesProp ?? 0)
  useEffect(() => {
    if (pendingRepliesProp !== undefined) { setPendingReplies(pendingRepliesProp); return }
    const fetchPendingReplies = async () => {
      try { const response = await fetch('/api/history/unresolved-replies/count'); const data = await response.json(); setPendingReplies(Number(data.count) || 0) }
      catch { setPendingReplies(0) }
    }
    void fetchPendingReplies()
    const interval = setInterval(fetchPendingReplies, 30000)
    return () => clearInterval(interval)
  }, [pendingRepliesProp])

  return <aside className="flex w-16 shrink-0 flex-col border-r border-card-border bg-white md:w-60">
    <div className="flex h-16 shrink-0 items-center justify-center border-b border-card-border md:justify-start md:px-5"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-primary text-white shadow-lg shadow-primary/20"><span className="text-sm font-black">AJH</span></div><div className="hidden md:block"><div className="text-sm font-black tracking-tight text-foreground">AutoJobHunter</div><div className="text-[12px] italic tracking-wide text-muted">自动求职猎人</div></div></div></div>
    <nav className="flex-1 space-y-1 px-1.5 py-4 md:px-3">{navItems.map(item => <NavLink key={item.to} to={item.to} className={({ isActive }) => `relative flex items-center justify-center gap-3 rounded-xl px-1 py-3 text-[10px] transition-colors md:justify-between md:px-3 md:text-sm ${isActive ? 'bg-[#FFF0E5] font-black text-primary' : 'text-muted hover:bg-[#FFFCFA] hover:text-foreground'}`}><span className="flex flex-col items-center gap-1 md:flex-row md:gap-3"><item.icon className="h-4 w-4" />{item.label}</span>{item.to === '/monitor' && pendingReplies > 0 && <span className="absolute right-1 top-2 h-2 w-2 rounded-full bg-danger md:static" aria-label="有待处理事项" />}</NavLink>)}</nav>
    <div className="space-y-3 border-t border-card-border px-2 py-4 md:px-4"><div aria-label="AutoJobHunter" className="relative flex items-center justify-center rounded-xl border border-card-border bg-[#FFFCFA] px-3 py-3 text-xs font-black text-foreground md:rounded-2xl"><Rocket className="h-4 w-4 shrink-0 text-primary md:absolute md:left-3" /><span className="mx-auto hidden items-center justify-center gap-2 md:flex">AutoJobHunter</span></div><p className="hidden items-center justify-center gap-1 text-center text-[11px] leading-5 text-muted md:flex"><Heart className="h-3 w-3 fill-rose-400 text-rose-400" />感谢支持 AutoJobHunter</p></div>
  </aside>
}
