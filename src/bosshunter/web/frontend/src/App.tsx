import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from './components/layout/Sidebar'
import { Header } from './components/layout/Header'
import DashboardPage from './pages/DashboardPage'
import ConfigPage from './pages/ConfigPage'
import KnowledgePage from './pages/KnowledgePage'
import ConversationsPage from './pages/ConversationsPage'
import ConversationDetailPage from './pages/ConversationDetailPage'
import AnalyticsPage from './pages/AnalyticsPage'
import AssistantLabPage from './pages/AssistantLabPage'

function JobsPage() {
  return <DashboardPage view="jobs" />
}

function MonitorPage() {
  return <DashboardPage view="monitor" />
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen overflow-hidden bg-background text-foreground">
        <Sidebar />
        <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <Header />
          <main className="min-w-0 flex-1 overflow-y-auto p-3 md:p-6">
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/monitor" element={<MonitorPage />} />
              <Route path="/config" element={<ConfigPage />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/conversations" element={<ConversationsPage />} />
              <Route path="/conversations/:id" element={<ConversationDetailPage />} />
              <Route path="/analytics" element={<AnalyticsPage />} />
              <Route path="/assistant-lab" element={<AssistantLabPage />} />
              <Route path="/notifications" element={<Navigate to="/config?section=notifications" replace />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
