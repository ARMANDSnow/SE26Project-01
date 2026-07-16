import type { ReactNode } from "react"
import { AlertTriangle, LockKeyhole } from "lucide-react"
import type { ResearchProjectArtifact } from "@/types"

export function ArtifactState({ artifact, empty, children }: { artifact?: ResearchProjectArtifact | null; empty: string; children: ReactNode }) {
  if (!artifact) return <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">{empty}</p>
  if (artifact.dependency_status === "inaccessible" || artifact.status === "inaccessible") {
    return <div className="flex gap-3 rounded-xl border border-dashed p-4 text-sm text-muted-foreground"><LockKeyhole className="mt-0.5 size-4 shrink-0" /><p>此版本包含当前不可访问的依赖。为避免泄漏，事实文本、标题、引用和关系均已隐藏。</p></div>
  }
  if (artifact.dependency_status === "stale" || artifact.status === "stale") {
    return <div className="flex gap-3 rounded-xl border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-4 text-sm"><AlertTriangle className="mt-0.5 size-4 shrink-0" /><p>此版本的上游资料已经变化。旧事实不再展示；请重新分析以生成当前版本。</p></div>
  }
  return <>{children}</>
}

export function CitationLabels({ keys }: { keys: string[] }) {
  if (!keys.length) return null
  return <span className="flex flex-wrap gap-1" aria-label={`${keys.length} 条引用`}>{keys.map((_key, index) => <span key={`${_key}-${index}`} className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">引用 {index + 1}</span>)}</span>
}
