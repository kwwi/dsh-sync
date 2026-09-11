import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../services/api'

interface Plan {
  sku: string
  name: string
  description: string
  price_cents: number
  is_free: boolean
  metadata: { original_price_cents?: number }
}

export default function UnlockPage() {
  const { id } = useParams()
  const nav = useNavigate()
  const [plans, setPlans] = useState<Plan[]>([])
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const autoCheckedRef = useRef(false)

  useEffect(() => {
    api<Plan[]>('/api/v1/pricing/plans?channel=web').then(setPlans).catch(() => setPlans([]))
  }, [])

  const plan = plans.find((p) => p.sku === 'report_full')
  const isFree = plan?.is_free ?? plan?.price_cents === 0

  // 免费计划：自动解锁（仅执行一次）
  useEffect(() => {
    if (!id || !isFree || autoCheckedRef.current) return
    autoCheckedRef.current = true
    setLoading(true)
    setError('')
    api<{ free: boolean; status: string }>('/api/v1/payment/checkout', {
      method: 'POST',
      body: JSON.stringify({ report_id: id, plan_sku: 'report_full' }),
    })
      .then(() => nav(`/report/${id}`))
      .catch((e) => {
        const msg = e instanceof ApiError
          ? `解锁失败 (${e.statusCode})，请重试`
          : e instanceof Error ? e.message : '解锁失败'
        setError(msg)
      })
      .finally(() => setLoading(false))
  }, [id, isFree, nav])

  async function handleCheckout() {
    if (!id) return
    setLoading(true)
    setError('')
    try {
      await api('/api/v1/payment/checkout', {
        method: 'POST',
        body: JSON.stringify({ report_id: id, plan_sku: 'report_full' }),
      })
      nav(`/report/${id}`)
    } catch (e) {
      const msg = e instanceof ApiError
        ? `请求失败 (${e.statusCode})：${e.body || '请重试'}`
        : e instanceof Error ? e.message : '操作失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  async function handleRedeem() {
    if (!id) return
    if (!code.trim()) {
      setError('请输入兑换码')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api('/api/v1/payment/redeem', {
        method: 'POST',
        body: JSON.stringify({ report_id: id, code: code.trim() }),
      })
      nav(`/report/${id}`)
    } catch (e) {
      if (e instanceof ApiError && e.statusCode === 400) {
        setError('兑换码无效或已用完')
      } else {
        const msg = e instanceof ApiError
          ? `请求失败 (${e.statusCode})：${e.body || '请重试'}`
          : e instanceof Error ? e.message : '兑换失败'
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  if (isFree && loading) {
    return (
      <section className="card">
        <p>当前免费，正在解锁完整报告…</p>
        {error && <p className="error-msg">{error}</p>}
      </section>
    )
  }

  return (
    <section className="card">
      <h2>解锁完整报告</h2>
      {plan && (
        <div className="price">
          {isFree ? (
            <span className="amount">免费</span>
          ) : (
            <>
              <span className="amount">¥{(plan.price_cents / 100).toFixed(2)}</span>
              {plan.metadata.original_price_cents && (
                <span className="orig">¥{(plan.metadata.original_price_cents / 100).toFixed(2)}</span>
              )}
            </>
          )}
        </div>
      )}
      <p>{plan?.description}</p>

      {isFree && (
        <button className="btn primary" onClick={handleCheckout} disabled={loading}>
          {loading ? '处理中...' : '免费查看完整报告'}
        </button>
      )}

      {!isFree && (
        <>
          <p className="disclaimer">您购买的是起名报告生成服务，非占卜或改运服务。</p>
          <div className="redeem-section">
            <label>兑换码
              <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="请输入兑换码" />
            </label>
            <button className="btn primary" onClick={handleRedeem} disabled={loading || !code.trim()}>
              {loading ? '兑换中...' : '使用兑换码'}
            </button>
          </div>
        </>
      )}

      {error && <p className="error-msg">{error}</p>}
    </section>
  )
}
