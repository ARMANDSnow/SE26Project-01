import { useMemo, useRef, useState } from "react"
import { ArrowLeft, ExternalLink, Loader2, Quote } from "lucide-react"
import { Link, Navigate, useParams } from "react-router"
import { AddToProjectDialog } from "@/components/research/add-to-project-dialog"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import {
  useResearchArtifactsQuery, useResearchCitationEvidenceQuery, useResearchCitationsQuery,
  useResearchReportsQuery, useResearchRunQuery,
} from "@/lib/query-hooks"
import type { ComparisonMatrix, ResearchCitation, ResearchReport, SynthesisClaims } from "@/types"

type View = "report" | "comparison" | "claims" | "citations"
const views: Array<{ value: View; label: string }> = [
  { value: "report", label: "报告" }, { value: "comparison", label: "对比" },
  { value: "claims", label: "主张" }, { value: "citations", label: "引用" },
]

function isReport(value: Record<string, unknown>): value is ResearchReport { return typeof value.title === "string" && Array.isArray(value.findings) && Array.isArray(value.citation_keys) }
function isMatrix(value: Record<string, unknown>): value is ComparisonMatrix { return Array.isArray(value.dimensions) && Array.isArray(value.cells) && Array.isArray(value.papers) }
function isClaims(value: Record<string, unknown>): value is SynthesisClaims { return Array.isArray(value.claims) }

export function ResearchReportPage() {
  const { runId = "", version = "" } = useParams()
  const reportVersion = Number(version)
  const run = useResearchRunQuery(runId)
  const reports = useResearchReportsQuery(runId)
  const artifacts = useResearchArtifactsQuery(runId)
  const citations = useResearchCitationsQuery(runId)
  const [view, setView] = useState<View>("report")
  const [section, setSection] = useState("summary")
  if (!runId || !Number.isInteger(reportVersion) || reportVersion < 1) return <Navigate to="/library?view=reports" replace />
  if (run.isLoading || reports.isLoading || artifacts.isLoading || citations.isLoading) return <LoadingState label="正在读取固定版本报告" skeleton />
  const artifact = reports.data?.find((item) => item.version === reportVersion)
  if (run.isError || reports.isError || !artifact || !isReport(artifact.content)) return <AppEmptyState title="无法打开报告" description="报告可能不存在、已无权访问，或当前版本已隐藏事实内容。" action={<Button asChild variant="outline" className="min-h-11"><Link to="/library?view=reports">返回报告列表</Link></Button>} />
  if (!artifact.is_current) return <section className="grid min-w-0 gap-5"><Button asChild variant="ghost" className="min-h-11 w-fit px-2"><Link to={`/runs/${runId}`}><ArrowLeft className="size-4" />返回调研任务</Link></Button><div className="rounded-xl border border-[var(--status-waiting)] bg-[var(--status-waiting-bg)] p-5"><h1 className="text-xl font-semibold">历史报告 v{artifact.version}</h1><p className="mt-2 text-sm leading-6">该固定版本的上游引用、证据或内容版本已变化。为避免将失效事实伪装成当前结论，正文、对比、主张和引用已隐藏。</p><Button asChild variant="outline" className="mt-4 min-h-11"><Link to={`/runs/${runId}`}>查看任务状态并重新生成</Link></Button></div></section>
  const report = artifact.content
  const sourceVersions = report.generated_from_artifact_versions
  const matrixArtifact = artifacts.data?.find((item) => item.artifact_type === "comparison_matrix" && item.version === sourceVersions.comparison_matrix)
  const claimsArtifact = artifacts.data?.find((item) => item.artifact_type === "synthesis_claims" && item.version === sourceVersions.synthesis_claims)
  const matrix = matrixArtifact && isMatrix(matrixArtifact.content) ? matrixArtifact.content : null
  const claims = claimsArtifact && isClaims(claimsArtifact.content) ? claimsArtifact.content : null
  const reportCitations = (citations.data ?? []).filter((item) => item.artifact_version === sourceVersions.citation_registry)
  return <section className="grid min-w-0 gap-5">
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-3"><div className="min-w-0"><Button asChild variant="ghost" className="min-h-11 px-2"><Link to={`/runs/${runId}`}><ArrowLeft className="size-4" />返回调研任务</Link></Button><div className="mt-2 flex min-w-0 flex-wrap items-center gap-2"><h1 className="break-words text-2xl font-semibold [overflow-wrap:anywhere]">{report.title}</h1><Badge variant="outline">v{artifact.version}</Badge><Badge variant={artifact.is_current ? "secondary" : "outline"}>{artifact.is_current ? "当前有效" : "历史/已失效"}</Badge></div><p className="mt-2 break-words text-sm text-muted-foreground">{report.topic} · 来源任务：{run.data?.title ?? runId}</p></div><AddToProjectDialog item={{ item_type: "research_report", artifact_id: artifact.id, artifact_version: artifact.version }} /></div>
    <div className="sm:hidden"><Label htmlFor="report-view">报告内容</Label><Select value={view} onValueChange={(value) => setView(value as View)}><SelectTrigger id="report-view" className="mt-2 min-h-11 w-full"><SelectValue /></SelectTrigger><SelectContent>{views.map((item) => <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>)}</SelectContent></Select></div>
    <div className="hidden grid-cols-4 rounded-xl bg-muted p-1 sm:grid" role="tablist" aria-label="报告内容">{views.map((item) => <button key={item.value} id={`report-tab-${item.value}`} type="button" role="tab" aria-controls="report-tabpanel" aria-selected={view === item.value} tabIndex={view === item.value ? 0 : -1} className="min-h-11 rounded-lg px-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-background aria-selected:shadow-sm" onClick={() => setView(item.value)}>{item.label}</button>)}</div>
    <div id="report-tabpanel" role="tabpanel" aria-labelledby={`report-tab-${view}`}>
    {view === "report" ? <ReportReading report={report} citations={reportCitations} runId={runId} section={section} onSection={setSection} /> : null}
    {view === "comparison" ? <ComparisonView matrix={matrix} citations={reportCitations} runId={runId} /> : null}
    {view === "claims" ? <ClaimsView claims={claims} citations={reportCitations} runId={runId} /> : null}
    {view === "citations" ? <CitationRegistry citations={reportCitations} runId={runId} /> : null}
    </div>
  </section>
}

const sections = [
  { id: "summary", label: "执行摘要" }, { id: "questions", label: "研究问题" }, { id: "findings", label: "主要发现" },
  { id: "agreements", label: "共识" }, { id: "disagreements", label: "分歧" }, { id: "limitations", label: "局限与空白" }, { id: "conclusion", label: "结论" },
]

function ReportReading({ report, citations, runId, section, onSection }: { report: ResearchReport; citations: ResearchCitation[]; runId: string; section: string; onSection: (value: string) => void }) {
  const selected = sections.find((item) => item.id === section) ?? sections[0]
  return <div className="grid min-w-0 gap-5 lg:grid-cols-[220px_minmax(0,72ch)] lg:justify-center"><nav className="hidden h-fit gap-1 rounded-xl border p-2 lg:grid" aria-label="报告章节">{sections.map((item) => <button key={item.id} type="button" aria-current={selected.id === item.id ? "page" : undefined} className="min-h-11 rounded-lg px-3 text-left text-sm hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-muted aria-[current=page]:font-medium" onClick={() => onSection(item.id)}>{item.label}</button>)}</nav><article className="min-w-0 rounded-xl border p-4 sm:p-6"><div className="mb-5 lg:hidden"><Label htmlFor="report-section">当前章节</Label><Select value={selected.id} onValueChange={onSection}><SelectTrigger id="report-section" className="mt-2 min-h-11 w-full"><SelectValue /></SelectTrigger><SelectContent>{sections.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></div><h2 className="text-xl font-semibold">{selected.label}</h2><div className="mt-4">{selected.id === "summary" ? <Statements items={report.executive_summary} citations={citations} runId={runId} /> : selected.id === "questions" ? <TextList items={report.research_questions} /> : selected.id === "findings" ? <Statements items={report.findings} citations={citations} runId={runId} /> : selected.id === "agreements" ? <Statements items={report.agreements} citations={citations} runId={runId} /> : selected.id === "disagreements" ? <Statements items={report.disagreements} citations={citations} runId={runId} /> : selected.id === "limitations" ? <TextList items={[...report.limitations, ...report.research_gaps]} /> : <Statements items={report.conclusion} citations={citations} runId={runId} />}</div></article></div>
}

function Statements({ items, citations, runId }: { items: ResearchReport["findings"]; citations: ResearchCitation[]; runId: string }) {
  return <div className="grid gap-4">{items.length ? items.map((item) => <section key={item.statement_id} className="border-b pb-4 last:border-0 last:pb-0"><p className="break-words text-sm leading-7 [overflow-wrap:anywhere]">{item.text}</p><div className="mt-2 flex flex-wrap gap-2">{item.citation_keys.map((key) => <CitationButton key={key} citation={citations.find((entry) => entry.citation_key === key)} displayIndex={Math.max(0, citations.findIndex((entry) => entry.citation_key === key)) + 1} runId={runId} />)}</div></section>) : <p className="text-sm text-muted-foreground">本节没有通过校验的事实内容。</p>}</div>
}

function TextList({ items }: { items: string[] }) { return items.length ? <ul className="list-disc space-y-2 pl-5 text-sm leading-7 text-muted-foreground">{items.map((item) => <li key={item} className="break-words">{item}</li>)}</ul> : <p className="text-sm text-muted-foreground">本节暂无内容。</p> }

function ComparisonView({ matrix, citations, runId }: { matrix: ComparisonMatrix | null; citations: ResearchCitation[]; runId: string }) {
  if (!matrix) return <AppEmptyState title="对比矩阵不可用" description="固定报告版本没有可读取的对应矩阵。" />
  return <section aria-labelledby="report-comparison-heading"><h2 id="report-comparison-heading" className="text-lg font-semibold">论文对比</h2><div className="mt-4 grid gap-4 lg:grid-cols-2">{matrix.dimensions.map((dimension) => <section key={dimension} className="min-w-0 rounded-xl border p-4"><h3 className="break-words font-semibold">{dimension}</h3><div className="mt-3 grid gap-3">{matrix.cells.filter((cell) => cell.dimension === dimension).map((cell) => <article key={cell.cell_id} className="border-b pb-3 last:border-0 last:pb-0"><p className="break-words text-sm font-medium">{matrix.papers.find((paper) => paper.paper_id === cell.paper_id)?.title ?? "论文"}</p><p className="mt-1 break-words text-sm leading-6 text-muted-foreground">{cell.value}</p><div className="mt-2 flex flex-wrap gap-2">{cell.citation_keys.map((key) => <CitationButton key={key} citation={citations.find((entry) => entry.citation_key === key)} displayIndex={Math.max(0, citations.findIndex((entry) => entry.citation_key === key)) + 1} runId={runId} />)}</div></article>)}</div></section>)}</div></section>
}

function ClaimsView({ claims, citations, runId }: { claims: SynthesisClaims | null; citations: ResearchCitation[]; runId: string }) {
  if (!claims) return <AppEmptyState title="研究主张不可用" description="固定报告版本没有可读取的对应主张。" />
  const labels = { finding: "发现", agreement: "共识", disagreement: "分歧", limitation: "局限", gap: "研究空白" } as const
  return <section aria-labelledby="report-claims-heading"><h2 id="report-claims-heading" className="text-lg font-semibold">研究主张</h2><div className="mt-4 grid gap-3 lg:grid-cols-2">{claims.claims.map((claim) => <article key={claim.claim_id} className="min-w-0 rounded-xl border p-4"><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{labels[claim.claim_type]}</Badge><span className="text-xs text-muted-foreground">置信度 {Math.round(claim.confidence * 100)}%</span></div><p className="mt-3 break-words text-sm leading-6 [overflow-wrap:anywhere]">{claim.claim}</p>{claim.caveats.length ? <p className="mt-2 break-words text-xs text-muted-foreground">注意：{claim.caveats.join("；")}</p> : null}<div className="mt-3 flex flex-wrap gap-2">{[...claim.supporting_citations, ...claim.contradicting_citations].map((key) => <CitationButton key={key} citation={citations.find((entry) => entry.citation_key === key)} displayIndex={Math.max(0, citations.findIndex((entry) => entry.citation_key === key)) + 1} runId={runId} />)}</div></article>)}</div></section>
}

function CitationRegistry({ citations, runId }: { citations: ResearchCitation[]; runId: string }) {
  return <section aria-labelledby="report-citations-heading"><h2 id="report-citations-heading" className="text-lg font-semibold">引用清单</h2><p className="mt-1 text-sm text-muted-foreground">引用按当前报告版本编号；打开后会按当前权限重新校验证据。</p><div className="mt-4 grid gap-2">{citations.map((citation, index) => <CitationButton key={citation.id} citation={citation} displayIndex={index + 1} runId={runId} expanded />)}</div></section>
}

function CitationButton({ citation, displayIndex, runId, expanded = false }: { citation?: ResearchCitation; displayIndex: number; runId: string; expanded?: boolean }) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  if (!citation) return <span className="rounded-lg border border-destructive/40 px-2 py-1 text-xs text-destructive">引用缺失</span>
  return <><button ref={trigger} type="button" onClick={() => setOpen(true)} className={`${expanded ? "flex min-h-14 w-full items-center justify-between gap-3 px-3 text-left" : "inline-flex min-h-11 items-center gap-1 px-3"} rounded-lg border text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}><span className="inline-flex min-w-0 items-center gap-1"><Quote className="size-3.5 shrink-0" /><span className="break-words">引用 {displayIndex}</span></span>{expanded ? <Badge variant="outline">{citation.status === "valid" ? "有效" : citation.status === "stale" ? "内容已更新" : citation.status === "inaccessible" ? "不可访问" : "无效"}</Badge> : null}</button><ReportEvidenceSheet runId={runId} citation={citation} displayIndex={displayIndex} open={open} onOpenChange={(next) => { setOpen(next); if (!next) requestAnimationFrame(() => trigger.current?.focus()) }} /></>
}

function ReportEvidenceSheet({ runId, citation, displayIndex, open, onOpenChange }: { runId: string; citation: ResearchCitation; displayIndex: number; open: boolean; onOpenChange: (open: boolean) => void }) {
  const evidence = useResearchCitationEvidenceQuery(runId, citation.id, open && citation.status !== "inaccessible")
  const current = open && evidence.isSuccess && !evidence.isFetching ? evidence.data : citation
  return <Sheet open={open} onOpenChange={onOpenChange}><SheetContent className="w-full gap-0 p-0 sm:max-w-md"><SheetHeader className="border-b pr-14"><SheetTitle>引用 {displayIndex}</SheetTitle><SheetDescription>按当前权限和论文内容版本重新校验。</SheetDescription></SheetHeader><div className="grid gap-3 overflow-y-auto p-4" aria-live="polite">{evidence.isLoading || evidence.isFetching ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />正在重新校验证据</p> : null}{evidence.isError ? <p role="alert" className="rounded-xl border border-destructive/40 p-3 text-sm text-destructive">证据读取失败；未使用旧缓存内容。</p> : null}{current.status === "inaccessible" ? <p className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">当前权限下不显示标题、内部引用标识、章节或原文。</p> : <><Badge variant="outline" className="w-fit">{current.status === "valid" ? "有效" : current.status === "stale" ? "内容已更新" : "无效"}</Badge>{current.status === "valid" ? <><p className="break-words text-sm text-muted-foreground">{current.heading || "未命名章节"}</p>{current.excerpt ? <blockquote className="whitespace-pre-wrap break-words rounded-xl bg-muted/60 p-4 text-sm leading-6 [overflow-wrap:anywhere]">{current.excerpt}</blockquote> : null}{current.paper_id && current.chunk_id ? <Button asChild variant="outline" className="min-h-11"><Link to={`/papers/${current.paper_id}?chunk=${current.chunk_id}&start=${current.char_start ?? ""}&end=${current.char_end ?? ""}&run=${runId}&report=${displayIndex}`}>在论文中定位<ExternalLink className="size-4" /></Link></Button> : null}</> : <p className="text-sm text-muted-foreground">该状态不返回事实文本，请生成新的当前版本。</p>}</>}</div></SheetContent></Sheet>
}
