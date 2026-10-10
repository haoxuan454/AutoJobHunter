import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

type Props = {
  page: number
  pageSize: number
  total: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
}

export function ConversationPagination({ page, pageSize, total, onPageChange, onPageSizeChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  const start = total ? (page - 1) * pageSize + 1 : 0
  return (
    <nav aria-label="HR 会话分页" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-card-border bg-white px-4 py-3 text-sm">
      <p className="text-muted" role="status">共 {total} 个会话 · 第 {start}–{Math.min(page * pageSize, total)} 个 · 第 {page} / {pages} 页</p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="mr-2 flex items-center gap-2 text-muted">
          每页
          <select aria-label="每页会话数" value={pageSize} onChange={event => onPageSizeChange(Number(event.target.value))} className="rounded-lg border border-card-border bg-white px-2 py-1.5">
            {[12, 24, 48].map(size => <option key={size} value={size}>{size} 个</option>)}
          </select>
        </label>
        <Button size="sm" variant="ghost" disabled={page === 1} onClick={() => onPageChange(1)}>首页</Button>
        <Button size="sm" variant="secondary" className="gap-1" disabled={page === 1} onClick={() => onPageChange(page - 1)}><ChevronLeft className="h-4 w-4" />上一页</Button>
        <Button size="sm" variant="secondary" className="gap-1" disabled={page === pages} onClick={() => onPageChange(page + 1)}>下一页<ChevronRight className="h-4 w-4" /></Button>
        <Button size="sm" variant="ghost" disabled={page === pages} onClick={() => onPageChange(pages)}>尾页</Button>
      </div>
    </nav>
  )
}
