import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../services/api'

interface ToneSyllable {
  char: string
  pinyin: string
  tone_label: string
}

interface Candidate {
  rank?: number
  full_name: string
  given_name?: string
  meaning: string
  citation_book?: string
  citation_text?: string
  citation_explanation?: string
  wuxing_label?: string
  wuxing?: Record<string, unknown>
  tone?: ToneSyllable[]
  tone_comment?: string
}

interface ReportSection {
  title: string
  content: string
}

interface PreviewReport {
  id: string
  surname: string
  bazi_summary: Record<string, string>
  birth_summary?: Record<string, string>
  fate_vernacular_excerpt: string
  fate_professional_excerpt?: string
  naming_advice_excerpt: string
  candidates_preview: Candidate[]
  paid: boolean
  unlock_hint: string
}

interface FullReport extends PreviewReport {
  birth_summary: Record<string, string>
  bazi_chart_text: string
  wuxing_analysis: string
  naming_advice: string
  fate_analysis: { vernacular: string; professional: string }
  candidates: Candidate[]
  sections?: ReportSection[]
}

interface Plan {
  sku: string
  is_free: boolean
  price_cents: number
}

function PreBlock({ text }: { text: string }) {
  return <pre className="report-pre">{text}</pre>
}

export default function ReportPage() {
  const { id } = useParams()
  const [report, setReport] = useState<PreviewReport | null>(null)
  const [full, setFull] = useState<FullReport | null>(null)
  const [isFree, setIsFree] = useState(false)
  const [error, setError] = useState('')
  const [fullError, setFullError] = useState<'payment' | 'forbidden' | ''>('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    api<PreviewReport>(`/api/v1/report/${id}?tier=preview`)
      .then(setReport)
      .catch((e) => setError(e instanceof ApiError && e.statusCode === 404 ? '报告不存在或已过期' : `加载失败：${e instanceof Error ? e.message : '未知错误'}`))

    api<Plan[]>('/api/v1/pricing/plans?channel=web')
      .then((plans) => {
        const plan = plans.find((p) => p.sku === 'report_full')
        setIsFree(!!(plan?.is_free ?? plan?.price_cents === 0))
      })
      .catch(() => setIsFree(false))

    api<FullReport>(`/api/v1/report/${id}?tier=full`)
      .then((data) => { setFull(data); setFullError('') })
      .catch((e) => {
        if (e instanceof ApiError) {
          if (e.statusCode === 402) setFullError('payment')
          else if (e.statusCode === 403) setFullError('forbidden')
        }
        setFull(null)
      })
      .finally(() => setLoading(false))
  }, [id])

  if (error) {
    return (
      <section className="card">
        <h2>加载失败</h2>
        <p className="disclaimer">{error}</p>
        <Link className="btn primary" to="/create">返回首页</Link>
      </section>
    )
  }
  if (loading && !report) return <p>加载中...</p>
  if (!report) return <p>加载中...</p>

  const data = full
  const candidates = data?.candidates ?? report.candidates_preview
  const birth = data?.birth_summary ?? report.birth_summary

  return (
    <section className="card report-page">
      <h2>智能起名报告</h2>
      <p className="disclaimer">【温馨提示】本报告基于传统文化与经典文献生成，仅供参考，请结合家庭意愿选用。</p>

      {/* 付费提示横幅 */}
      {fullError === 'payment' && (
        <div className="pay-banner">
          <p className="pay-title">🔒 完整报告需解锁</p>
          <p className="pay-desc">解锁后查看全部备选名字、典籍出处和详细分析</p>
          <Link className="btn primary" to={`/report/${id}/unlock`}>解锁完整报告</Link>
        </div>
      )}
      {fullError === 'forbidden' && (
        <div className="pay-banner" style={{ borderColor: '#dc2626', background: '#fef2f2' }}>
          <p className="pay-title" style={{ color: '#991b1b' }}>无权访问</p>
          <p className="pay-desc" style={{ color: '#b91c1c' }}>此报告不属于当前会话，请在原设备上查看</p>
        </div>
      )}

      <h3>基本信息</h3>
      {birth ? (
        <ul className="report-meta">
          {birth['性别'] && <li>性别：{birth['性别']}</li>}
          {birth['出生地点'] && <li>出生地点：{birth['出生地点']}</li>}
          {birth['出生公历_北京'] && <li>出生公历（北京）：{birth['出生公历_北京']}</li>}
          {birth['出生公历_真太阳'] && <li>出生公历（真太阳）：{birth['出生公历_真太阳']}</li>}
          {birth['出生农历'] && <li>出生农历：{birth['出生农历']}</li>}
          {birth['生辰八字'] && <li>生辰八字：{birth['生辰八字']}</li>}
          {birth['生肖'] && <li>生肖：{birth['生肖']}</li>}
        </ul>
      ) : (
        <>
          <p>{report.bazi_summary['四柱']}</p>
          <p>{report.bazi_summary['农历']}</p>
        </>
      )}

      {data?.bazi_chart_text && (
        <>
          <h3>八字命盘</h3>
          <PreBlock text={data.bazi_chart_text} />
        </>
      )}

      {data?.wuxing_analysis && (
        <>
          <h3>五行分析</h3>
          <PreBlock text={data.wuxing_analysis} />
          {data.fate_analysis?.professional && (
            <details className="report-details">
              <summary>专业解读（展开）</summary>
              <PreBlock text={data.fate_analysis.professional} />
            </details>
          )}
        </>
      )}

      <h3>命格简析</h3>
      <p>{data?.fate_analysis?.vernacular ?? report.fate_vernacular_excerpt}</p>

      {data?.naming_advice && (
        <>
          <h3>取名建议</h3>
          <PreBlock text={data.naming_advice} />
        </>
      )}

      <h3>备选名字</h3>
      <ol className="names">
        {candidates?.map((c, i) => (
          <li key={`${c.full_name}-${i}`} className="name-card">
            <strong>{i + 1}、{c.full_name}</strong>
            {c.citation_explanation && <p className="cite">{c.citation_explanation}</p>}
            {full && c.citation_text && !c.citation_explanation && (
              <p className="cite">出自《{c.citation_book}》：{c.citation_text}</p>
            )}
            <p>{c.meaning}</p>
            {(c.wuxing_label || c.wuxing) && (
              <p className="wuxing-tag">[五行属性] {c.wuxing_label ?? String(c.wuxing?.summary ?? '')}</p>
            )}
            {c.tone && c.tone.length > 0 && (
              <p className="tone-tag">
                [音韵] {c.tone.map((t) => `${t.char}(${t.pinyin}/${t.tone_label})`).join(' ')}
                {c.tone_comment ? ` — ${c.tone_comment}` : ''}
              </p>
            )}
          </li>
        ))}
      </ol>

      {/* 底部解锁按钮 */}
      {!full && fullError === 'payment' && (
        <Link className="btn primary" to={`/report/${id}/unlock`}>{report.unlock_hint || '解锁完整报告'}</Link>
      )}
      {!full && !fullError && isFree && (
        <Link className="btn primary" to={`/report/${id}/unlock`}>免费查看完整报告</Link>
      )}
    </section>
  )
}
