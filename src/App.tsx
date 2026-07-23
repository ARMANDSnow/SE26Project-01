import { lazy, Suspense } from "react"
import { Navigate, Route, Routes } from "react-router"
import { AppShell } from "@/components/app/app-shell"
import { AuthPage } from "@/features/auth/page"
import { LoadingState } from "@/components/common/loading-state"
import { useCurrentUserQuery } from "@/lib/query-hooks"

const ChatPage = lazy(() => import("@/features/chat/page").then((module) => ({ default: module.ChatPage })))
const LibraryPage = lazy(() => import("@/features/library/page").then((module) => ({ default: module.LibraryPage })))
const PaperDetailPage = lazy(() => import("@/features/paper-detail/page").then((module) => ({ default: module.PaperDetailPage })))
const PapersPage = lazy(() => import("@/features/papers/page").then((module) => ({ default: module.PapersPage })))
const ResearchRunPage = lazy(() => import("@/features/research/run-page").then((module) => ({ default: module.ResearchRunPage })))
const ResearchProjectPage = lazy(() => import("@/features/projects/project-page").then((module) => ({ default: module.ResearchProjectPage })))
const ResearchReportPage = lazy(() => import("@/features/reports/page").then((module) => ({ default: module.ResearchReportPage })))
const WorkspacesPage = lazy(() => import("@/features/workspaces/page").then((module) => ({ default: module.WorkspacesPage })))

export default function App() {
  const userQuery = useCurrentUserQuery()
  if (userQuery.isLoading) {
    return <main className="grid min-h-screen place-items-center"><LoadingState label="正在检查登录状态" /></main>
  }
  if (userQuery.isError || !userQuery.data) return <AuthPage />

  return (
    <Suspense fallback={<main className="grid min-h-[50vh] place-items-center"><LoadingState label="正在加载工作区" /></main>}>
      <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ChatPage />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/:paperId" element={<PaperDetailPage />} />
        <Route path="/qa" element={<Navigate to="/" replace />} />
        <Route path="/graph" element={<Navigate to="/" replace />} />
        <Route path="/learning" element={<Navigate to="/" replace />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/workspaces" element={<WorkspacesPage />} />
        <Route path="/library/projects/:projectId" element={<ResearchProjectPage />} />
        <Route path="/runs/:runId" element={<ResearchRunPage />} />
        <Route path="/runs/:runId/reports/:version" element={<ResearchReportPage />} />
      </Route>
      </Routes>
    </Suspense>
  )
}
