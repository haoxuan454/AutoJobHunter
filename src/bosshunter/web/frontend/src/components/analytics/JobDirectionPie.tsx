import { useMemo } from 'react'
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { JOB_DIRECTION_LIMIT, topJobDirections, type JobDirectionActivity } from '@/lib/jobDirectionActivity'

const directionColor = (index: number) => `hsl(${(index * 137.5 + 22) % 360}, 65%, 48%)`

/** The legend owns its scroll area; it never changes the chart/card height. */
export function JobDirectionPie({ rows, legacyFallback = false }: { rows: JobDirectionActivity[]; legacyFallback?: boolean }) {
  const directions = useMemo(() => topJobDirections(rows), [rows])
  const chartRows = useMemo(() => directions.map(row => ({ ...row, name: row.label })), [directions])
  const conversationCount = directions.reduce((sum, row) => sum + row.conversations, 0)

  if (!directions.length) return <div className="flex h-36 items-center justify-center text-sm text-muted">暂无真实对话数据</div>

  return <div className="min-w-0 space-y-3">
    <p className="text-xs leading-5 text-muted">{legacyFallback
      ? `兼容旧版接口：按 HR 消息数排序，当前展示 ${directions.length} 项；后端更新后将按双方消息数展示前 ${JOB_DIRECTION_LIMIT} 项。`
      : `按双方有效消息数取前 ${JOB_DIRECTION_LIMIT} 个岗位方向 · 当前 ${directions.length} 项。占比以这 ${directions.length} 项会话为分母。`}</p>
    <div className="grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,180px)]">
      <div className="h-80 min-w-0" data-testid="job-direction-pie">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={chartRows} dataKey="conversations" nameKey="name" cx="50%" cy="50%" outerRadius="75%" labelLine={false}
              label={({ percent }) => percent >= 0.04 ? `${Math.round(percent * 100)}%` : ''}>
              {chartRows.map((entry, index) => <Cell key={entry.name} fill={directionColor(index)} />)}
            </Pie>
            <Tooltip wrapperStyle={{ zIndex: 10, maxWidth: 280 }} contentStyle={{ whiteSpace: 'normal', overflowWrap: 'anywhere' }}
              formatter={(value: number, _name: string, item: any) => [
                `${value} 个会话 · 双方 ${item.payload.message_count} 条消息 · HR 回复率 ${item.payload.reply_rate}%`, item.payload.name,
              ]} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul aria-label="岗位方向图例" tabIndex={0} className="h-64 min-w-0 space-y-1 overflow-y-auto overscroll-contain rounded-xl bg-slate-50/80 p-2 outline-none focus-visible:ring-2 focus-visible:ring-primary/30 sm:h-80">
        {directions.map((row, index) => <li key={row.label} className="flex min-w-0 items-start gap-2 rounded-lg px-1 py-2 text-xs"
          title={`${row.label} · ${row.conversations} 个会话 · 双方 ${row.message_count} 条消息`}>
          <span aria-hidden="true" className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: directionColor(index) }} />
          <div className="min-w-0 flex-1">
            <span className="block truncate font-medium text-slate-700">{row.label.length > 12 ? `${row.label.slice(0, 12)}…` : row.label}</span>
            <span className="mt-1 block text-[11px] text-muted">{row.conversations} 会话 · {row.message_count} 消息</span>
          </div>
          <span className="shrink-0 tabular-nums text-slate-600">{conversationCount ? (row.conversations / conversationCount * 100).toFixed(1) : '0.0'}%</span>
        </li>)}
      </ul>
    </div>
  </div>
}
