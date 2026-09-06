import { Route, Routes } from 'react-router-dom'
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

function App() {
  return (
    <Routes>
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
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}

export default App
