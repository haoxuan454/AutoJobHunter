import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BacklogPanel } from './BacklogPanel'

afterEach(cleanup)

type Item = { id: string; label: string }

const items: Item[] = [
  { id: 'a', label: '岗位 A' },
  { id: 'b', label: '岗位 B' },
]

function renderPanel(overrides: Partial<React.ComponentProps<typeof BacklogPanel<Item>>> = {}) {
  const onSelectionChange = vi.fn()
  const onDeleteSelected = vi.fn()
  const result = render(
    <BacklogPanel<Item>
      title="测试积压"
      description="测试说明"
      items={items}
      getId={item => item.id}
      selectedIds={[]}
      onSelectionChange={onSelectionChange}
      onDeleteSelected={onDeleteSelected}
      renderItem={(item, selected, onToggle, onDelete) => (
        <article>
          <input aria-label={`选择${item.label}`} type="checkbox" checked={selected} onChange={onToggle} />
          <span>{item.label}</span>
          <button onClick={onDelete}>删除{item.label}</button>
        </article>
      )}
      {...overrides}
    />,
  )
  return { ...result, onSelectionChange, onDeleteSelected }
}

describe('BacklogPanel', () => {
  it('keeps the queue in a fixed-height scroll container and supports select-all', () => {
    const { container, onSelectionChange } = renderPanel()
    const list = screen.getByRole('region', { name: '测试积压' }).querySelector('[aria-label="测试积压滚动列表"]')
    expect(list?.className).toContain('h-[360px]')
    expect(list?.className).toContain('overflow-y-auto')
    fireEvent.click(screen.getByRole('button', { name: '全选测试积压' }))
    expect(onSelectionChange).toHaveBeenCalledWith(['a', 'b'])
    expect(container.textContent).toContain('岗位 A')
  })

  it('supports an individual delete callback and a batch delete callback', () => {
    const { onDeleteSelected } = renderPanel({ selectedIds: ['a', 'b'] })
    fireEvent.click(screen.getByRole('button', { name: '删除岗位 A' }))
    expect(onDeleteSelected).toHaveBeenCalledWith(['a'])
    fireEvent.click(screen.getByRole('button', { name: /移入回收站/ }))
    expect(onDeleteSelected).toHaveBeenCalledWith(['a', 'b'])
  })

  it('never includes a hidden stale selection in select-all or batch deletion', () => {
    const { onSelectionChange, onDeleteSelected } = renderPanel({ selectedIds: ['a', 'hidden'] })
    fireEvent.click(screen.getByRole('button', { name: /移入回收站/ }))
    expect(onDeleteSelected).toHaveBeenCalledWith(['a'])
    fireEvent.click(screen.getByRole('button', { name: '全选测试积压' }))
    expect(onSelectionChange).toHaveBeenCalledWith(['a', 'b'])
  })

  it('explains a filtered empty list without implying that all pending jobs disappeared', () => {
    renderPanel({ items: [], emptyMessage: '没有符合当前条件的岗位，请调整筛选条件。' })
    expect(screen.getByText('没有符合当前条件的岗位，请调整筛选条件。')).toBeTruthy()
    expect(screen.queryByText('当前没有积压项目。')).toBeNull()
  })
})
