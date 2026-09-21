import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import VoiceAssistantPage from './VoiceAssistantPage'

describe('VoiceAssistantPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ reply: '我之前用 Python 做过服务接口和数据处理。', generation_mode: 'configured_model' }), { status: 200, headers: { 'Content-Type': 'application/json' } })))
    vi.stubGlobal('speechSynthesis', { cancel: vi.fn(), speak: vi.fn() })
  })

  afterEach(() => { cleanup(); vi.unstubAllGlobals() })

  it('submits the transcript to the local voice reply API and displays the answer', async () => {
    render(<VoiceAssistantPage />)
    fireEvent.change(screen.getByLabelText('文字降级输入'), { target: { value: '你之前用 Python 做过什么？' } })
    fireEvent.click(screen.getByRole('button', { name: '立即提交' }))
    await waitFor(() => expect(screen.getByText('我之前用 Python 做过服务接口和数据处理。')).toBeTruthy())
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/voice-assistant/reply', expect.objectContaining({ method: 'POST' }))
  })
})
