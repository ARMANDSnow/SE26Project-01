import { useEffect, useId, useRef, useState } from "react"
import { Link } from "react-router"
import {
  AlertCircle, BookOpenText, Check, ChevronDown, Circle, ExternalLink, FileText, Loader2,
  Pause, Play, Quote, RotateCcw, Search, ShieldAlert, Square, X,
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
  useResolveResearchDecisionMutation, useResearchCitationsQuery, useResearchCitationEvidenceQuery,
  useResearchReportsQuery, useRegenerateResearchReportMutation,
} from "@/lib/query-hooks"
import type {
  ComparisonMatrix, PaperBrief, ResearchArtifact, ResearchBrief, ResearchCitation,
  ResearchDecision, ResearchReport, ResearchRun, SynthesisClaims, SynthesisPlan,
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

const topicStages = [
  { id: "define", label: "定义研究", keys: ["brief", "query_planning"] },
  { id: "collect", label: "搜集论文", keys: ["local_search", "arxiv_search", "dedup_import"] },
  { id: "screen", label: "筛选资料", keys: ["screening"] },
  { id: "fulltext", label: "获取全文", keys: ["fulltext_acquisition"] },
  { id: "read", label: "阅读与提取", keys: ["reading", "extraction", "finalize_dataset"] },
  { id: "synthesize", label: "比较与综合", keys: ["synthesis_planning", "comparison_matrix", "cross_paper_claims"] },
  { id: "verify", label: "核验与成稿", keys: ["citation_registry", "citation_verification", "report_generation", "finalize_cited_report"] },
] as const

const stageStatusPriority: ResearchStepStatus[] = ["failed", "waiting_input", "running", "paused", "cancelled", "queued", "completed", "skipped"]

function aggregateStageStatus(steps: ResearchStep[]): ResearchStepStatus {
  if (steps.length && steps.every((step) => ["completed", "skipped"].includes(step.status))) return "completed"
  return stageStatusPriority.find((status) => steps.some((step) => step.status === status)) ?? "queued"
}

function TopicStage({ id, label, steps, expanded, onToggle, expandedStepId, onToggleStep, instanceId }: {
  id: string; label: string; steps: ResearchStep[]; expanded: boolean; onToggle: () => void;
  expandedStepId: string; onToggleStep: (id: string) => void; instanceId: string
}) {
  const status = aggregateStageStatus(steps)
  const Icon = stepIcon[status] ?? Circle
  const detailId = `${instanceId}-stage-${id}`
  const done = steps.filter((step) => ["completed", "skipped"].includes(step.status)).length
  return <section className="min-w-0 border-b py-1 last:border-b-0">
    <button type="button" aria-expanded={expanded} aria-controls={detailId} onClick={onToggle} className="flex min-h-14 w-full items-center gap-3 rounded-lg px-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-muted" aria-hidden="true"><Icon className={cn("size-4", status === "running" && "animate-spin motion-reduce:animate-none")} /></span>
      <span className="min-w-0 flex-1"><span className="block text-sm font-medium">{label}</span><span className="text-xs text-muted-foreground">{researchStepStatusLabel[status]} · {done}/{steps.length} 项执行记录</span></span>
      <ChevronDown className={cn("size-4 transition-transform motion-reduce:transition-none", expanded && "rotate-180")} />
    </button>
    {expanded ? <div id={detailId} className="grid gap-2 pb-3 pl-2 pt-1 md:pl-11">{steps.map((step) => <WorkflowStep key={step.id} step={step} instanceId={instanceId} expanded={expandedStepId === step.id} onToggle={() => onToggleStep(step.id)} />)}</div> : null}
  </section>
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
          <span className="mt-0.5 block text-xs text-muted-foreground">{researchStepStatusLabel[step.status]} · 第 {step.attempt_count} 次尝试，共 {step.max_attempts} 次</span>
        </span>
        <ChevronDown className={cn("size-4 shrink-0 transition-transform motion-reduce:transition-none", expanded && "rotate-180")} />
      </button>
      {expanded ? (
        <div id={detailId} className="min-w-0 border-t px-4 py-3 text-xs leading-5 text-muted-foreground">
          <p className="font-medium text-foreground">技术详情</p><p className="mt-1">执行者：{step.agent_name}</p>
          {step.output.scaffold_only ? <p className="mt-1">Harness 骨架输出；未执行论文检索、导入或模型研究。</p> : null}
          {tools.length ? (
            <section className="mt-3" aria-label="工具执行摘要">
              <p className="font-medium text-foreground">工具执行</p>
              <div className="mt-1 grid gap-2">
                {tools.map((tool, index) => (
                  <div key={`${tool.tool}-${index}`} className="min-w-0 rounded-lg bg-muted/55 p-2">
                    <div className="flex flex-wrap items-center gap-2"><code className="break-all font-mono text-foreground">{tool.tool}</code><Badge variant="outline">{tool.status}</Badge><span>第 {tool.attempt} 次尝试</span></div>
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
  const [showAll, setShowAll] = useState(false)
  const stageSets: Partial<Record<ResearchRunPaper["stage"], ResearchRunPaper["stage"][]>> = {
    selected: ["selected", "fulltext_ready", "read", "extracted"],
    fulltext_ready: ["fulltext_ready", "read", "extracted"],
    read: ["read", "extracted"],
  }
  const visible = papers.filter((paper) => filter === "all" || (stageSets[filter] ?? [filter]).includes(paper.stage))
  const displayed = showAll ? visible : visible.slice(0, 8)
  return (
    <section aria-label="调研论文列表">
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1">
        {(["all", "candidate", "selected", "excluded", "fulltext_ready", "read", "extracted"] as const).map((value) => <Button key={value} size="sm" variant={filter === value ? "default" : "outline"} aria-pressed={filter === value} className="min-h-11 shrink-0" onClick={() => { setFilter(value); setShowAll(false) }}>{value === "all" ? `全部 ${papers.length}` : stageLabel[value]}</Button>)}
      </div>
      <div className="grid gap-2">
        {displayed.map((paper) => (
          <article key={paper.paper_id} className="min-w-0 rounded-xl border bg-card p-3">
            <div className="flex min-w-0 items-start gap-2"><span className="shrink-0 font-mono text-xs text-muted-foreground">{paper.rank ? `#${paper.rank}` : "—"}</span><div className="min-w-0 flex-1"><h3 className="break-words text-sm font-medium [overflow-wrap:anywhere]">{paper.title}</h3><p className="mt-1 break-all text-xs text-muted-foreground">{paper.source}:{paper.source_id} · {paper.published_at.slice(0, 4)}</p></div><Badge variant="outline">{stageLabel[paper.stage]}</Badge></div>
            {paper.score != null ? <p className="mt-2 text-xs">评分：<span className="font-mono">{paper.score}</span></p> : null}
            {paper.inclusion_reason || paper.exclusion_reason ? <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">{paper.inclusion_reason ?? paper.exclusion_reason}</p> : null}
            <Button asChild variant="link" className="mt-1 min-h-11 h-auto px-0"><Link to={`/papers/${paper.paper_id}`}>打开论文<ExternalLink className="size-3.5" /></Link></Button>
          </article>
        ))}
        {!visible.length ? <p className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">当前筛选没有数据库记录。</p> : null}
      </div>
      {visible.length > 8 ? <Button type="button" variant="outline" className="mt-3 min-h-11" aria-expanded={showAll} onClick={() => setShowAll((value) => !value)}>{showAll ? "收起论文列表" : `再显示 ${visible.length - displayed.length} 篇论文`}</Button> : null}
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
    return <article key={artifact.id} className="min-w-0 rounded-xl border bg-card"><button type="button" className="flex min-h-14 w-full items-center gap-3 p-3 text-left" aria-expanded={open} aria-controls={detailId} onClick={() => setExpanded(open ? "" : artifact.id)}><BookOpenText className="size-4 shrink-0 text-primary" /><span className="min-w-0 flex-1"><span className="block break-words text-sm font-medium">{brief.title}</span><span className="mt-1 block text-xs text-muted-foreground">{brief.year} · v{artifact.version} · {artifact.is_current ? "内容版本有效" : "原文已更新"}</span></span><ChevronDown className={cn("size-4 shrink-0", open && "rotate-180")} /></button>{open ? <div id={detailId} className="grid gap-3 border-t p-3 text-xs leading-5"><div><strong>研究问题</strong><p className="break-words text-muted-foreground">{brief.research_question}</p></div><div><strong>方法</strong><p className="break-words text-muted-foreground">{brief.method}</p></div><div><strong>数据集与实验</strong><p className="break-words text-muted-foreground">{brief.dataset || "未报告"}；{brief.experiments || "未报告"}</p></div><div><strong>主要发现</strong><ul className="list-disc pl-5 text-muted-foreground">{brief.key_findings.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div><div><strong>局限</strong><ul className="list-disc pl-5 text-muted-foreground">{brief.limitations.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div><div><strong>原文证据</strong><p className="break-words text-muted-foreground">{brief.evidence_ids.map((item) => `片段 ${item.chunk_id}`).join(" · ")}</p></div></div> : null}</article>
  })}{!briefs.length ? <p className="rounded-lg border border-dashed p-4 text-xs text-muted-foreground">论文阅读卡尚未生成。</p> : null}</div>
}

const citationStatusLabel: Record<ResearchCitation["status"], string> = {
  valid: "有效", stale: "已过期", inaccessible: "不可访问", invalid: "无效",
}

function CitationDisclosure({ runId, citation, instanceId }: { runId: string; citation: ResearchCitation; instanceId: string }) {
  const [open, setOpen] = useState(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const detailId = `${instanceId}-citation-${citation.id}`
  const evidence = useResearchCitationEvidenceQuery(runId, citation.id, open && citation.status !== "inaccessible")
  // A closed disclosure must follow the latest Registry projection. React Query may
  // still hold a previously valid Evidence response after report regeneration, so
  // only expose it once the currently open disclosure has finished revalidation.
  const current = citation.status !== "inaccessible"
    && open && evidence.isSuccess && !evidence.isFetching && evidence.data
    ? evidence.data
    : citation
  const ordinal = citation.citation_key.match(/\d+/)?.[0] ?? citation.citation_key
  const accessibleName = `引用 ${ordinal}，${citationStatusLabel[current.status]}`
  return <article className="min-w-0 rounded-lg border bg-card">
    <button ref={buttonRef} type="button" className="flex min-h-11 w-full min-w-0 items-center gap-2 px-3 py-2 text-left" aria-label={accessibleName} aria-expanded={open} aria-controls={detailId} onClick={() => setOpen((value) => !value)}>
      <Quote className="size-4 shrink-0 text-primary" /><span className="min-w-0 flex-1 break-words text-xs font-semibold">引用 {ordinal}</span><Badge variant="outline"><span>{citationStatusLabel[current.status]}</span></Badge><ChevronDown className={cn("size-4 shrink-0", open && "rotate-180")} />
    </button>
    {open ? <div id={detailId} className="min-w-0 border-t p-3 text-xs leading-5">
      {evidence.isLoading ? <p className="text-muted-foreground">正在重新校验证据…</p> : evidence.isError ? <p role="alert" className="text-destructive">证据读取失败；未使用缓存内容。</p> : <>
        <p className="break-words [overflow-wrap:anywhere]" role="status" aria-live="polite">状态：{citationStatusLabel[current.status]}</p>
        {current.paper_id ? <p className="break-words text-muted-foreground">论文 {current.paper_id} · {current.heading || "未命名章节"} · {current.char_start}–{current.char_end}</p> : <p className="text-muted-foreground">当前权限下仅保留安全状态。</p>}
        {current.excerpt ? <blockquote className="mt-2 break-words rounded-md bg-muted/55 p-2 [overflow-wrap:anywhere]">{current.excerpt}</blockquote> : <p className="mt-2 text-muted-foreground">该状态不返回证据原文。</p>}
        {current.status === "valid" ? <p className="mt-1 text-muted-foreground">技术详情：内部标识 {citation.citation_key}</p> : null}
        {current.status === "valid" && current.paper_id ? <Button asChild variant="link" className="h-auto min-h-11 px-0"><Link to={`/papers/${current.paper_id}?chunk=${current.chunk_id ?? ""}&start=${current.char_start ?? ""}&end=${current.char_end ?? ""}`}>在论文中定位原文证据<ExternalLink className="size-3.5" /></Link></Button> : null}
      </>}
      <Button variant="ghost" className="mt-1 min-h-11" onClick={() => { setOpen(false); requestAnimationFrame(() => buttonRef.current?.focus()) }}>关闭引用</Button>
    </div> : null}
  </article>
}

function isSynthesisPlan(content: Record<string, unknown>): content is SynthesisPlan {
  return typeof content.topic === "string" && Array.isArray(content.comparison_dimensions) && typeof content.synthesis_strategy === "string"
}
function isComparisonMatrix(content: Record<string, unknown>): content is ComparisonMatrix {
  return Array.isArray(content.dimensions) && Array.isArray(content.papers) && Array.isArray(content.cells)
}
function isSynthesisClaims(content: Record<string, unknown>): content is SynthesisClaims {
  return Array.isArray(content.claims)
}
function isResearchReport(content: Record<string, unknown>): content is ResearchReport {
  return typeof content.title === "string" && Array.isArray(content.findings) && Array.isArray(content.conclusion) && Array.isArray(content.citation_keys)
}

function CitationListForKeys({ keys, citations, runId, instanceId }: { keys: string[]; citations: ResearchCitation[] | null; runId: string; instanceId: string }) {
  if (citations === null) return <p className="text-xs text-muted-foreground" aria-live="polite">正在读取引用清单…</p>
  return <div className="grid gap-2">{keys.map((key) => { const citation = citations.find((entry) => entry.citation_key === key); return citation ? <CitationDisclosure key={`${instanceId}-${citation.id}-${key}`} runId={runId} citation={citation} instanceId={instanceId} /> : <p key={key} className="break-all text-xs text-destructive">{key} 未出现在当前 Registry</p> })}</div>
}

function CitedStatements({ title, items, citations, runId, instanceId }: { title: string; items: ResearchReport["findings"]; citations: ResearchCitation[] | null; runId: string; instanceId: string }) {
  return <section className="min-w-0"><h4 className="text-sm font-semibold">{title}</h4><div className="mt-2 grid gap-3">{items.map((item) => <article key={item.statement_id} className="min-w-0 rounded-lg bg-muted/45 p-3"><p className="break-words text-xs leading-5 [overflow-wrap:anywhere]">{item.text}</p><div className="mt-2"><CitationListForKeys keys={item.citation_keys} citations={citations} runId={runId} instanceId={`${instanceId}-${item.statement_id}`} /></div></article>)}</div></section>
}

function SynthesisReport({ run, artifacts, instanceId }: { run: ResearchRun; artifacts: ResearchArtifact[]; instanceId: string }) {
  const citationsQuery = useResearchCitationsQuery(run.id)
  const reportsQuery = useResearchReportsQuery(run.id)
  const regeneration = useRegenerateResearchReportMutation(run.id)
  const reports = reportsQuery.data ?? []
  const preferred = reports.find((item) => item.is_current) ?? reports[0]
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [followCurrent, setFollowCurrent] = useState(true)
  useEffect(() => { if (preferred && (selectedVersion == null || followCurrent)) setSelectedVersion(preferred.version) }, [followCurrent, preferred, selectedVersion])
  const reportArtifact = reports.find((item) => item.version === selectedVersion) ?? preferred
  const report = reportArtifact && isResearchReport(reportArtifact.content) ? reportArtifact.content : null
  const sourceVersions = report?.generated_from_artifact_versions
  const planArtifact = artifacts.find((item) => item.artifact_type === "synthesis_plan" && (sourceVersions ? item.version === sourceVersions.synthesis_plan : item.is_current))
  const matrixArtifact = artifacts.find((item) => item.artifact_type === "comparison_matrix" && (sourceVersions ? item.version === sourceVersions.comparison_matrix : item.is_current))
  const claimsArtifact = artifacts.find((item) => item.artifact_type === "synthesis_claims" && (sourceVersions ? item.version === sourceVersions.synthesis_claims : item.is_current))
  const plan = planArtifact && isSynthesisPlan(planArtifact.content) ? planArtifact.content : null
  const matrix = matrixArtifact && isComparisonMatrix(matrixArtifact.content) ? matrixArtifact.content : null
  const claims = claimsArtifact && isSynthesisClaims(claimsArtifact.content) ? claimsArtifact.content : null
  const allCitations = citationsQuery.isLoading || citationsQuery.isError ? null : (citationsQuery.data ?? [])
  const currentRegistryVersion = artifacts.find((item) => item.artifact_type === "citation_registry" && item.is_current)?.version
  const reportRegistryVersion = report?.generated_from_artifact_versions.citation_registry
  const synthesisCitations = allCitations?.filter((item) => currentRegistryVersion == null || item.artifact_version === currentRegistryVersion) ?? null
  const reportCitations = allCitations?.filter((item) => reportRegistryVersion == null || item.artifact_version === reportRegistryVersion) ?? null
  const citations = report ? reportCitations : synthesisCitations
  const counts = (citations ?? []).reduce<Record<string, number>>((result, item) => ({ ...result, [item.status]: (result[item.status] ?? 0) + 1 }), {})
  const reportSections = ["执行摘要", "研究问题", "主要发现", "共识", "分歧", "局限与空白", "结论"]
  return <section className="min-w-0 space-y-4" aria-label="可追溯调研综合与报告" aria-busy={reportsQuery.isLoading || citationsQuery.isLoading}>
    <p className="sr-only" aria-live="polite">引用验证状态：{counts.valid ?? 0} 条有效，{counts.stale ?? 0} 条过期，{counts.inaccessible ?? 0} 条不可访问，{counts.invalid ?? 0} 条无效。</p>
    <article className="min-w-0 border-y py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0"><h3 className="break-words text-sm font-semibold">{report?.title ?? "版本化研究报告"}</h3><p className="mt-1 text-xs text-muted-foreground">引用有效 {counts.valid ?? 0} · 内容已更新 {counts.stale ?? 0} · 不可访问 {counts.inaccessible ?? 0}</p></div>
        {reports.length ? <label className="text-xs">版本 <select className="ml-1 min-h-11 rounded-xl border bg-background px-2" value={reportArtifact?.version ?? ""} onChange={(event) => { const version = Number(event.target.value); setSelectedVersion(version); setFollowCurrent(reports.find((item) => item.version === version)?.is_current === true) }}>{reports.map((item) => <option key={item.id} value={item.version}>v{item.version}{item.is_current ? " · 当前版本" : " · 历史版本"}</option>)}</select></label> : null}
      </div>
      {reportArtifact && !reportArtifact.is_current ? <p role="status" className="mt-3 rounded-lg border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-3 text-xs">这是历史版本。受影响的事实文本不会作为当前结论展示。</p> : null}
      {report && reportArtifact?.is_current ? <div className="mt-4"><h4 className="text-xs font-semibold">执行摘要</h4><ul className="mt-2 space-y-2">{report.executive_summary.slice(0, 3).map((item, index) => <li key={item.statement_id} className="break-words border-l-2 pl-3 text-xs leading-5 [overflow-wrap:anywhere]">{item.text}<span className="ml-1 text-muted-foreground">[引用 {index + 1}]</span></li>)}</ul></div> : reportsQuery.isLoading ? <p className="mt-3 text-xs text-muted-foreground">正在读取报告版本…</p> : <p className="mt-3 text-xs text-muted-foreground">报告尚未通过严格引用校验。</p>}
      <div className="mt-4 flex flex-wrap gap-2">{reportArtifact ? <Button asChild variant="outline" className="min-h-11"><Link to={`/runs/${run.id}/reports/${reportArtifact.version}`}><ExternalLink className="size-4" />打开完整报告</Link></Button> : null}{(reportArtifact || claimsArtifact) && ["completed", "failed"].includes(run.status) ? <Button className="min-h-11" variant="outline" disabled={regeneration.isPending} onClick={() => { setFollowCurrent(true); regeneration.mutate() }}><RotateCcw className="size-4" />生成新版本</Button> : null}</div>
      {regeneration.isPending ? <p className="mt-2 text-xs text-muted-foreground" role="status" aria-live="polite">已请求生成新版本；完成后将自动切换到当前版本。</p> : null}{regeneration.isError ? <p role="alert" className="mt-2 text-xs text-destructive">重新生成请求失败，旧版本保持不变。</p> : null}
    </article>
  </section>
}

export function WorkflowPanel({ run, onClose, compact = false }: { run: ResearchRun; onClose?: () => void; compact?: boolean }) {
  const steps = run.steps ?? []
  const groupedStages = run.mode === "topic" ? topicStages.map((stage) => ({ ...stage, steps: steps.filter((step) => (stage.keys as readonly string[]).includes(step.step_key)) })) : []
  const progressItems = run.mode === "topic" ? groupedStages : steps
  const completed = run.mode === "topic" ? groupedStages.filter((stage) => aggregateStageStatus(stage.steps) === "completed").length : steps.filter((step) => step.status === "completed").length
  const progressTotal = progressItems.length
  const decisions = (run.decisions ?? []).filter((decision) => decision.status === "pending")
  const artifactsQuery = useResearchArtifactsQuery(run.mode === "topic" ? run.id : "")
  const papersQuery = useResearchRunPapersQuery(run.mode === "topic" ? run.id : "")
  const [expandedStepId, setExpandedStepId] = useState(() => steps.find((step) => ["running", "failed"].includes(step.status))?.id ?? "")
  const [expandedStageId, setExpandedStageId] = useState<string>(() => groupedStages.find((stage) => stage.steps.some((step) => ["running", "failed", "waiting_input"].includes(step.status)))?.id ?? groupedStages[0]?.id ?? "")
  const instanceId = useId().replace(/:/g, "")
  const titleRef = useRef<HTMLHeadingElement>(null)
  const activeStepId = steps.find((step) => ["running", "failed", "waiting_input"].includes(step.status))?.id ?? ""
  useEffect(() => {
    if (!activeStepId) return
    setExpandedStepId(activeStepId)
    const activeStage = groupedStages.find((stage) => stage.steps.some((step) => step.id === activeStepId))
    if (activeStage) setExpandedStageId(activeStage.id)
  }, [activeStepId])
  const artifacts = artifactsQuery.data ?? []
  const brief = artifacts.find((artifact) => artifact.artifact_type === "research_brief")
  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col bg-[var(--surface-raised)]", compact && "rounded-xl border")}>
      <header className="border-b p-4">
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">Research Workflow</p><h2 ref={titleRef} tabIndex={-1} className="mt-1 break-words rounded text-base font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring">{run.title}</h2></div>
          {onClose ? <Button size="icon" variant="ghost" className="size-11 shrink-0" aria-label="关闭 Workflow" onClick={onClose}><X className="size-4" /></Button> : null}
        </div>
        <div className="mt-3 flex items-center justify-between gap-3"><Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge><span className="text-xs tabular-nums text-muted-foreground">{completed}/{progressTotal} {run.mode === "topic" ? "阶段" : "步"}</span></div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label="Research Workflow 进度" aria-valuemin={0} aria-valuemax={progressTotal} aria-valuenow={completed}><span className="block h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none" style={{ width: `${progressTotal ? completed / progressTotal * 100 : 0}%` }} /></div>
        <p className="sr-only" aria-live="polite">{researchStatusLabel[run.status]}，已完成 {completed} / {progressTotal} {run.mode === "topic" ? "阶段" : "步"}</p>
        <BudgetSummary run={run} />
        <div className="mt-4"><RunControls run={run} /></div>
      </header>
      <div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4">
        {run.mode === "harness" ? <div className="mb-4 rounded-lg border bg-muted/45 p-3 text-xs leading-5 text-muted-foreground"><strong className="text-foreground">当前为 Harness 骨架。</strong> 仅执行三步确定性流程，不代表论文调研已完成。</div> : <div className="mb-4" aria-busy={artifactsQuery.isLoading}>{artifactsQuery.isLoading ? <p className="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">正在读取 ResearchBrief…</p> : artifactsQuery.isError ? <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-xs text-destructive">ResearchBrief 读取失败，未假定数据不存在。</p> : <BriefSummary artifact={brief} />}</div>}
        {decisions.length ? <div className="mb-4 grid gap-3">{decisions.map((decision, index) => <DecisionCard key={decision.id} runId={run.id} decision={decision} instanceId={instanceId} autoFocus={index === 0} returnFocusRef={titleRef} />)}</div> : null}
        {run.mode === "topic" ? (
            <Tabs defaultValue="steps" className="min-w-0">
            <TabsList className="grid h-auto min-h-11 w-full grid-cols-3"><TabsTrigger className="min-h-11" value="steps"><Search />过程</TabsTrigger><TabsTrigger className="min-h-11" value="dataset"><BookOpenText />数据集</TabsTrigger><TabsTrigger className="min-h-11" value="synthesis"><FileText />综合报告</TabsTrigger></TabsList>
            <TabsContent value="steps"><section aria-labelledby={`${instanceId}-steps`}><div className="my-3"><h3 id={`${instanceId}-steps`} className="text-sm font-semibold">七个研究阶段</h3><p className="mt-1 text-xs text-muted-foreground">展开阶段可审计全部 17 条后端执行记录。</p></div><div>{groupedStages.map((stage) => <TopicStage key={stage.id} id={stage.id} label={stage.label} steps={stage.steps} instanceId={instanceId} expanded={expandedStageId === stage.id} onToggle={() => setExpandedStageId((current) => current === stage.id ? "" : stage.id)} expandedStepId={expandedStepId} onToggleStep={(id) => setExpandedStepId((current) => current === id ? "" : id)} />)}</div></section></TabsContent>
            <TabsContent value="dataset" className="pt-3"><Tabs defaultValue="papers"><TabsList className="grid h-auto min-h-11 w-full grid-cols-2"><TabsTrigger className="min-h-11" value="papers">论文</TabsTrigger><TabsTrigger className="min-h-11" value="briefs">阅读卡</TabsTrigger></TabsList><TabsContent value="papers" className="pt-3" aria-busy={papersQuery.isLoading}>{papersQuery.isLoading ? <p className="text-xs text-muted-foreground">正在读取论文列表…</p> : papersQuery.isError ? <p role="alert" className="text-xs text-destructive">论文列表读取失败，未假定列表为空。</p> : <PaperList papers={papersQuery.data ?? []} />}</TabsContent><TabsContent value="briefs" className="pt-3" aria-busy={artifactsQuery.isLoading}>{artifactsQuery.isLoading ? <p className="text-xs text-muted-foreground">正在读取 PaperBrief…</p> : artifactsQuery.isError ? <p role="alert" className="text-xs text-destructive">阅读卡读取失败，未假定数据不存在。</p> : <PaperBriefList artifacts={artifacts} instanceId={instanceId} />}</TabsContent></Tabs></TabsContent>
            <TabsContent value="synthesis" className="pt-3"><SynthesisReport run={run} artifacts={artifacts} instanceId={instanceId} /></TabsContent>
          </Tabs>
        ) : <section aria-labelledby={`${instanceId}-steps`}><h3 id={`${instanceId}-steps`} className="mb-2 text-sm font-semibold">真实执行步骤</h3><div className="grid gap-2">{steps.map((step) => <WorkflowStep key={step.id} step={step} instanceId={instanceId} expanded={expandedStepId === step.id} onToggle={() => setExpandedStepId((current) => current === step.id ? "" : step.id)} />)}</div></section>}
        {run.error_message ? <div className="mt-4 break-words rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive [overflow-wrap:anywhere]" role="alert">任务失败：{run.error_message}</div> : null}
      </div>
    </div>
  )
}
