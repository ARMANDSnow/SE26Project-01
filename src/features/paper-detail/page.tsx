import {
  ArrowLeft,
  BookOpen,
  Bot,
  Columns2,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  NotebookPen,
  PanelLeft,
  Plus,
  Sparkles,
  Star,
} from "lucide-react"
import { FormEvent, useEffect, useMemo, useRef, useState } from "react"
import { Link, useParams, useSearchParams } from "react-router"
import { toast } from "sonner"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { MarkdownBlock } from "@/components/common/markdown-block"
import { ProcessingBadge } from "@/components/common/status-badge"
import { AddToProjectDialog } from "@/components/research/add-to-project-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import {
  useAddNoteMutation,
  useFavoriteMutation,
  useGeneratePaperSummaryMutation,
  usePaperChunksQuery,
  usePaperQuery,
  useParsePaperDocumentMutation,
  useResearchProjectBacklinksQuery,
} from "@/lib/query-hooks"
import { cn } from "@/lib/utils"
import { formatLocalDateTime } from "@/lib/date-time"
import { PaperChat } from "./paper-chat"

type LayoutMode = "reading" | "split" | "chat"
type WorkspaceTab = "source" | "summary" | "notes"

export function PaperDetailPage() {
  const { paperId = "" } = useParams()
  const [searchParams] = useSearchParams()
  const id = Number(paperId)
  const evidenceChunkId = Number(searchParams.get("chunk"))
  const hasEvidenceTarget = Number.isInteger(evidenceChunkId) && evidenceChunkId > 0
  const paperQuery = usePaperQuery(id)
  const projectBacklinks = useResearchProjectBacklinksQuery({ item_type: "paper", paper_id: id }, Number.isInteger(id) && id > 0)
  const chunksQuery = usePaperChunksQuery(id)
  const favoriteMutation = useFavoriteMutation()
  const parseMutation = useParsePaperDocumentMutation()
  const summaryMutation = useGeneratePaperSummaryMutation()
  const addNoteMutation = useAddNoteMutation()
  const [layout, setLayout] = useState<LayoutMode>("split")
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>(hasEvidenceTarget ? "source" : "summary")
  const [sourceView, setSourceView] = useState<"pdf" | "text">(hasEvidenceTarget ? "text" : "pdf")
  const evidenceRef = useRef<HTMLElement>(null)
  const [note, setNote] = useState("")
  const [comment, setComment] = useState("")
  const paper = paperQuery.data
  const evidenceChunk = chunksQuery.data?.find((chunk) => chunk.id === evidenceChunkId)

  useEffect(() => {
    if (!hasEvidenceTarget || !evidenceChunk) return
    setWorkspaceTab("source")
    setSourceView("text")
    requestAnimationFrame(() => {
      evidenceRef.current?.scrollIntoView({ block: "center" })
      evidenceRef.current?.focus()
    })
  }, [evidenceChunk, hasEvidenceTarget])

  const currentSummary = useMemo(
    () => paper?.summaries?.find((summary) => Boolean(summary.is_active)) ?? paper?.summaries?.[0],
    [paper?.summaries],
  )

  if (paperQuery.isLoading) return <LoadingState label="正在加载论文工作台" skeleton />
  if (!paper) {
    return <AppEmptyState title="没有找到论文" description="请回到论文库选择一篇可用论文。" action={<Button asChild variant="outline"><Link to="/papers">返回论文库</Link></Button>} />
  }

  const documentReady = paper.document?.status === "completed"
  const pdfUrl = paper.pdf.view_url
  const busy = favoriteMutation.isPending || parseMutation.isPending || summaryMutation.isPending || addNoteMutation.isPending

  const onParse = async () => {
    try {
      await parseMutation.mutateAsync(paper.id)
      toast.success("Docling 已完成论文全文解析。")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "论文解析失败")
    }
  }

  const onSummary = async () => {
    try {
      await summaryMutation.mutateAsync(paper.id)
      toast.success(currentSummary ? "已生成新的概要版本。" : "论文概要已生成。")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "概要生成失败")
    }
  }

  const onFavorite = async () => {
    try {
      await favoriteMutation.mutateAsync({ paperId: paper.id, favorite: !paper.is_favorite })
      toast.success(paper.is_favorite ? "已取消收藏。" : "已收藏论文。")
    } catch {
      toast.error("收藏状态更新失败。")
    }
  }

  const onSubmitNote = async (event: FormEvent) => {
    event.preventDefault()
    if (!note.trim()) return
    try {
      await addNoteMutation.mutateAsync({ paperId: paper.id, note: note.trim(), comment: comment.trim() })
      setNote("")
      setComment("")
      toast.success("笔记已保存。")
    } catch {
      toast.error("笔记保存失败。")
    }
  }

  return (
    <section className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button asChild variant="ghost" className="min-h-11 px-2"><Link to="/papers"><ArrowLeft className="size-4" />返回论文库</Link></Button>
        <div className="inline-flex rounded-lg border bg-card p-1" aria-label="工作台布局">
          <Button size="sm" variant={layout === "reading" ? "secondary" : "ghost"} onClick={() => setLayout("reading")}><PanelLeft className="size-4" />阅读</Button>
          <Button size="sm" variant={layout === "split" ? "secondary" : "ghost"} onClick={() => setLayout("split")}><Columns2 className="size-4" />并排</Button>
          <Button size="sm" variant={layout === "chat" ? "secondary" : "ghost"} onClick={() => setLayout("chat")}><Bot className="size-4" />Chat</Button>
        </div>
      </div>

      <Card>
        <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="rounded-full bg-primary/10 text-primary hover:bg-primary/10">{paper.primary_category}</Badge>
              <ProcessingBadge status={documentReady ? "processed" : paper.processing_status} />
              <Badge variant={documentReady ? "secondary" : "outline"} className="rounded-full">
                {paper.document?.status === "processing" ? "正在解析全文" : documentReady ? `全文 ${paper.document?.token_count.toLocaleString()} tokens` : paper.document?.status === "failed" ? "全文解析失败" : "尚未解析全文"}
              </Badge>
            </div>
            <h1 className="text-2xl font-semibold leading-tight md:text-3xl">{paper.title}</h1>
            <p className="line-clamp-3 max-w-5xl text-sm leading-6 text-muted-foreground">{paper.abstract}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <span>{paper.authors.join("、") || "作者未知"}</span><span>{paper.published_at}</span><span>{paper.venue ?? paper.source}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-start gap-2 lg:justify-end">
            <AddToProjectDialog item={{ item_type: "paper", paper_id: paper.id }} />
            <Button variant={paper.is_favorite ? "secondary" : "outline"} size="icon" className="size-11" onClick={onFavorite} disabled={busy} aria-label="收藏">
              <Star className={cn("size-4", paper.is_favorite && "fill-current")} />
            </Button>
            <Button variant="outline" className="min-h-11" onClick={onParse} disabled={busy || !paper.pdf.available}>
              {parseMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />}{documentReady ? "重新解析全文" : "解析全文"}
            </Button>
            <Button className="min-h-11" onClick={onSummary} disabled={busy || !documentReady}>
              {summaryMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}{currentSummary ? "重新生成概要" : "生成概要"}
            </Button>
            {paper.pdf.download_url ? <Button asChild variant="outline" size="icon" className="size-11"><a href={paper.pdf.download_url} aria-label="下载 PDF"><Download className="size-4" /></a></Button> : null}
            {paper.source_url ? <Button asChild variant="outline" size="icon" className="size-11"><a href={paper.source_url} target="_blank" rel="noreferrer" aria-label="来源页面"><ExternalLink className="size-4" /></a></Button> : null}
          </div>
        </CardContent>
      </Card>

      <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>所属研究项目：</span>{projectBacklinks.isLoading ? <span>正在读取…</span> : (projectBacklinks.data ?? []).length ? projectBacklinks.data?.map((item) => <Button key={item.project_id} asChild variant="link" className="h-auto min-h-11 px-1"><Link to={`/library/projects/${item.project_id}`}>{item.project_title}</Link></Button>) : <span>尚未加入</span>}</div>

      {paper.document?.status === "failed" ? <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">Docling 解析失败：{paper.document.error}</div> : null}

      <div className={cn("grid min-h-[620px] gap-4", layout === "split" && "xl:grid-cols-2")}>
        {layout !== "chat" ? (
          <Card className="min-w-0 overflow-hidden">
            <Tabs value={workspaceTab} onValueChange={(value) => {
              if (value === "source" || value === "summary" || value === "notes") setWorkspaceTab(value)
            }} className="flex h-full min-h-[620px] flex-col">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3">
                <TabsList>
                  <TabsTrigger value="source"><BookOpen className="size-4" />原文</TabsTrigger>
                  <TabsTrigger value="summary"><Sparkles className="size-4" />概要</TabsTrigger>
                  <TabsTrigger value="notes"><NotebookPen className="size-4" />笔记</TabsTrigger>
                </TabsList>
                {workspaceTab === "source" ? <div className="inline-flex rounded-md border p-0.5">
                  <Button size="sm" variant={sourceView === "pdf" ? "secondary" : "ghost"} onClick={() => setSourceView("pdf")}>PDF</Button>
                  <Button size="sm" variant={sourceView === "text" ? "secondary" : "ghost"} onClick={() => setSourceView("text")} disabled={!documentReady}>解析文本</Button>
                </div> : null}
              </div>
              <TabsContent value="source" className="mt-0 min-h-0 flex-1 overflow-auto p-0">
                {workspaceTab === "source" && sourceView === "pdf" && pdfUrl ? <iframe title={paper.title} src={pdfUrl} className="h-[720px] w-full bg-muted" /> : documentReady ? <div className="p-5">{hasEvidenceTarget ? chunksQuery.isLoading ? <p className="mb-4 text-sm text-muted-foreground" aria-live="polite">正在定位 Citation Evidence…</p> : chunksQuery.isError ? <p className="mb-4 text-sm text-destructive" role="alert">Evidence 定位失败；未用全文缓存伪装定位结果。</p> : evidenceChunk ? <section ref={evidenceRef} tabIndex={-1} className="mb-5 min-w-0 rounded-xl border border-primary/35 bg-primary/5 p-4 outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Citation Evidence 定位" role="status"><p className="text-xs font-semibold text-primary">Citation Evidence · Chunk {evidenceChunk.id}</p><h2 className="mt-1 break-words text-sm font-semibold [overflow-wrap:anywhere]">{evidenceChunk.heading || "未命名章节"}</h2><p className="mt-1 text-xs text-muted-foreground">字符 {evidenceChunk.char_start}–{evidenceChunk.char_end}</p><blockquote className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 [overflow-wrap:anywhere]"><mark className="rounded bg-[var(--status-waiting-bg)] px-0.5 text-foreground">{evidenceChunk.content}</mark></blockquote></section> : <p className="mb-4 text-sm text-destructive" role="alert">当前论文与 source hash 下不存在该 Evidence Chunk。</p> : null}<MarkdownBlock content={paper.document?.content_markdown ?? ""} className="max-w-none" /></div> : <AppEmptyState title="尚未生成可阅读的全文" description="点击“解析全文”，使用 Docling 读取完整 PDF。" />}
              </TabsContent>
              <TabsContent value="summary" className="mt-0 min-h-0 flex-1 overflow-auto p-5">
                {currentSummary ? <div className="grid gap-4"><div className="text-xs text-muted-foreground">{currentSummary.model} · {formatLocalDateTime(currentSummary.created_at)}</div><MarkdownBlock content={currentSummary.content} className="max-w-none" /></div> : <AppEmptyState title="还没有全文概要" description={documentReady ? "点击顶部“生成概要”。" : "请先完成论文全文解析。"} />}
              </TabsContent>
              <TabsContent value="notes" className="mt-0 min-h-0 flex-1 overflow-auto p-5">
                <div className="mx-auto grid max-w-3xl gap-5">
                  <form className="grid gap-3" onSubmit={onSubmitNote}>
                    <div className="grid gap-2"><Label htmlFor="paper-note">阅读笔记</Label><Textarea id="paper-note" className="min-h-32" value={note} onChange={(event) => setNote(event.target.value)} placeholder="记录方法、实验、疑问或对比点…" /></div>
                    <div className="grid gap-2"><Label htmlFor="paper-comment">标签或评论</Label><Input id="paper-comment" value={comment} onChange={(event) => setComment(event.target.value)} placeholder="可选" /></div>
                    <Button className="w-fit" disabled={busy || !note.trim()}>{addNoteMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}保存笔记</Button>
                  </form>
                  <div className="grid gap-2">{(paper.notes ?? []).map((item) => <article key={item.id} className="rounded-lg border bg-background p-3"><p className="text-sm leading-6">{item.note}</p>{item.comment ? <span className="mt-1 block text-xs text-muted-foreground">{item.comment}</span> : null}</article>)}{!paper.notes?.length ? <AppEmptyState title="暂无笔记" /> : null}</div>
                </div>
              </TabsContent>
            </Tabs>
          </Card>
        ) : null}

        {layout !== "reading" ? <PaperChat paperId={paper.id} enabled={documentReady} /> : null}
      </div>
    </section>
  )
}
