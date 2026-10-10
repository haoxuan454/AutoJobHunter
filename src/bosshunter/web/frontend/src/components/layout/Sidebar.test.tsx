import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { PipelineFlow } from '@/components/dashboard/PipelineFlow'

afterEach(cleanup)

describe('public application branding', () => {
  it('uses AutoJobHunter in both sidebar locations and links to the user project', () => {
    render(<MemoryRouter><Sidebar pendingReplies={0} /><PipelineFlow /></MemoryRouter>)
    expect(screen.getAllByText('AutoJobHunter')).toHaveLength(2)
    expect(screen.getByText('AJ')).toBeTruthy()
    expect(screen.getByText('AutoJobHunter 自动求职流程')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'AutoJobHunter GitHub' })
    expect(link.getAttribute('href')).toBe('https://github.com/haoxuan454/AutoJobHunter')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noreferrer')
    expect(screen.queryByText(/BossHunter/)).toBeNull()
  })
})
