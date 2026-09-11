import { getSessionId } from './api'

export type ReportProgressEvent = {
  step: string
  title: string
  summary: string
}

export type ReportGenerateResult = {
  report_id: string
  status: string
}

function parseSseChunk(buffer: string): { events: Array<{ event: string; data: unknown }>; rest: string } {
  const events: Array<{ event: string; data: unknown }> = []
  const parts = buffer.split('\n\n')
  const rest = parts.pop() ?? ''
  for (const block of parts) {
    if (!block.trim()) continue
    let event = 'message'
    let dataStr = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
    }
    if (dataStr) {
      try {
        events.push({ event, data: JSON.parse(dataStr) })
      } catch {
        events.push({ event, data: dataStr })
      }
    }
  }
  return { events, rest }
}

export async function generateReportStream(
  body: unknown,
  onProgress: (ev: ReportProgressEvent) => void,
): Promise<ReportGenerateResult> {
  const res = await fetch('/api/v1/report/generate/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Session-Id': getSessionId(),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  if (!res.body) {
    throw new Error('浏览器不支持流式响应')
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const { events, rest } = parseSseChunk(buffer)
    buffer = rest
    for (const { event, data } of events) {
      if (event === 'progress' && data && typeof data === 'object') {
        const d = data as ReportProgressEvent
        onProgress(d)
      } else if (event === 'done' && data && typeof data === 'object') {
        return data as ReportGenerateResult
      } else if (event === 'error') {
        const msg = typeof data === 'object' && data && 'message' in data ? String((data as { message: string }).message) : '生成失败'
        throw new Error(msg)
      }
    }
  }
  throw new Error('推算未完成')
}
