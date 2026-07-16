import { FolderKanban } from "lucide-react"
import { Link, Navigate, useParams } from "react-router"
import { Button } from "@/components/ui/button"
import { LoadingState } from "@/components/common/loading-state"
import { AddToProjectDialog } from "@/components/research/add-to-project-dialog"
import { useResearchProjectBacklinksQuery } from "@/lib/query-hooks"
import { WorkflowPanel } from "./workflow-panel"
import { useResearchRunLiveQuery } from "./use-research-run-stream"

export function ResearchRunPage() {
  const { runId = "" } = useParams()
  const runQuery = useResearchRunLiveQuery(runId)
  const backlinks = useResearchProjectBacklinksQuery({ item_type: "run", run_id: runId }, Boolean(runId))
  if (!runId) return <Navigate to="/" replace />
  if (runQuery.isLoading) return <LoadingState label="正在恢复 Research Run" skeleton />
  if (runQuery.isError || !runQuery.data) return <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-5 text-sm text-destructive" role="alert"><p>无法加载任务。任务可能不存在、无访问权限，或网络暂时不可用。</p><Button className="mt-3" variant="outline" onClick={() => runQuery.refetch()}>重试加载</Button></div>
  return <div className="mx-auto grid min-h-[calc(100dvh-7rem)] w-full max-w-4xl gap-3">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
      <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground"><FolderKanban className="size-4" /><span>所属研究项目：</span>{backlinks.isLoading ? <span>正在读取…</span> : (backlinks.data ?? []).length ? backlinks.data?.map((item) => <Button key={item.project_id} asChild variant="link" className="h-auto min-h-11 px-1"><Link to={`/library/projects/${item.project_id}`}>{item.project_title}</Link></Button>) : <span>尚未加入</span>}</div>
      {runQuery.data.mode !== "project" ? <AddToProjectDialog item={{ item_type: "run", run_id: runId }} /> : null}
    </div>
    <div className="flex min-h-0"><WorkflowPanel run={runQuery.data} compact /></div>
  </div>
}
