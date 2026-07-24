import { ExternalLink, Loader2, Quote } from "lucide-react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useProjectEntityEvidenceQuery } from "@/lib/query-hooks"
import type { ProjectEntityEvidence } from "@/types"

const statusLabel = { valid: "有效", stale: "内容已更新", inaccessible: "不可访问", invalid: "无效" } as const

export function CitationEvidenceInspector({ projectId, artifactVersion, entityKind, entityId, open, onOpenChange }: {
  projectId: string
  artifactVersion: number
  entityKind: ProjectEntityEvidence["entity_kind"]
  entityId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const evidence = useProjectEntityEvidenceQuery(projectId, artifactVersion, entityKind, entityId, open)
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b pr-14">
          <SheetTitle>引用与原文证据</SheetTitle>
          <SheetDescription>每次打开都会按当前权限和内容版本重新校验。</SheetDescription>
        </SheetHeader>
        <div className="grid gap-3 overflow-y-auto p-4" aria-live="polite">
          {evidence.isLoading || evidence.isFetching ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />正在重新校验证据</p> : null}
          {evidence.isError ? <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">证据读取失败；未使用旧缓存内容。</p> : null}
          {evidence.data?.dependency_status === "inaccessible" ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">当前权限下只保留安全审计状态，不显示标题、引用标识、章节或原文。</p> : null}
          {evidence.data?.dependency_status !== "inaccessible" ? evidence.data?.citations.map((citation, index) => (
            <article key={citation.citation_id} className="min-w-0 rounded-xl border p-3">
              <div className="flex min-w-0 items-center gap-2"><Quote className="size-4 shrink-0 text-primary" /><strong className="min-w-0 flex-1 break-words text-sm">引用 {citation.citation_label?.match(/\d+/)?.[0] ?? index + 1}</strong><Badge variant="outline">{statusLabel[citation.status]}</Badge></div>
              {citation.status === "valid" ? <>
                <p className="mt-2 break-words text-xs text-muted-foreground [overflow-wrap:anywhere]">{citation.paper_title ? `《${citation.paper_title}》` : "论文"}{citation.heading ? ` · ${citation.heading}` : ""}</p>
                {citation.excerpt ? <blockquote className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-muted/60 p-3 text-sm leading-6 [overflow-wrap:anywhere]">{citation.excerpt}</blockquote> : null}
                {citation.paper_id && citation.chunk_id ? <Button asChild variant="link" className="mt-2 h-auto min-h-11 px-0"><Link to={`/papers/${citation.paper_id}?chunk=${citation.chunk_id}&start=${citation.char_start ?? ""}&end=${citation.char_end ?? ""}&project=${projectId}`}>在论文中定位<ExternalLink className="size-4" /></Link></Button> : null}
              </> : <p className="mt-2 text-sm text-muted-foreground">该引用不再返回事实文本，请重新分析项目。</p>}
            </article>
          )) : null}
          {evidence.isSuccess && evidence.data.dependency_status !== "inaccessible" && !evidence.data.citations.length ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">这个确定性关系不需要模型引用，或当前没有可展示的引用。</p> : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
