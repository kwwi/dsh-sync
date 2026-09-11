import { Link, Route, Routes } from 'react-router-dom'
import CreatePage from './pages/CreatePage'
import HomePage from './pages/HomePage'
import ReportPage from './pages/ReportPage'
import UnlockPage from './pages/UnlockPage'

export default function App() {
  return (
    <div className="layout">
      <header className="header">
        <Link to="/">智能起名</Link>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/create" element={<CreatePage />} />
          <Route path="/report/:id" element={<ReportPage />} />
          <Route path="/report/:id/unlock" element={<UnlockPage />} />
        </Routes>
      </main>
      <footer className="footer">
        本服务基于传统文化与经典文献，仅供文化学习与家庭参考，不构成命理预测。
      </footer>
    </div>
  )
}
