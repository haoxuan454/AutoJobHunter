import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import { CheckSquare, Trash2 } from 'lucide-react'

type BacklogPanelProps<T> = {
  title: string
  description: string
  items: T[]
  getId: (item: T) => string
  selectedIds: string[]
  onSelectionChange: (ids: string[]) => void
  onDeleteSelected: (ids: string[]) => void
  renderItem: (
    item: T,
    selected: boolean,
    onToggle: () => void,
    onDelete: () => void,
  ) => ReactNode
  children?: ReactNode
  actions?: ReactNode
  className?: string
  emptyMessage?: string
  ariaLabel?: string
  deleting?: boolean
}

/**
 * Fixed-height backlog surface shared by the three workbench queues.
 * Deletion is intentionally delegated to the page so all queues use the
 * same soft-delete/recycle-bin endpoint and task-conflict guard.
 */
export function BacklogPanel<T>({
  title,
  description,
  items,
  getId,
  selectedIds,
  onSelectionChange,
  onDeleteSelected,
  renderItem,
  children,
  actions,
  className = 'rounded-3xl border border-card-border bg-white p-5',
  emptyMessage = '当前没有积压项目。',
  ariaLabel,
  deleting = false,
}: BacklogPanelProps<T>) {
  const itemIds = items.map(getId)
  const selected = new Set(selectedIds.filter(id => itemIds.includes(id)))
  const allSelected = itemIds.length > 0 && itemIds.every(id => selected.has(id))
  const setAll = () => onSelectionChange(allSelected ? [] : itemIds)
  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelectionChange(itemIds.filter(itemId => next.has(itemId)))
  }

  return (
    <section className={className} aria-label={ariaLabel || title}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h3 className="text-lg font-black">{title}</h3>
          <p className="mt-1 text-xs text-muted">{description}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {actions}
          <Button
            variant="secondary"
            size="sm"
            disabled={deleting || !items.length}
            onClick={setAll}
            aria-label={allSelected ? `取消全选${title}` : `全选${title}`}
          >
            <CheckSquare className="mr-2 h-4 w-4" />{allSelected ? '取消全选' : '全选'}
          </Button>
          <Button variant="secondary" size="sm" disabled={deleting || !selected.size} onClick={() => onSelectionChange([])}>
            清空选择
          </Button>
          <Button
            variant="destructive"
            size="sm"
            disabled={deleting || !selected.size}
            onClick={() => onDeleteSelected([...selected])}
          >
            <Trash2 className="mr-2 h-4 w-4" />移入回收站 {selected.size || ''}
          </Button>
        </div>
      </div>

      {children}

      {items.length ? (
        <div className="h-[360px] overflow-y-auto overscroll-contain rounded-2xl border border-card-border/70 bg-white/60 p-2 pr-1" aria-label={`${title}滚动列表`}>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {items.map(item => {
              const id = getId(item)
              return <div key={id}>{renderItem(item, selected.has(id), () => { if (!deleting) toggle(id) }, () => { if (!deleting) onDeleteSelected([id]) })}</div>
            })}
          </div>
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-card-border bg-[#FFFCFA] p-5 text-center text-sm text-muted">{emptyMessage}</p>
      )}
    </section>
  )
}
