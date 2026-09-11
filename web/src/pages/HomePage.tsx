import { Link } from 'react-router-dom'

export default function HomePage() {
  return (
    <section className="card">
      <h1>智能起名</h1>
      <p>根据生辰八字与中华经典文献，为您推荐寓意美好的名字。</p>
      <div className="disclaimer">
        【温馨提示】本报告由传统文献与智能技术辅助生成，喜用神分析及名字建议仅供参考。
      </div>
      <Link className="btn primary" to="/create">开始起名</Link>
    </section>
  )
}
