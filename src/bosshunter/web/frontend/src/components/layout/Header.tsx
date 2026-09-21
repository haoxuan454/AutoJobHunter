import { useLocation } from 'react-router-dom'
import { Activity, AudioLines, BarChart3, BookOpen, BriefcaseBusiness, BrainCircuit, Coins, FlaskConical, ListChecks, MessageSquare, Radar, Settings, Target } from 'lucide-react'

const pageMeta: Record<string, { title: string; description: string; icon: typeof Target; tone: string }> = {
  '/voice-assistant': { title: '语音求职助手', description: '实时转写 HR 问题并生成求职者口吻回复', icon: AudioLines, tone: 'bg-indigo-50 text-indigo-600' },
  '/assistant-lab': { title: 'AI 回复演练', description: '本地沙盒验证个人经验驱动的 HR 回复流程', icon: FlaskConical, tone: 'bg-indigo-50 text-indigo-600' },
  '/common-questions': { title: '共性问题库', description: '查看和整理脱敏后的 HR 共性问题与回复', icon: ListChecks, tone: 'bg-teal-50 text-teal-600' },
  '/': { title: '工作台', description: '查看今日求职任务与整体进度', icon: Target, tone: 'bg-orange-50 text-orange-600' },
  '/jobs': { title: '岗位池', description: '统一查看、筛选和管理已采集岗位', icon: BriefcaseBusiness, tone: 'bg-blue-50 text-blue-600' },
  '/monitor': { title: '监测执行', description: '查看 HR 回复并处理待人工确认事项', icon: Radar, tone: 'bg-emerald-50 text-emerald-600' },
  '/knowledge': { title: '个人知识库', description: '管理可供 AI 引用的真实经历与项目经验', icon: BookOpen, tone: 'bg-violet-50 text-violet-600' },
  '/conversations': { title: 'HR 会话', description: '按会话查看 HR 消息、上下文和回复草稿', icon: MessageSquare, tone: 'bg-cyan-50 text-cyan-600' },
  '/analytics': { title: '数据分析', description: '从沟通记录中观察岗位方向与 HR 兴趣', icon: BarChart3, tone: 'bg-rose-50 text-rose-600' },
  '/ai-usage': { title: 'Token 消耗', description: '查看模型调用、Token 使用量和费用估算', icon: Coins, tone: 'bg-indigo-50 text-indigo-600' },
  '/config': { title: '配置', description: '设置个人资料、平台、AI 和安全规则', icon: Settings, tone: 'bg-amber-50 text-amber-700' },
}

export function Header() {
  const location = useLocation()
  const meta = pageMeta[location.pathname] || { title: 'AutoJobHunter', description: '自动化求职工作台', icon: BrainCircuit, tone: 'bg-slate-100 text-slate-600' }
  const Icon = meta.icon

  return <header className="flex min-h-20 shrink-0 items-center justify-between gap-4 border-b border-card-border bg-[#FFFCFA] px-4 py-3 md:px-6">
    <div className="flex min-w-0 items-center gap-3">
      <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl ${meta.tone}`}><Icon className="h-5 w-5" /></div>
      <div className="min-w-0"><h1 className="truncate text-lg font-black tracking-tight text-foreground md:text-xl">{meta.title}</h1><p className="mt-0.5 truncate text-xs text-muted md:text-sm">{meta.description}</p></div>
    </div>
    <div className="flex shrink-0 items-center gap-2 rounded-full bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700"><Activity className="h-3.5 w-3.5" /><span className="hidden sm:inline">本地服务运行中</span><span className="sm:hidden">运行中</span></div>
  </header>
}
