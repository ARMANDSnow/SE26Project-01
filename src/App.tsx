import { Navigate, Route, Routes } from "react-router"
import { AppShell } from "@/components/app/app-shell"
import { ChatPage } from "@/features/chat/page"
import { LibraryPage } from "@/features/library/page"
import { PaperDetailPage } from "@/features/paper-detail/page"
import { PapersPage } from "@/features/papers/page"
import { AuthPage } from "@/features/auth/page"
import { LoadingState } from "@/components/common/loading-state"
import { useCurrentUserQuery } from "@/lib/query-hooks"

export default function App() {
  const userQuery = useCurrentUserQuery()
  if (userQuery.isLoading) {
    return <main className="grid min-h-screen place-items-center"><LoadingState label="正在检查登录状态" /></main>
  }
  if (!userQuery.data) return <AuthPage />

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ChatPage />} />
        <Route path="/papers" element={<PapersPage />} />
        <Route path="/papers/:paperId" element={<PaperDetailPage />} />
        <Route path="/qa" element={<Navigate to="/" replace />} />
        <Route path="/graph" element={<Navigate to="/" replace />} />
        <Route path="/learning" element={<Navigate to="/" replace />} />
        <Route path="/library" element={<LibraryPage />} />
      </Route>
    </Routes>
  )
}
