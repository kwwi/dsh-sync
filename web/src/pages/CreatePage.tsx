import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RegionPicker, { type BirthPlaceSelection } from '../components/RegionPicker'
import GenerationProgressOverlay, { type ProgressStep } from '../components/GenerationProgressOverlay'
import { generateReportStream } from '../services/reportGenerate'
import { ApiError } from '../services/api'

export default function CreatePage() {
  const nav = useNavigate()
  const [loading, setLoading] = useState(false)
  const [progressOpen, setProgressOpen] = useState(false)
  const [progressCurrent, setProgressCurrent] = useState<ProgressStep | null>(null)
  const [completedSteps, setCompletedSteps] = useState<string[]>([])
  const [birthPlace, setBirthPlace] = useState<BirthPlaceSelection | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const [form, setForm] = useState({
    surname: '',
    gender: 'male',
    birth_datetime: '',
    regionCode: '',
  })

  function validate(): string | null {
    if (!form.surname.trim()) return '请输入姓氏'
    if (!form.birth_datetime) return '请选择出生时间'
    if (!birthPlace) return '请选择出生地（省 / 市 / 区县）'
    return null
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg('')
    const validationError = validate()
    if (validationError) {
      setErrorMsg(validationError)
      return
    }
    if (!birthPlace) return

    setLoading(true)
    setProgressOpen(true)
    setCompletedSteps([])
    setProgressCurrent({ step: 'bazi', title: '八字排盘', summary: '正在启动推算引擎…' })
    try {
      const dt = form.birth_datetime.includes('T')
        ? `${form.birth_datetime}:00+08:00`
        : form.birth_datetime
      const body = {
        surname: form.surname.trim(),
        gender: form.gender,
        birth_datetime: dt,
        birth_place: {
          province: birthPlace.province,
          city: birthPlace.city,
          district: birthPlace.district,
          longitude: birthPlace.longitude,
          latitude: birthPlace.latitude,
        },
        output_count: 10,
      }
      let lastStep = ''
      const res = await generateReportStream(body, (ev) => {
        if (lastStep && lastStep !== ev.step) {
          setCompletedSteps((prev) => (prev.includes(lastStep) ? prev : [...prev, lastStep]))
        }
        lastStep = ev.step
        setProgressCurrent(ev)
      })
      if (lastStep) {
        setCompletedSteps((prev) => (prev.includes(lastStep) ? prev : [...prev, lastStep]))
      }
      setProgressCurrent({ step: 'finalize', title: '汇总报告', summary: '报告已生成，正在跳转…' })
      await new Promise((r) => setTimeout(r, 400))
      nav(`/report/${res.report_id}`)
    } catch (err) {
      const msg = err instanceof ApiError
        ? `请求失败 (${err.statusCode})：${err.body || '请重试'}`
        : err instanceof Error ? err.message : '生成失败，请重试'
      setErrorMsg(msg)
    } finally {
      setLoading(false)
      setProgressOpen(false)
    }
  }

  return (
    <>
      <GenerationProgressOverlay
        open={progressOpen}
        current={progressCurrent}
        completedSteps={completedSteps}
      />
      <section className="card">
        <h2>填写信息</h2>
        <form onSubmit={submit} className="form">
          <label>姓氏<input value={form.surname} placeholder="请输入姓氏" onChange={(e) => setForm({ ...form, surname: e.target.value })} required /></label>
          <label>性别
            <select value={form.gender} onChange={(e) => setForm({ ...form, gender: e.target.value })}>
              <option value="male">男</option>
              <option value="female">女</option>
            </select>
          </label>
          <label>出生时间<input type="datetime-local" value={form.birth_datetime} onChange={(e) => setForm({ ...form, birth_datetime: e.target.value })} required /></label>
          <fieldset className="region-fieldset">
            <legend>出生地</legend>
            <RegionPicker
              value={form.regionCode}
              onChange={(place) => {
                setBirthPlace(place)
                setForm((f) => ({ ...f, regionCode: place.code }))
              }}
            />
            {birthPlace && (
              <p className="region-hint">
                已选：{birthPlace.province} {birthPlace.city} {birthPlace.district}
                （经度 {birthPlace.longitude.toFixed(2)}°，纬度 {birthPlace.latitude.toFixed(2)}°）
              </p>
            )}
          </fieldset>
          {errorMsg && <p className="error-msg">{errorMsg}</p>}
          <button className="btn primary" type="submit" disabled={loading}>
            {loading ? '生成中...' : '生成报告'}
          </button>
        </form>
      </section>
    </>
  )
}
