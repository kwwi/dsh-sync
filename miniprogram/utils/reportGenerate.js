function _app() { return getApp() }

const STEP_ORDER = ['bazi', 'analysis', 'fate', 'names', 'finalize']
const STEP_LABELS = {
  bazi: '八字排盘',
  analysis: '命格分析',
  fate: '命理解读',
  names: '典籍起名',
  finalize: '汇总报告',
}

function parseSseBuffer(buffer) {
  const events = []
  const parts = buffer.split('\n\n')
  const rest = parts.pop() || ''
  parts.forEach((block) => {
    if (!block.trim()) return
    let event = 'message'
    let dataStr = ''
    block.split('\n').forEach((line) => {
      if (line.indexOf('event:') === 0) event = line.slice(6).trim()
      else if (line.indexOf('data:') === 0) dataStr += line.slice(5).trim()
    })
    if (dataStr) {
      try {
        events.push({ event, data: JSON.parse(dataStr) })
      } catch (e) {
        events.push({ event, data: dataStr })
      }
    }
  })
  return { events, rest }
}

function decodeChunk(arrayBuffer) {
  if (typeof TextDecoder !== 'undefined') {
    return new TextDecoder('utf-8').decode(new Uint8Array(arrayBuffer))
  }
  const bytes = new Uint8Array(arrayBuffer)
  let s = ''
  for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i])
  try {
    return decodeURIComponent(escape(s))
  } catch (e) {
    return s
  }
}

function generateReportStream(body, onProgress) {
  return new Promise((resolve, reject) => {
    let buffer = ''
    let finished = false

    const reqTask = wx.request({
      url: `${_app().globalData.apiBase}/api/v1/report/generate/stream`,
      method: 'POST',
      data: body,
      enableChunked: true,
      header: {
        'Content-Type': 'application/json',
        'X-Session-Id': _app().globalData.sessionId,
      },
      success(res) {
        if (finished) return
        if (buffer) {
          const parsed = parseSseBuffer(buffer + '\n\n')
          parsed.events.forEach(({ event, data }) => {
            if (event === 'progress' && data) onProgress(data)
            else if (event === 'done' && data) {
              finished = true
              resolve(data)
            } else if (event === 'error') {
              finished = true
              reject(new Error((data && data.message) || '生成失败'))
            }
          })
        }
        if (!finished) {
          reject(new Error('推算未完成'))
        }
      },
      fail: reject,
    })

    if (reqTask && reqTask.onChunkReceived) {
      reqTask.onChunkReceived((res) => {
        buffer += decodeChunk(res.data)
        const parsed = parseSseBuffer(buffer)
        buffer = parsed.rest
        parsed.events.forEach(({ event, data }) => {
          if (event === 'progress' && data) onProgress(data)
          else if (event === 'done' && data) {
            finished = true
            resolve(data)
          } else if (event === 'error') {
            finished = true
            reject(new Error((data && data.message) || '生成失败'))
          }
        })
      })
      reqTask.onHeadersReceived && reqTask.onHeadersReceived(() => {})
    } else {
      // 降级路径：不支持流式传输时模拟进度
      const steps = [
        { step: 'bazi', title: '八字排盘', summary: '正在换算真太阳时并排定四柱干支…' },
        { step: 'analysis', title: '命格分析', summary: '正在推算五行旺衰、日主强弱…' },
        { step: 'fate', title: '命理解读', summary: '正在结合典籍规则推导喜用神…' },
        { step: 'names', title: '语料检索', summary: '正在从典籍库中匹配五行喜用的字词…' },
        { step: 'names', title: '音韵分析', summary: '正在分析姓与候选名的平仄搭配…' },
        { step: 'names', title: '创作候选名', summary: '正在运用古典意象创作候选名字…' },
        { step: 'names', title: '精选排名', summary: '正在对候选名进行深度解读与排名…' },
      ]
      let stepIdx = 0
      const stepTimer = setInterval(() => {
        if (stepIdx < steps.length) {
          onProgress(steps[stepIdx])
          stepIdx += 1
        }
      }, 1200)
      request('/api/v1/report/generate', 'POST', body)
        .then((data) => {
          clearInterval(stepTimer)
          onProgress({ step: 'finalize', title: '汇总报告', summary: '报告已生成。' })
          resolve(data)
        })
        .catch((err) => {
          clearInterval(stepTimer)
          reject(err)
        })
    }
  })
}

function request(path, method, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${_app().globalData.apiBase}${path}`,
      method,
      data,
      header: {
        'Content-Type': 'application/json',
        'X-Session-Id': _app().globalData.sessionId,
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data)
        else reject(res.data)
      },
      fail: reject,
    })
  })
}

module.exports = {
  STEP_ORDER,
  STEP_LABELS,
  generateReportStream,
}
