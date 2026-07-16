import { CircleAlert, CircleCheck, Clock3, Loader2, Pause, Play, RotateCcw, Square } from "lucide-react"
import { Navigate, useParams } from "react-router"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { LoadingState } from "@/components/common/loading-state"
import { useResearchRunControlMutation, useResearchRunQuery } from "@/lib/query-hooks"
import { researchStatusLabel, researchStatusTone, researchStepStatusLabel } from "./status"

const stepIcon = {
  completed: CircleCheck,
  running: Loader2,
  failed: CircleAlert,
} as const

export function ResearchRunPage() {
  const { runId = "" } = useParams()
  const runQuery = useResearchRunQuery(runId)
  const control = useResearchRunControlMutation(runId)
  if (!runId) return <Navigate to="/" replace />
  if (runQuery.isLoading) return <LoadingState label="正在恢复 Research Run" skeleton />
  if (runQuery.isError || !runQuery.data) {
    return (
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-5 text-sm text-destructive" role="alert">
        <p>无法加载任务。任务可能不存在、无访问权限，或网络暂时不可用。</p>
        <Button className="mt-3" variant="outline" onClick={() => runQuery.refetch()}>重试加载</Button>
      </div>
    )
  }
  const run = runQuery.data
  const canPause = ["queued", "running"].includes(run.status) && !run.requested_action
  const canResume = run.status === "paused"
  const canCancel = !["completed", "failed", "cancelled"].includes(run.status) && run.requested_action !== "cancel"
  const canRetry = run.status === "failed"

  return (
    <div className="grid gap-5">
      <Card>
        <CardHeader className="gap-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <CardTitle className="text-xl">{run.title}</CardTitle>
              <CardDescription className="mt-2 max-w-3xl whitespace-pre-wrap text-sm leading-6">{run.goal}</CardDescription>
            </div>
            <Badge variant={researchStatusTone[run.status]} aria-live="polite">
              {researchStatusLabel[run.status]}
            </Badge>
          </div>
          <div className="flex flex-wrap gap-2">
            {canPause ? <Button variant="outline" onClick={() => control.mutate("pause")} disabled={control.isPending}><Pause className="size-4" />安全暂停</Button> : null}
            {canResume ? <Button onClick={() => control.mutate("resume")} disabled={control.isPending}><Play className="size-4" />继续</Button> : null}
            {canCancel ? <Button variant="outline" onClick={() => control.mutate("cancel")} disabled={control.isPending}><Square className="size-4" />停止</Button> : null}
            {canRetry ? <Button onClick={() => control.mutate("retry")} disabled={control.isPending}><RotateCcw className="size-4" />重试</Button> : null}
          </div>
          {run.requested_action ? (
            <p className="text-sm text-muted-foreground" role="status">
              请求已发送，正在等待安全边界{run.requested_action === "pause" ? "暂停" : "停止"}。
            </p>
          ) : null}
          {control.isError ? (
            <p className="text-sm text-destructive" role="alert">控制请求失败，任务状态没有被客户端假定改变，请重试。</p>
          ) : null}
        </CardHeader>
      </Card>

      <section aria-labelledby="run-steps-title">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="run-steps-title" className="text-base font-semibold">执行步骤</h2>
          <span className="font-mono text-xs text-muted-foreground">{run.id}</span>
        </div>
        <div className="grid gap-3">
          {(run.steps ?? []).length === 0 ? (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">该 Run 暂无可展示步骤。</p>
          ) : null}
          {(run.steps ?? []).map((step) => {
            const Icon = stepIcon[step.status as keyof typeof stepIcon] ?? Clock3
            return (
              <Card key={step.id}>
                <CardContent className="flex min-h-20 items-start gap-3 p-4">
                  <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-full bg-muted">
                    <Icon className={step.status === "running" ? "size-4 animate-spin motion-reduce:animate-none" : "size-4"} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="font-medium">{step.title}</h3>
                      <Badge variant="outline">{researchStepStatusLabel[step.status]}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">{step.agent_name} · 第 {step.attempt_count}/{step.max_attempts} 次尝试</p>
                    {step.output.scaffold_only ? <p className="mt-2 text-xs text-muted-foreground">Harness 骨架输出；未执行论文调研或外部调用。</p> : null}
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </section>
    </div>
  )
}
