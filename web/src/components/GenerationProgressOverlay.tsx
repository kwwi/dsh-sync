import { useTypewriter } from '../hooks/useTypewriter'

export type ProgressStep = {
  step: string
  title: string
  summary: string
}

const STEP_ORDER = ['bazi', 'analysis', 'fate', 'names', 'finalize']

type Props = {
  open: boolean
  current: ProgressStep | null
  completedSteps: string[]
}

export default function GenerationProgressOverlay({ open, current, completedSteps }: Props) {
  const summary = current?.summary ?? '请稍候…'
  const typed = useTypewriter(open ? summary : '', 24)

  if (!open) return null

  const currentIdx = current ? STEP_ORDER.indexOf(current.step) : 0

  return (
    <div className="progress-overlay" role="dialog" aria-modal="true" aria-labelledby="progress-title">
      <div className="progress-modal">
        <h3 id="progress-title">正在推算命理</h3>
        <ul className="progress-steps">
          {STEP_ORDER.map((id, i) => {
            const done = completedSteps.includes(id) || (current && STEP_ORDER.indexOf(current.step) > i)
            const active = current?.step === id
            const labels: Record<string, string> = {
              bazi: '八字排盘',
              analysis: '命格分析',
              fate: '命理解读',
              names: '典籍起名',
              finalize: '汇总报告',
            }
            return (
              <li key={id} className={done ? 'done' : active ? 'active' : ''}>
                <span className="progress-dot" />
                {labels[id]}
              </li>
            )
          })}
        </ul>
        {current && (
          <div className="progress-detail">
            <p className="progress-step-title">{current.title}</p>
            <p className="progress-summary">
              {typed}
              <span className="progress-cursor" aria-hidden>|</span>
            </p>
          </div>
        )}
        <p className="progress-hint">步骤 {Math.min(currentIdx + 1, STEP_ORDER.length)} / {STEP_ORDER.length}</p>
      </div>
    </div>
  )
}
