import { Navigate, useParams } from "react-router"
import { Button } from "@/components/ui/button"
import { LoadingState } from "@/components/common/loading-state"
import { WorkflowPanel } from "./workflow-panel"
import { useResearchRunLiveQuery } from "./use-research-run-stream"

export function ResearchRunPage() {
  const { runId = "" } = useParams()
  const runQuery = useResearchRunLiveQuery(runId)
  if (!runId) return <Navigate to="/" replace />
  if (runQuery.isLoading) return <LoadingState label="正在恢复 Research Run" skeleton />
  if (runQuery.isError || !runQuery.data) return <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-5 text-sm text-destructive" role="alert"><p>无法加载任务。任务可能不存在、无访问权限，或网络暂时不可用。</p><Button className="mt-3" variant="outline" onClick={() => runQuery.refetch()}>重试加载</Button></div>
  return <div className="mx-auto flex min-h-[calc(100dvh-7rem)] w-full max-w-4xl"><WorkflowPanel run={runQuery.data} compact /></div>
}
