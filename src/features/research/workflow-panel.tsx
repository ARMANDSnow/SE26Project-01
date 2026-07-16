import { useId, useState } from "react"
import {
  AlertCircle, Check, ChevronDown, Circle, Clock3, Loader2, Pause,
  Play, RotateCcw, ShieldAlert, Square, X,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog, AlertDialogActionButton, AlertDialogCancelButton, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { cn } from "@/lib/utils"
import { useResearchRunControlMutation, useResolveResearchDecisionMutation } from "@/lib/query-hooks"
import type { ResearchDecision, ResearchRun, ResearchStep, ResearchStepStatus } from "@/types"
import { researchStatusLabel, researchStatusTone, researchStepStatusLabel } from "./status"

const stepIcon: Partial<Record<ResearchStepStatus, typeof Circle>> = {
  running: Loader2, completed: Check, failed: AlertCircle, waiting_input: Clock3,
  cancelled: X, paused: Pause,
}

function safeOutput(output: Record<string, unknown>) {
  const entries = Object.entries(output).filter(([, value]) => ["string", "number", "boolean"].includes(typeof value))
  return entries.slice(0, 8)
}

function WorkflowStep({ step, expanded, onToggle }: { step: ResearchStep; expanded: boolean; onToggle: () => void }) {
  const Icon = stepIcon[step.status] ?? Circle
  const output = safeOutput(step.output)
  return (
    <article className="rounded-xl border bg-card">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="flex min-h-14 w-full items-center gap-3 rounded-xl px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted" aria-hidden="true">
          <Icon className={cn("size-4", step.status === "running" && "animate-spin motion-reduce:animate-none")} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{step.title}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{researchStepStatusLabel[step.status]} · attempt {step.attempt_count}/{step.max_attempts}</span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform motion-reduce:transition-none", expanded && "rotate-180")} />
      </button>
      {expanded ? (
        <div className="border-t px-4 py-3 text-xs leading-5 text-muted-foreground">
          <p>执行者：{step.agent_name}</p>
          {step.output.scaffold_only ? <p className="mt-1">Harness 骨架输出；未执行论文检索、导入或模型研究。</p> : null}
          {output.length ? (
            <dl className="mt-2 grid gap-1 rounded-lg bg-muted/50 p-2">
              {output.map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(0,7rem)_1fr] gap-2"><dt className="truncate font-mono">{key}</dt><dd className="break-words text-foreground">{String(value)}</dd></div>)}
            </dl>
          ) : null}
          {step.status === "failed" ? <p className="mt-2 text-destructive">本步骤失败。仅显示安全错误摘要。</p> : null}
        </div>
      ) : null}
    </article>
  )
}

function DecisionCard({ runId, decision, instanceId }: { runId: string; decision: ResearchDecision; instanceId: string }) {
  const mutation = useResolveResearchDecisionMutation(runId)
  if (decision.status !== "pending") return null
  return (
    <section className="rounded-xl border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-4" aria-labelledby={`${instanceId}-decision-${decision.id}`}>
      <p className="mb-1 flex items-center gap-2 text-xs font-semibold text-[var(--status-waiting-fg)]"><ShieldAlert className="size-4" />需要你的确认</p>
      <h3 id={`${instanceId}-decision-${decision.id}`} className="text-sm font-medium leading-6">{decision.question}</h3>
      <div className="mt-3 grid gap-2">
        {decision.options.map((option) => {
          const recommended = option.id === decision.recommended_option
          return (
            <Button key={option.id} variant={recommended ? "default" : "outline"} className="h-auto min-h-11 justify-start whitespace-normal py-2 text-left" disabled={mutation.isPending} onClick={() => mutation.mutate({ decisionId: decision.id, optionId: option.id })}>
              <span><span className="block">{option.label}{recommended ? " · 推荐" : ""}</span>{option.description ? <span className="mt-0.5 block text-xs font-normal opacity-80">{option.description}</span> : null}</span>
            </Button>
          )
        })}
      </div>
      {mutation.isError ? <p className="mt-2 text-xs text-destructive" role="alert">提交失败，任务状态未被客户端改变。</p> : null}
    </section>
  )
}

function RunControls({ run }: { run: ResearchRun }) {
  const mutation = useResearchRunControlMutation(run.id)
  const canPause = ["queued", "running"].includes(run.status) && !run.requested_action
  const canResume = run.status === "paused"
  const canCancel = !["completed", "failed", "cancelled"].includes(run.status) && run.requested_action !== "cancel"
  const canRetry = run.status === "failed"
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {canPause ? <Button size="sm" variant="outline" className="min-h-11" disabled={mutation.isPending} onClick={() => mutation.mutate("pause")}><Pause className="size-4" />暂停</Button> : null}
        {canResume ? <Button size="sm" className="min-h-11" disabled={mutation.isPending} onClick={() => mutation.mutate("resume")}><Play className="size-4" />继续</Button> : null}
        {canCancel ? (
          <AlertDialog>
            <AlertDialogTrigger asChild><Button size="sm" variant="outline" className="min-h-11" disabled={mutation.isPending}><Square className="size-4" />停止</Button></AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader><AlertDialogTitle>停止这项研究？</AlertDialogTitle><AlertDialogDescription>任务将在安全边界取消。已保存的步骤和事件不会删除，此操作不能用“继续”恢复。</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancelButton>返回</AlertDialogCancelButton><AlertDialogActionButton onClick={() => mutation.mutate("cancel")}>确认停止</AlertDialogActionButton></AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        ) : null}
        {canRetry ? <Button size="sm" className="min-h-11" disabled={mutation.isPending} onClick={() => mutation.mutate("retry")}><RotateCcw className="size-4" />重试</Button> : null}
      </div>
      {run.requested_action ? <p className="mt-2 text-xs text-muted-foreground" role="status">请求已提交，正在等待安全边界{run.requested_action === "pause" ? "暂停" : "停止"}。</p> : null}
      {mutation.isError ? <p className="mt-2 text-xs text-destructive" role="alert">控制失败，未假定任务已改变。</p> : null}
    </div>
  )
}

export function WorkflowPanel({ run, onClose, compact = false }: { run: ResearchRun; onClose?: () => void; compact?: boolean }) {
  const steps = run.steps ?? []
  const completed = steps.filter((step) => step.status === "completed").length
  const decisions = (run.decisions ?? []).filter((decision) => decision.status === "pending")
  const [expandedStepId, setExpandedStepId] = useState(() => steps.find((step) => ["running", "failed"].includes(step.status))?.id ?? "")
  const instanceId = useId().replace(/:/g, "")
  return (
    <div className={cn("flex min-h-0 flex-1 flex-col bg-[var(--surface-raised)]", compact && "rounded-xl border")}>
      <header className="border-b p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Research Workflow</p><h2 className="mt-1 line-clamp-2 text-base font-semibold">{run.title}</h2></div>
          {onClose ? <Button size="icon" variant="ghost" className="size-11 shrink-0" aria-label="关闭 Workflow" onClick={onClose}><X className="size-4" /></Button> : null}
        </div>
        <div className="mt-3 flex items-center justify-between gap-3"><Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge><span className="text-xs tabular-nums text-muted-foreground">{completed}/{steps.length} 步</span></div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Research Workflow 进度" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={completed}><span className="block h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none" style={{ width: `${steps.length ? completed / steps.length * 100 : 0}%` }} /></div>
        <p className="sr-only" aria-live={compact ? undefined : "polite"}>{researchStatusLabel[run.status]}，已完成 {completed} / {steps.length} 步</p>
        <div className="mt-4"><RunControls run={run} /></div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="mb-4 rounded-lg border bg-muted/45 p-3 text-xs leading-5 text-muted-foreground"><strong className="text-foreground">当前为 Harness 骨架。</strong> 仅执行下方三步确定性流程，不代表论文调研已完成。</div>
        {decisions.length ? <div className="mb-4 grid gap-3">{decisions.map((decision) => <DecisionCard key={decision.id} runId={run.id} decision={decision} instanceId={instanceId} />)}</div> : null}
        <section aria-labelledby={`${instanceId}-steps`}><h3 id={`${instanceId}-steps`} className="mb-2 text-sm font-semibold">真实执行步骤</h3><div className="grid gap-2">{steps.map((step) => <WorkflowStep key={step.id} step={step} expanded={expandedStepId === step.id} onToggle={() => setExpandedStepId((current) => current === step.id ? "" : step.id)} />)}</div></section>
        {run.error_message ? <div className="mt-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive" role="alert">任务失败：{run.error_message}</div> : null}
      </div>
    </div>
  )
}
