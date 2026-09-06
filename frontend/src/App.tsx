import { Navigate, Route, Routes } from 'react-router-dom'
import { ProtectedRoute } from './components/auth/ProtectedRoute'
import { AppShell } from './components/layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { RequirementWizardPage } from './pages/RequirementWizardPage'
import { ArchitectureStudioPage } from './pages/ArchitectureStudioPage'
import { ComparisonPage } from './pages/ComparisonPage'
import { BlastRadiusPage } from './pages/BlastRadiusPage'
import { DiagramsPage } from './pages/DiagramsPage'
import { DocsPage } from './pages/DocsPage'
import { SettingsPage } from './pages/SettingsPage'
import { TeamFitPage } from './pages/TeamFitPage'
import { IndustryTwinsPage } from './pages/IndustryTwinsPage'
import { BudgetPage } from './pages/BudgetPage'
import { CausalGraphPage } from './pages/CausalGraphPage'
import { AuthPage } from './pages/AuthPage'
import { HistoryPage } from './pages/HistoryPage'
import { ProfilePage } from './pages/ProfilePage'

function App() {
  return (
    <Routes>
      <Route path="/sign-in" element={<AuthPage mode="sign-in" />} />
      <Route path="/sign-up" element={<AuthPage mode="sign-up" />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/wizard" element={<RequirementWizardPage />} />
          <Route path="/architecture" element={<ArchitectureStudioPage />} />
          <Route path="/causal-graph" element={<CausalGraphPage />} />
          <Route path="/comparison" element={<ComparisonPage />} />
          <Route path="/blast-radius" element={<BlastRadiusPage />} />
          <Route path="/team-fit" element={<TeamFitPage />} />
          <Route path="/industry-twins" element={<IndustryTwinsPage />} />
          <Route path="/budget" element={<BudgetPage />} />
          <Route path="/diagrams" element={<DiagramsPage />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default App
