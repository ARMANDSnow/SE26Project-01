import { useEffect, useId, useRef, useState } from "react"
import { Link } from "react-router"
import {
  AlertCircle, BookOpenText, Check, ChevronDown, Circle, ExternalLink, Loader2,
  Pause, Play, RotateCcw, Search, ShieldAlert, Square, X,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  AlertDialog, AlertDialogActionButton, AlertDialogCancelButton, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import {
  useResearchArtifactsQuery, useResearchRunControlMutation, useResearchRunPapersQuery,
  useResolveResearchDecisionMutation,
} from "@/lib/query-hooks"
import type {
  PaperBrief, ResearchArtifact, ResearchBrief, ResearchDecision, ResearchRun,
  ResearchRunPaper, ResearchStep, ResearchStepStatus, ResearchToolCallSummary,
} from "@/types"
import { researchStatusLabel, researchStatusTone, researchStepStatusLabel } from "./status"

const stepIcon: Partial<Record<ResearchStepStatus, typeof Circle>> = {
  running: Loader2, completed: Check, failed: AlertCircle, waiting_input: ShieldAlert,
  cancelled: X, paused: Pause,
}

const stageLabel: Record<ResearchRunPaper["stage"], string> = {
  candidate: "候选", selected: "入选", excluded: "排除", fulltext_ready: "全文就绪",
  read: "已阅读", extracted: "已抽取",
}

function toolSummaries(step: ResearchStep): ResearchToolCallSummary[] {
  const value = step.output.tool_calls
  if (!Array.isArray(value)) return []
  return value.filter((item): item is ResearchToolCallSummary => {
    if (!item || typeof item !== "object") return false
    const row = item as Record<string, unknown>
    return typeof row.tool === "string" && typeof row.summary === "string" && typeof row.attempt === "number"
  })
}

function safeOutput(output: Record<string, unknown>) {
  const hidden = new Set(["tool_calls", "evidence_refs"])
  return Object.entries(output)
    .filter(([key, value]) => !hidden.has(key) && ["string", "number", "boolean"].includes(typeof value))
    .slice(0, 10)
}

function WorkflowStep({ step, expanded, onToggle, instanceId }: {
  step: ResearchStep; expanded: boolean; onToggle: () => void; instanceId: string
}) {
  const Icon = stepIcon[step.status] ?? Circle
  const output = safeOutput(step.output)
  const tools = toolSummaries(step)
  const detailId = `${instanceId}-step-${step.id}`
  return (
    <article className="min-w-0 rounded-xl border bg-card">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={detailId}
        onClick={onToggle}
        className="flex min-h-14 w-full items-center gap-3 rounded-xl px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted" aria-hidden="true">
          <Icon className={cn("size-4", step.status === "running" && "animate-spin motion-reduce:animate-none")} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block break-words text-sm font-medium">{step.title}</span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{researchStepStatusLabel[step.status]} · attempt {step.attempt_count}/{step.max_attempts}</span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform motion-reduce:transition-none", expanded && "rotate-180")} />
      </button>
      {expanded ? (
        <div id={detailId} className="min-w-0 border-t px-4 py-3 text-xs leading-5 text-muted-foreground">
          <p>执行者：{step.agent_name}</p>
          {step.output.scaffold_only ? <p className="mt-1">Harness 骨架输出；未执行论文检索、导入或模型研究。</p> : null}
          {tools.length ? (
            <section className="mt-3" aria-label="工具执行摘要">
              <p className="font-medium text-foreground">工具执行</p>
              <div className="mt-1 grid gap-2">
                {tools.map((tool, index) => (
                  <div key={`${tool.tool}-${index}`} className="min-w-0 rounded-lg bg-muted/55 p-2">
                    <div className="flex flex-wrap items-center gap-2"><code className="break-all font-mono text-foreground">{tool.tool}</code><Badge variant="outline">{tool.status}</Badge><span>attempt {tool.attempt}</span></div>
                    <p className="mt-1 break-words">{tool.summary}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
          {output.length ? (
            <dl className="mt-2 grid gap-1 rounded-lg bg-muted/50 p-2">
              {output.map(([key, value]) => <div key={key} className="grid min-w-0 grid-cols-[minmax(0,7rem)_1fr] gap-2"><dt className="truncate font-mono">{key}</dt><dd className="break-words text-foreground [overflow-wrap:anywhere]">{String(value)}</dd></div>)}
            </dl>
          ) : null}
          {step.status === "failed" ? <p className="mt-2 text-destructive">本步骤失败。仅显示稳定错误码和安全摘要。</p> : null}
        </div>
      ) : null}
    </article>
  )
}

function DecisionCard({ runId, decision, instanceId, autoFocus, returnFocusRef }: {
  runId: string; decision: ResearchDecision; instanceId: string; autoFocus: boolean;
  returnFocusRef: React.RefObject<HTMLElement | null>
}) {
  const mutation = useResolveResearchDecisionMutation(runId)
  const cardRef = useRef<HTMLElement>(null)
  useEffect(() => { if (autoFocus) cardRef.current?.focus() }, [autoFocus, decision.id])
  if (decision.status !== "pending") return null
  return (
    <section ref={cardRef} tabIndex={-1} className="rounded-xl border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-labelledby={`${instanceId}-decision-${decision.id}`}>
      <p className="mb-1 flex items-center gap-2 text-xs font-semibold text-[var(--status-waiting-fg)]"><ShieldAlert className="size-4" />需要你的确认</p>
      <h3 id={`${instanceId}-decision-${decision.id}`} className="text-sm font-medium leading-6">{decision.question}</h3>
      <div className="mt-3 grid gap-2">
        {decision.options.map((option) => {
          const recommended = option.id === decision.recommended_option
          return (
            <Button key={option.id} variant={recommended ? "default" : "outline"} className="h-auto min-h-11 justify-start whitespace-normal py-2 text-left" disabled={mutation.isPending} onClick={() => mutation.mutate({ decisionId: decision.id, optionId: option.id }, { onSuccess: () => requestAnimationFrame(() => returnFocusRef.current?.focus()) })}>
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
              <AlertDialogHeader><AlertDialogTitle>停止这项研究？</AlertDialogTitle><AlertDialogDescription>任务将在安全边界取消。已保存的步骤、论文关联和 Artifact 不会删除。</AlertDialogDescription></AlertDialogHeader>
              <AlertDialogFooter><AlertDialogCancelButton className="min-h-11">返回</AlertDialogCancelButton><AlertDialogActionButton className="min-h-11" onClick={() => mutation.mutate("cancel")}>确认停止</AlertDialogActionButton></AlertDialogFooter>
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

function isResearchBrief(content: Record<string, unknown>): content is ResearchBrief {
  return typeof content.topic === "string" && Array.isArray(content.research_questions)
    && typeof content.scope === "string" && typeof content.date_range === "object"
    && content.date_range !== null && Array.isArray(content.preferred_sources)
    && typeof content.output_language === "string"
}

function isPaperBrief(content: Record<string, unknown>): content is PaperBrief {
  return typeof content.paper_id === "number" && typeof content.title === "string"
    && typeof content.research_question === "string" && typeof content.method === "string"
    && typeof content.dataset === "string" && typeof content.experiments === "string"
    && Array.isArray(content.key_findings) && Array.isArray(content.limitations)
    && Array.isArray(content.evidence_ids) && content.evidence_ids.every((item) => item && typeof item === "object" && typeof (item as { chunk_id?: unknown }).chunk_id === "number")
}

function BriefSummary({ artifact }: { artifact?: ResearchArtifact }) {
  if (!artifact || !isResearchBrief(artifact.content)) return <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">ResearchBrief 尚未由真实步骤生成。</p>
  const brief = artifact.content
  const years = [brief.date_range.start_year, brief.date_range.end_year].filter(Boolean).join("–") || "未限定"
  return (
    <section className="min-w-0 rounded-xl border bg-muted/35 p-3" aria-label="ResearchBrief 摘要">
      <div className="flex items-center justify-between gap-2"><h3 className="break-words text-sm font-semibold">{brief.topic}</h3><Badge variant="outline">v{artifact.version}</Badge></div>
      <p className="mt-2 break-words text-xs leading-5 text-muted-foreground">{brief.scope}</p>
      <dl className="mt-2 grid gap-1 text-xs"><div><dt className="inline text-muted-foreground">研究问题：</dt><dd className="inline">{brief.research_questions.join("；")}</dd></div><div><dt className="inline text-muted-foreground">年份：</dt><dd className="inline">{years}</dd></div><div><dt className="inline text-muted-foreground">来源/语言：</dt><dd className="inline">{brief.preferred_sources.join(" + ")} · {brief.output_language}</dd></div></dl>
    </section>
  )
}

function BudgetSummary({ run }: { run: ResearchRun }) {
  if (run.mode !== "topic") return null
  const items = [
    ["候选", run.usage.candidate_papers ?? 0, run.budget.max_candidates ?? 0],
    ["全文", run.usage.fulltext_papers ?? 0, run.budget.max_fulltext_papers ?? 0],
    ["模型", run.usage.model_calls ?? 0, run.budget.max_model_calls ?? 0],
    ["工具", run.usage.tool_calls ?? 0, run.budget.max_tool_calls ?? 0],
    ["时长（秒）", run.usage.wall_clock_seconds ?? 0, run.budget.max_wall_clock_seconds ?? 0],
  ] as const
  return <section className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-5" aria-label="实际预算使用">{items.map(([label, used, limit]) => <div key={label} className="min-w-0 rounded-lg bg-muted/50 p-2 text-center"><strong className="block truncate font-mono text-foreground">{used}/{limit}</strong><span className="text-muted-foreground">{label}</span></div>)}</section>
}

function PaperList({ papers }: { papers: ResearchRunPaper[] }) {
  const [filter, setFilter] = useState<"all" | ResearchRunPaper["stage"]>("all")
  const stageSets: Partial<Record<ResearchRunPaper["stage"], ResearchRunPaper["stage"][]>> = {
    selected: ["selected", "fulltext_ready", "read", "extracted"],
    fulltext_ready: ["fulltext_ready", "read", "extracted"],
    read: ["read", "extracted"],
  }
  const visible = papers.filter((paper) => filter === "all" || (stageSets[filter] ?? [filter]).includes(paper.stage))
  return (
    <section aria-label="调研论文列表">
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {(["all", "candidate", "selected", "excluded", "fulltext_ready", "read", "extracted"] as const).map((value) => <Button key={value} size="sm" variant={filter === value ? "default" : "outline"} aria-pressed={filter === value} className="min-h-11 shrink-0" onClick={() => setFilter(value)}>{value === "all" ? `全部 ${papers.length}` : stageLabel[value]}</Button>)}
      </div>
      <div className="grid gap-2">
        {visible.map((paper) => (
          <article key={paper.paper_id} className="min-w-0 rounded-xl border bg-card p-3">
            <div className="flex min-w-0 items-start gap-2"><span className="shrink-0 font-mono text-xs text-muted-foreground">{paper.rank ? `#${paper.rank}` : "—"}</span><div className="min-w-0 flex-1"><h3 className="break-words text-sm font-medium [overflow-wrap:anywhere]">{paper.title}</h3><p className="mt-1 break-all text-xs text-muted-foreground">{paper.source}:{paper.source_id} · {paper.published_at.slice(0, 4)}</p></div><Badge variant="outline">{stageLabel[paper.stage]}</Badge></div>
            {paper.score != null ? <p className="mt-2 text-xs">评分：<span className="font-mono">{paper.score}</span></p> : null}
            {paper.inclusion_reason || paper.exclusion_reason ? <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">{paper.inclusion_reason ?? paper.exclusion_reason}</p> : null}
            <Button asChild variant="link" className="mt-1 min-h-11 h-auto px-0"><Link to={`/papers/${paper.paper_id}`}>打开论文<ExternalLink className="size-3.5" /></Link></Button>
          </article>
        ))}
        {!visible.length ? <p className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">当前筛选没有数据库记录。</p> : null}
      </div>
    </section>
  )
}

function PaperBriefList({ artifacts, instanceId }: { artifacts: ResearchArtifact[]; instanceId: string }) {
  const [expanded, setExpanded] = useState("")
  const briefs = artifacts.filter((artifact) => artifact.artifact_type === "paper_brief" && isPaperBrief(artifact.content))
  return <div className="grid gap-2">{briefs.map((artifact) => {
    const brief = artifact.content as PaperBrief
    const open = expanded === artifact.id
    const detailId = `${instanceId}-paper-brief-${artifact.id}`
    return <article key={artifact.id} className="min-w-0 rounded-xl border bg-card"><button type="button" className="flex min-h-14 w-full items-center gap-3 p-3 text-left" aria-expanded={open} aria-controls={detailId} onClick={() => setExpanded(open ? "" : artifact.id)}><BookOpenText className="size-4 shrink-0 text-primary" /><span className="min-w-0 flex-1"><span className="block break-words text-sm font-medium">{brief.title}</span><span className="mt-1 block text-xs text-muted-foreground">{brief.year} · v{artifact.version} · {artifact.is_current ? "source hash 有效" : "source hash 已失效"}</span></span><ChevronDown className={cn("size-4 shrink-0", open && "rotate-180")} /></button>{open ? <div id={detailId} className="grid gap-3 border-t p-3 text-xs leading-5"><div><strong>研究问题</strong><p className="break-words text-muted-foreground">{brief.research_question}</p></div><div><strong>方法</strong><p className="break-words text-muted-foreground">{brief.method}</p></div><div><strong>数据集与实验</strong><p className="break-words text-muted-foreground">{brief.dataset || "未报告"}；{brief.experiments || "未报告"}</p></div><div><strong>主要发现</strong><ul className="list-disc pl-5 text-muted-foreground">{brief.key_findings.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div><div><strong>局限</strong><ul className="list-disc pl-5 text-muted-foreground">{brief.limitations.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div><div><strong>证据</strong><p className="break-words text-muted-foreground">{brief.evidence_ids.map((item) => `chunk ${item.chunk_id}`).join(" · ")}</p></div></div> : null}</article>
  })}{!briefs.length ? <p className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">PaperBrief 尚未由 Extraction Agent 写入。</p> : null}</div>
}

export function WorkflowPanel({ run, onClose, compact = false }: { run: ResearchRun; onClose?: () => void; compact?: boolean }) {
  const steps = run.steps ?? []
  const completed = steps.filter((step) => step.status === "completed").length
  const decisions = (run.decisions ?? []).filter((decision) => decision.status === "pending")
  const artifactsQuery = useResearchArtifactsQuery(run.mode === "topic" ? run.id : "")
  const papersQuery = useResearchRunPapersQuery(run.mode === "topic" ? run.id : "")
  const [expandedStepId, setExpandedStepId] = useState(() => steps.find((step) => ["running", "failed"].includes(step.status))?.id ?? "")
  const instanceId = useId().replace(/:/g, "")
  const titleRef = useRef<HTMLHeadingElement>(null)
  const activeStepId = steps.find((step) => ["running", "failed", "waiting_input"].includes(step.status))?.id ?? ""
  useEffect(() => { if (activeStepId) setExpandedStepId(activeStepId) }, [activeStepId])
  const artifacts = artifactsQuery.data ?? []
  const brief = artifacts.find((artifact) => artifact.artifact_type === "research_brief")
  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col bg-[var(--surface-raised)]", compact && "rounded-xl border")}>
      <header className="border-b p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Research Workflow</p><h2 ref={titleRef} tabIndex={-1} className="mt-1 break-words rounded text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring">{run.title}</h2></div>
          {onClose ? <Button size="icon" variant="ghost" className="size-11 shrink-0" aria-label="关闭 Workflow" onClick={onClose}><X className="size-4" /></Button> : null}
        </div>
        <div className="mt-3 flex items-center justify-between gap-3"><Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge><span className="text-xs tabular-nums text-muted-foreground">{completed}/{steps.length} 步</span></div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Research Workflow 进度" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={completed}><span className="block h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none" style={{ width: `${steps.length ? completed / steps.length * 100 : 0}%` }} /></div>
        <p className="sr-only" aria-live="polite">{researchStatusLabel[run.status]}，已完成 {completed} / {steps.length} 步</p>
        <BudgetSummary run={run} />
        <div className="mt-4"><RunControls run={run} /></div>
      </header>
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4">
        {run.mode === "harness" ? <div className="mb-4 rounded-lg border bg-muted/45 p-3 text-xs leading-5 text-muted-foreground"><strong className="text-foreground">当前为 Harness 骨架。</strong> 仅执行三步确定性流程，不代表论文调研已完成。</div> : <div className="mb-4" aria-busy={artifactsQuery.isLoading}>{artifactsQuery.isLoading ? <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">正在读取 ResearchBrief…</p> : artifactsQuery.isError ? <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-xs text-destructive">ResearchBrief 读取失败，未假定数据不存在。</p> : <BriefSummary artifact={brief} />}</div>}
        {decisions.length ? <div className="mb-4 grid gap-3">{decisions.map((decision, index) => <DecisionCard key={decision.id} runId={run.id} decision={decision} instanceId={instanceId} autoFocus={index === 0} returnFocusRef={titleRef} />)}</div> : null}
        {run.mode === "topic" ? (
          <Tabs defaultValue="steps" className="min-w-0">
            <TabsList className="grid h-auto min-h-11 w-full grid-cols-3"><TabsTrigger className="min-h-11" value="steps"><Search />步骤</TabsTrigger><TabsTrigger className="min-h-11" value="papers">论文</TabsTrigger><TabsTrigger className="min-h-11" value="briefs"><BookOpenText />阅读卡</TabsTrigger></TabsList>
            <TabsContent value="steps"><section aria-labelledby={`${instanceId}-steps`}><h3 id={`${instanceId}-steps`} className="my-3 text-sm font-semibold">真实执行步骤</h3><div className="grid gap-2">{steps.map((step) => <WorkflowStep key={step.id} step={step} instanceId={instanceId} expanded={expandedStepId === step.id} onToggle={() => setExpandedStepId((current) => current === step.id ? "" : step.id)} />)}</div></section></TabsContent>
            <TabsContent value="papers" className="pt-3" aria-busy={papersQuery.isLoading}>{papersQuery.isLoading ? <p className="text-xs text-muted-foreground">正在读取论文列表…</p> : papersQuery.isError ? <p role="alert" className="text-xs text-destructive">论文列表读取失败，未假定列表为空。</p> : <PaperList papers={papersQuery.data ?? []} />}</TabsContent>
            <TabsContent value="briefs" className="pt-3" aria-busy={artifactsQuery.isLoading}>{artifactsQuery.isLoading ? <p className="text-xs text-muted-foreground">正在读取 PaperBrief…</p> : artifactsQuery.isError ? <p role="alert" className="text-xs text-destructive">阅读卡读取失败，未假定数据不存在。</p> : <PaperBriefList artifacts={artifacts} instanceId={instanceId} />}</TabsContent>
          </Tabs>
        ) : <section aria-labelledby={`${instanceId}-steps`}><h3 id={`${instanceId}-steps`} className="mb-2 text-sm font-semibold">真实执行步骤</h3><div className="grid gap-2">{steps.map((step) => <WorkflowStep key={step.id} step={step} instanceId={instanceId} expanded={expandedStepId === step.id} onToggle={() => setExpandedStepId((current) => current === step.id ? "" : step.id)} />)}</div></section>}
        {run.error_message ? <div className="mt-4 break-words rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive [overflow-wrap:anywhere]" role="alert">任务失败：{run.error_message}</div> : null}
      </div>
    </div>
  )
}
