import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Archive, ArrowDown, ArrowLeft, ArrowUp, FileText, FolderArchive, Loader2, Pause, Play, RotateCcw, Save, Square, Trash2 } from "lucide-react"
import { Link, Navigate, useNavigate, useParams } from "react-router"
import { toast } from "sonner"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { Badge } from "@/components/ui/badge"
import { AlertDialog, AlertDialogActionButton, AlertDialogCancelButton, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  useControlResearchProjectAnalysisMutation, useDeleteResearchProjectMutation,
  useRemoveResearchProjectItemMutation, useReorderResearchProjectItemsMutation,
  useResearchProjectAnalysisQuery, useResearchProjectArtifactQuery,
  useResearchProjectArtifactVersionsQuery, useResearchProjectCoverageQuery,
  useResearchProjectItemsQuery, useResearchProjectQuery, useResolveResearchDecisionMutation,
  useSetResearchProjectArchivedMutation, useStartResearchProjectAnalysisMutation,
  useUpdateResearchProjectMutation,
} from "@/lib/query-hooks"
import type {
  ResearchGraph, ResearchProjectArtifactType, ResearchProjectCoverage, ResearchProjectItem,
  ResearchRun, ResearchTimeline, TopicClusters,
} from "@/types"
import { GraphView } from "./graph-view"
import { TimelineView } from "./timeline-view"
import { TopicClustersView } from "./topic-clusters"

type View = "scope" | "clusters" | "timeline" | "graph" | "versions"
const views: Array<{ value: View; label: string }> = [
  { value: "scope", label: "资料范围" }, { value: "clusters", label: "主题簇" },
  { value: "timeline", label: "时间线" }, { value: "graph", label: "关系图" },
  { value: "versions", label: "版本记录" },
]
const artifactForView: Partial<Record<View, ResearchProjectArtifactType>> = {
  clusters: "topic_clusters", timeline: "research_timeline", graph: "research_graph",
}

export function ResearchProjectPage() {
  const { projectId = "" } = useParams()
  const navigate = useNavigate()
  const projectQuery = useResearchProjectQuery(projectId)
  const itemsQuery = useResearchProjectItemsQuery(projectId)
  const coverageQuery = useResearchProjectCoverageQuery(projectId)
  const analysisQuery = useResearchProjectAnalysisQuery(projectId)
  const update = useUpdateResearchProjectMutation(projectId)
  const archived = useSetResearchProjectArchivedMutation(projectId)
  const removeProject = useDeleteResearchProjectMutation()
  const removeItem = useRemoveResearchProjectItemMutation(projectId)
  const reorder = useReorderResearchProjectItemsMutation(projectId)
  const startAnalysis = useStartResearchProjectAnalysisMutation(projectId)
  const controlAnalysis = useControlResearchProjectAnalysisMutation(projectId)
  const [view, setView] = useState<View>("scope")
  const [versions, setVersions] = useState<Partial<Record<ResearchProjectArtifactType, number>>>({})
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const project = projectQuery.data
  const type = artifactForView[view]
  const clusters = useResearchProjectArtifactQuery<TopicClusters>(projectId, "topic_clusters", versions.topic_clusters, view === "clusters")
  const timeline = useResearchProjectArtifactQuery<ResearchTimeline>(projectId, "research_timeline", versions.research_timeline, view === "timeline")
  const graph = useResearchProjectArtifactQuery<ResearchGraph>(projectId, "research_graph", versions.research_graph, view === "graph")
  const clusterVersions = useResearchProjectArtifactVersionsQuery(projectId, "topic_clusters")
  const timelineVersions = useResearchProjectArtifactVersionsQuery(projectId, "research_timeline")
  const graphVersions = useResearchProjectArtifactVersionsQuery(projectId, "research_graph")

  useEffect(() => { if (project) { setTitle(project.title); setDescription(project.description) } }, [project])
  if (!projectId) return <Navigate to="/library" replace />
  if (projectQuery.isLoading) return <LoadingState label="正在加载研究项目" skeleton />
  if (projectQuery.isError || !project) return <AppEmptyState title="无法打开研究项目" description="项目可能不存在、已无权访问，或网络暂时不可用。" action={<Button asChild variant="outline" className="min-h-11"><Link to="/library?view=projects">返回项目列表</Link></Button>} />
  const readOnly = project.status === "archived"
  const analysis = analysisQuery.data?.run ?? undefined

  const save = async (event: FormEvent) => {
    event.preventDefault()
    try { await update.mutateAsync({ title: title.trim(), description: description.trim() }); setEditing(false); toast.success("项目已更新。") } catch { toast.error("项目更新失败。") }
  }
  const setArchive = async (value: boolean) => {
    try { await archived.mutateAsync(value); toast.success(value ? "项目已归档，只读历史仍保留。" : "项目已恢复，可继续编辑。") } catch { toast.error("项目状态更新失败。") }
  }

  return <section className="grid min-w-0 gap-5">
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
      <div className="min-w-0"><Button asChild variant="ghost" className="min-h-11 px-2"><Link to="/library?view=projects"><ArrowLeft className="size-4" />返回研究项目</Link></Button><div className="mt-2 flex min-w-0 flex-wrap items-center gap-2"><h1 className="break-words text-2xl font-semibold [overflow-wrap:anywhere]">{project.title}</h1><Badge variant={readOnly ? "outline" : "secondary"}>{readOnly ? "已归档 · 只读" : "进行中"}</Badge></div>{project.description ? <p className="mt-2 max-w-3xl break-words text-sm leading-6 text-muted-foreground">{project.description}</p> : null}</div>
      <div className="flex flex-wrap gap-2">{readOnly ? <Button className="min-h-11" onClick={() => setArchive(false)} disabled={archived.isPending}><FolderArchive className="size-4" />恢复项目</Button> : <><Button variant="outline" className="min-h-11" aria-expanded={editing} aria-controls="project-edit-form" onClick={() => setEditing((value) => !value)}>编辑项目</Button><Button variant="outline" className="min-h-11" onClick={() => setArchive(true)} disabled={archived.isPending}><Archive className="size-4" />归档</Button></>}</div>
    </div>

    {editing && !readOnly ? <form id="project-edit-form" className="grid gap-3 rounded-xl border p-4" onSubmit={save}><div className="grid gap-2"><Label htmlFor="project-title">项目名称</Label><Input id="project-title" className="min-h-11" maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} /></div><div className="grid gap-2"><Label htmlFor="project-description">项目说明</Label><Textarea id="project-description" maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} /></div><div className="flex flex-wrap gap-2"><Button className="min-h-11" disabled={!title.trim() || update.isPending}><Save className="size-4" />保存</Button><Button type="button" variant="ghost" className="min-h-11" onClick={() => setEditing(false)}>取消</Button></div></form> : null}

    <ProjectCoverage coverage={coverageQuery.data} loading={coverageQuery.isLoading} error={coverageQuery.isError} />
    <AnalysisControls projectId={projectId} analysis={analysis} readOnly={readOnly} canAnalyze={(coverageQuery.data?.current_items ?? 0) > 0} pending={startAnalysis.isPending || controlAnalysis.isPending} onStart={() => startAnalysis.mutate(undefined, { onError: () => toast.error("无法启动项目分析。") })} onControl={(action) => controlAnalysis.mutate(action, { onError: () => toast.error("任务控制失败，未假定状态已经改变。") })} />

    <div className="sm:hidden"><Label htmlFor="project-view">项目内容</Label><Select value={view} onValueChange={(value) => setView(value as View)}><SelectTrigger id="project-view" className="mt-2 min-h-11 w-full"><SelectValue /></SelectTrigger><SelectContent>{views.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent></Select></div>
    <div className="hidden grid-cols-5 rounded-xl bg-muted p-1 sm:grid" role="tablist" aria-label="项目内容">{views.map((item) => <button key={item.value} id={`project-tab-${item.value}`} type="button" role="tab" aria-controls="project-tabpanel" aria-selected={view === item.value} tabIndex={view === item.value ? 0 : -1} className="min-h-11 rounded-lg px-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-background aria-selected:shadow-sm" onClick={() => setView(item.value)}>{item.label}</button>)}</div>

    {type ? <VersionPicker type={type} selected={versions[type]} versions={type === "topic_clusters" ? clusterVersions.data : type === "research_timeline" ? timelineVersions.data : graphVersions.data} onChange={(version) => setVersions((current) => ({ ...current, [type]: version }))} /> : null}
    <div id="project-tabpanel" role="tabpanel" aria-labelledby={`project-tab-${view}`}>{view === "scope" ? <ProjectItems items={itemsQuery.data ?? []} loading={itemsQuery.isLoading} readOnly={readOnly} onRemove={(id) => removeItem.mutate(id)} onReorder={(ids) => reorder.mutate(ids)} /> : null}
    {view === "clusters" ? <TopicClustersView projectId={projectId} artifact={clusters.data} /> : null}
    {view === "timeline" ? <TimelineView projectId={projectId} artifact={timeline.data} /> : null}
    {view === "graph" ? <GraphView projectId={projectId} artifact={graph.data} /> : null}
    {view === "versions" ? <VersionHistory groups={[{ label: "主题簇", items: clusterVersions.data }, { label: "时间线", items: timelineVersions.data }, { label: "关系图", items: graphVersions.data }]} /> : null}</div>

    {readOnly ? <div className="border-t pt-5"><AlertDialog><AlertDialogTrigger asChild><Button variant="destructive" className="min-h-11" disabled={removeProject.isPending}><Trash2 className="size-4" />删除项目记录</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>删除这个已归档项目？</AlertDialogTitle><AlertDialogDescription>项目成员和项目分析版本会被删除；原始 Run、论文、固定报告、引用和证据不会被删除。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancelButton className="min-h-11">取消</AlertDialogCancelButton><AlertDialogActionButton className="min-h-11" onClick={() => removeProject.mutate(projectId, { onSuccess: () => navigate("/library?view=projects"), onError: () => toast.error("项目删除失败。") })}>确认删除</AlertDialogActionButton></AlertDialogFooter></AlertDialogContent></AlertDialog><p className="mt-2 text-xs text-muted-foreground">删除项目不会删除原始 Run、论文、报告、引用或证据。</p></div> : null}
  </section>
}

function ProjectCoverage({ coverage, loading, error }: { coverage?: ResearchProjectCoverage; loading: boolean; error: boolean }) {
  if (loading) return <LoadingState label="正在校验项目资料" />
  if (error || !coverage) return <p role="alert" className="rounded-xl border border-destructive/40 p-4 text-sm text-destructive">资料有效性读取失败，未假定项目可以分析。</p>
  const stats = [["有效资料", coverage.current_items], ["论文", coverage.paper_count], ["报告", coverage.report_count], ["有效引用", coverage.valid_citation_count]] as const
  return <Card><CardContent className="p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-semibold">资料覆盖</h2><p className="mt-1 text-sm text-muted-foreground">{coverage.status === "ready" ? "资料足以生成当前脉络" : coverage.status === "limited" ? "仅能生成覆盖有限的研究脉络" : "资料不足，需要补充或清理"}</p></div><Badge variant="outline">过期 {coverage.stale_items} · 不可访问 {coverage.inaccessible_items}</Badge></div><dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">{stats.map(([label, value]) => <div key={label} className="rounded-lg bg-muted/50 p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-lg font-semibold tabular-nums">{value}</dd></div>)}</dl>{coverage.missing_inputs.length ? <p className="mt-3 break-words text-sm text-muted-foreground">仍需：{coverage.missing_inputs.join("；")}</p> : null}{coverage.warnings.length ? <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{coverage.warnings.map((item) => <li key={item} className="break-words">{item}</li>)}</ul> : null}</CardContent></Card>
}

function AnalysisControls({ projectId, analysis, readOnly, canAnalyze, pending, onStart, onControl }: { projectId: string; analysis?: ResearchRun; readOnly: boolean; canAnalyze: boolean; pending: boolean; onStart: () => void; onControl: (action: "pause" | "resume" | "cancel" | "retry") => void }) {
  const statusLabel = { queued: "等待开始", running: "分析中", waiting_input: "等待你的决定", paused: "已暂停", completed: "已完成", failed: "失败", cancelling: "正在停止", cancelled: "已停止" } as const
  const decisionMutation = useResolveResearchDecisionMutation(analysis?.id ?? "", projectId)
  const pendingDecision = analysis?.decisions?.find((decision) => decision.status === "pending")
  return <section className="rounded-xl border p-4" aria-label="项目分析控制">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">项目分析</h2><p className="mt-1 text-sm text-muted-foreground">{analysis ? `${statusLabel[analysis.status]} · ${analysis.steps?.length ?? 0} 个可审计步骤` : "尚未启动分析"}</p></div><div className="flex flex-wrap gap-2">
      {!analysis || ["completed", "failed", "cancelled"].includes(analysis.status) ? <Button className="min-h-11" disabled={readOnly || !canAnalyze || pending} onClick={onStart}>{pending ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <RotateCcw className="size-4" />}{analysis?.status === "failed" ? "创建新分析" : analysis ? "生成新版本" : "开始分析"}</Button> : null}
      {["queued", "running"].includes(analysis?.status ?? "") ? <Button variant="outline" className="min-h-11" disabled={pending} onClick={() => onControl("pause")}><Pause className="size-4" />暂停</Button> : null}
      {analysis?.status === "paused" ? <Button className="min-h-11" disabled={pending} onClick={() => onControl("resume")}><Play className="size-4" />继续</Button> : null}
      {analysis && !["completed", "failed", "cancelled"].includes(analysis.status) ? <AlertDialog><AlertDialogTrigger asChild><Button variant="outline" className="min-h-11" disabled={pending}><Square className="size-4" />停止</Button></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>停止项目分析？</AlertDialogTitle><AlertDialogDescription>尚未开始的步骤会停止，已完成的项目 Artifact 版本和审计记录会保留。</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancelButton className="min-h-11">继续分析</AlertDialogCancelButton><AlertDialogActionButton className="min-h-11" onClick={() => onControl("cancel")}>确认停止</AlertDialogActionButton></AlertDialogFooter></AlertDialogContent></AlertDialog> : null}
      {analysis?.status === "failed" ? <Button variant="outline" className="min-h-11" disabled={pending} onClick={() => onControl("retry")}><RotateCcw className="size-4" />重试当前步骤</Button> : null}
    </div></div>
    {analysis ? <><dl className="mt-4 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">{[["模型调用", `${analysis.usage.model_calls}/${analysis.budget.max_model_calls}`], ["工具调用", `${analysis.usage.tool_calls}/${analysis.budget.max_tool_calls}`], ["成功操作", analysis.usage.successful_calls], ["运行时间", `${Math.round(analysis.usage.wall_clock_seconds ?? 0)} 秒`]].map(([label, value]) => <div key={label} className="rounded-lg bg-muted/50 p-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 font-medium tabular-nums">{value}</dd></div>)}</dl><details className="mt-3 border-t pt-3"><summary className="flex min-h-11 cursor-pointer items-center text-sm font-medium">查看七步审计记录</summary><ol className="grid gap-2 pt-2 sm:grid-cols-2">{(analysis.steps ?? []).map((step, index) => <li key={step.id} className="min-w-0 rounded-lg bg-muted/45 p-3 text-sm"><span className="text-xs text-muted-foreground">{index + 1}. {statusLabel[step.status as keyof typeof statusLabel] ?? step.status}</span><span className="mt-1 block break-words font-medium [overflow-wrap:anywhere]">{step.title}</span></li>)}</ol></details></> : null}
    {pendingDecision ? <div className="mt-4 rounded-xl border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-4"><h3 className="font-semibold">需要你的决定</h3><p className="mt-1 text-sm">{pendingDecision.question}</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{pendingDecision.options.map((option) => <Button key={option.id} variant={option.id === pendingDecision.recommended_option ? "default" : "outline"} className="h-auto min-h-11 whitespace-normal py-2 text-left" disabled={decisionMutation.isPending} onClick={() => decisionMutation.mutate({ decisionId: pendingDecision.id, optionId: option.id })}>{option.label}{option.id === pendingDecision.recommended_option ? " · 推荐" : ""}</Button>)}</div></div> : null}
    <span className="sr-only" aria-live="polite">{analysis ? `项目分析${statusLabel[analysis.status]}` : "项目分析尚未开始"}</span><span className="sr-only">{projectId}</span>
  </section>
}

function ProjectItems({ items, loading, readOnly, onRemove, onReorder }: { items: ResearchProjectItem[]; loading: boolean; readOnly: boolean; onRemove: (id: string) => void; onReorder: (ids: string[]) => void }) {
  if (loading) return <LoadingState label="正在读取项目资料" />
  const move = (index: number, offset: number) => { const next = [...items]; const target = index + offset; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; onReorder(next.map((item) => item.id)) }
  const href = (item: ResearchProjectItem) => item.item_type === "run" && item.run_id ? `/runs/${item.run_id}` : item.item_type === "paper" && item.paper_id ? `/papers/${item.paper_id}` : item.item_type === "research_report" && item.source_run_id && item.artifact_version ? `/runs/${item.source_run_id}/reports/${item.artifact_version}` : null
  return <section aria-labelledby="project-items-heading"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h2 id="project-items-heading" className="text-lg font-semibold">项目资料范围</h2><p className="mt-1 text-sm text-muted-foreground">读取时会重新校验权限；移除项目项不会删除原始资料。</p></div>{!readOnly ? <Button asChild variant="outline" className="min-h-11"><Link to="/papers"><FileText className="size-4" />添加更多论文</Link></Button> : null}</div>
    {items.length ? <div className="grid gap-2">{items.map((item, index) => <article key={item.id} className="flex min-w-0 flex-wrap items-center gap-3 rounded-xl border p-3"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{item.item_type === "run" ? "调研任务" : item.item_type === "paper" ? "论文" : `报告 v${item.artifact_version}`}</Badge><span className="text-xs text-muted-foreground">{item.dependency_status === "current" ? "当前有效" : item.dependency_status === "stale" ? "内容已更新" : "不可访问"}</span></div>{item.dependency_status === "inaccessible" ? <p className="mt-2 text-sm text-muted-foreground">当前权限下只保留安全占位，不显示标题或摘要。</p> : <>{href(item) ? <Link to={href(item)!} className="mt-2 block break-words font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [overflow-wrap:anywhere]">{item.title || "未命名资料"}</Link> : <h3 className="mt-2 break-words font-medium [overflow-wrap:anywhere]">{item.title || "未命名资料"}</h3>}{item.subtitle ? <p className="mt-1 break-words text-sm text-muted-foreground">{item.subtitle}</p> : null}</>}</div>{!readOnly ? <div className="flex gap-1"><Button size="icon" variant="ghost" className="size-11" aria-label="上移" disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp className="size-4" /></Button><Button size="icon" variant="ghost" className="size-11" aria-label="下移" disabled={index === items.length - 1} onClick={() => move(index, 1)}><ArrowDown className="size-4" /></Button><Button size="icon" variant="ghost" className="size-11" aria-label="移出项目" onClick={() => onRemove(item.id)}><Trash2 className="size-4" /></Button></div> : null}</article>)}</div> : <AppEmptyState title="项目还没有资料" description="从调研任务、论文或固定报告版本加入资料。" />}
  </section>
}

function VersionPicker({ type, selected, versions, onChange }: { type: ResearchProjectArtifactType; selected?: number; versions?: Array<{ id: string; version: number; is_current: boolean; status: string }>; onChange: (version?: number) => void }) {
  if (!versions?.length) return null
  const current = versions.find((item) => item.is_current)?.version ?? versions[0].version
  return <div className="flex flex-wrap items-center justify-end gap-2"><Label htmlFor={`version-${type}`}>分析版本</Label><Select value={String(selected ?? current)} onValueChange={(value) => onChange(Number(value))}><SelectTrigger id={`version-${type}`} className="min-h-11 w-44"><SelectValue /></SelectTrigger><SelectContent>{versions.map((item) => <SelectItem key={item.id} value={String(item.version)}>v{item.version} · {item.is_current ? "当前" : item.status === "stale" ? "已失效" : "历史"}</SelectItem>)}</SelectContent></Select></div>
}

function VersionHistory({ groups }: { groups: Array<{ label: string; items?: Array<{ id: string; version: number; status: string; is_current: boolean; created_at: string }> }> }) {
  return <section aria-labelledby="project-versions-heading"><h2 id="project-versions-heading" className="text-lg font-semibold">版本记录</h2><p className="mt-1 text-sm text-muted-foreground">历史版本仅用于安全审计；失效事实不会伪装成当前结论。</p><div className="mt-4 grid gap-4 md:grid-cols-2">{groups.map((group) => <section key={group.label} className="rounded-xl border p-4"><h3 className="font-semibold">{group.label}</h3><div className="mt-2 grid gap-2">{group.items?.length ? group.items.map((item) => <div key={item.id} className="flex min-h-11 items-center justify-between gap-2 rounded-lg bg-muted/50 px-3 text-sm"><span>v{item.version} · {item.created_at}</span><Badge variant="outline">{item.is_current ? "当前" : item.status === "stale" ? "已失效" : "历史"}</Badge></div>) : <p className="text-sm text-muted-foreground">暂无版本</p>}</div></section>)}</div></section>
}
