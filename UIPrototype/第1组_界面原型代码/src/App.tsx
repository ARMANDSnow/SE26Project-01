import { Route, Routes } from "react-router"
import { AppShell } from "@/components/app/app-shell"
import { DashboardPage } from "@/features/dashboard/page"
import { GraphPage } from "@/features/graph/page"
import { LearningPage } from "@/features/learning/page"
import { PaperDetailPage } from "@/features/paper-detail/page"
import { PapersPage } from "@/features/papers/page"
import { QAPage } from "@/features/qa/page"

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/:paperId" element={<PaperDetailPage />} />
        <Route path="/qa" element={<QAPage />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/learning" element={<LearningPage />} />
      </Route>
    </Routes>
  )
}
