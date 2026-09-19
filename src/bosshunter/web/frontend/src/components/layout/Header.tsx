import { useLocation } from 'react-router-dom'
import { Activity } from 'lucide-react'

const pageTitles: Record<string, string> = {
  '/': '工作台',
  '/jobs': '岗位池',
  '/monitor': '监测执行',
  '/config': '配置',
  '/knowledge': '个人知识库',
  '/conversations': 'HR 会话',
  '/analytics': '数据分析',
}

export function Header() {
  const location = useLocation()
  const title = pageTitles[location.pathname] || 'AutoJobHunter'
  return <header className="flex h-16 items-center justify-between border-b border-card-border bg-[#FFFCFA] px-6"><h1 className="text-lg font-black text-foreground">{title}</h1><div className="flex items-center gap-2 text-xs text-muted"><Activity className="h-3 w-3 text-success" /><span>本地服务运行中</span></div></header>
}
