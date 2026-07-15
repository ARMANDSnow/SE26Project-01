import { Navigate, Route, Routes } from "react-router"
import { AppShell } from "@/components/app/app-shell"
import { ChatPage } from "@/features/chat/page"
import { LibraryPage } from "@/features/library/page"
import { PaperDetailPage } from "@/features/paper-detail/page"
import { PapersPage } from "@/features/papers/page"

export default function App() {
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
