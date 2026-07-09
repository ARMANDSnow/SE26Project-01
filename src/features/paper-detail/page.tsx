import {
  ArrowLeft,
  BookOpen,
  Bookmark,
  Clock3,
  ExternalLink,
  FileSearch,
  FileText,
  Loader2,
  Plus,
  Sparkles,
  Star,
  Tags,
} from "lucide-react"
import { FormEvent, useEffect, useState } from "react"
import { Link, useParams } from "react-router"
import { toast } from "sonner"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { MarkdownBlock } from "@/components/common/markdown-block"
import { ProcessingBadge, ReadingBadge } from "@/components/common/status-badge"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { plainSnippet, sectionNames } from "@/lib/format"
import {
  useAddNoteMutation,
  useFavoriteMutation,
  usePaperChunksQuery,
  usePaperQuery,
  useProcessPaperMutation,
} from "@/lib/query-hooks"
import { cn } from "@/lib/utils"

const sourceLabels: Record<string, string> = {
  html: "HTML",
  pdf: "PDF",
  metadata: "元数据",
}

export function PaperDetailPage() {
  const { paperId = "" } = useParams()
  const id = Number(paperId)
  const paperQuery = usePaperQuery(id)
  const chunksQuery = usePaperChunksQuery(id)
  const favoriteMutation = useFavoriteMutation()
  const processMutation = useProcessPaperMutation()
  const addNoteMutation = useAddNoteMutation()
  const paper = paperQuery.data
  const [activeSection, setActiveSection] = useState("summary")
  const [note, setNote] = useState("")
  const [comment, setComment] = useState("")

  useEffect(() => {
    if (paper?.wiki?.length) {
      setActiveSection((current) => paper.wiki?.some((section) => section.section === current) ? current : paper.wiki?.[0]?.section ?? "summary")
    }
  }, [paper])

  if (paperQuery.isLoading) {
    return <LoadingState label="正在加载论文详情" skeleton />
  }

  if (!paper) {
    return (
      <AppEmptyState
        title="没有找到论文"
        description="请回到论文库选择一篇可用论文。"
        action={
          <Button asChild variant="outline" className="h-11">
            <Link to="/papers">返回论文库</Link>
          </Button>
        }
      />
    )
  }

  const activeWiki = paper.wiki?.find((section) => section.section === activeSection) ?? paper.wiki?.[0]
  const chunks = chunksQuery.data?.items ?? []
  const chunkCount = chunksQuery.isError ? 0 : chunksQuery.data?.count ?? paper.chunk_count ?? 0
  const busy = favoriteMutation.isPending || processMutation.isPending || addNoteMutation.isPending

  const onFavorite = async () => {
    try {
      await favoriteMutation.mutateAsync({ paperId: paper.id, favorite: !paper.is_favorite })
      toast.success(paper.is_favorite ? "已取消收藏。" : "已收藏论文。")
    } catch {
      toast.error("收藏状态更新失败，请稍后重试。")
    }
  }

  const onProcess = async () => {
    try {
      await processMutation.mutateAsync(paper.id)
      toast.success("结构化解析已完成。")
    } catch {
      toast.error("结构化解析失败，请稍后重试。")
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
      toast.error("笔记保存失败，请确认后端服务是否运行。")
    }
  }

  return (
    <section className="grid gap-5">
      <Button asChild variant="ghost" className="h-11 w-fit px-2">
        <Link to="/papers">
          <ArrowLeft className="size-4" />
          返回论文库
        </Link>
      </Button>

      <Card>
        <CardContent className="grid gap-5 p-4 lg:grid-cols-[minmax(0,1fr)_auto]">
          <div className="min-w-0 space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="rounded-full bg-primary/10 text-primary hover:bg-primary/10">{paper.primary_category}</Badge>
              <ProcessingBadge status={paper.processing_status} />
              <ReadingBadge status={paper.reading_status} />
            </div>
            <div className="space-y-3">
              <h1 className="text-2xl font-semibold leading-tight text-foreground md:text-3xl">{paper.title}</h1>
              <p className="max-w-5xl text-sm leading-7 text-muted-foreground">{paper.abstract}</p>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <BookOpen className="size-3.5" />
                {paper.authors.join("、")}
              </span>
              <span className="inline-flex items-center gap-1">
                <Clock3 className="size-3.5" />
                {paper.published_at}
              </span>
              <span className="inline-flex items-center gap-1">
                <FileText className="size-3.5" />
                {paper.arxiv_id}
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-start gap-2 lg:justify-end">
            <Button
              variant={paper.is_favorite ? "secondary" : "outline"}
              size="icon"
              className="size-11"
              aria-label={paper.is_favorite ? "取消收藏" : "收藏"}
              onClick={onFavorite}
              disabled={busy}
            >
              <Star className={cn("size-4", paper.is_favorite && "fill-[var(--chart-2)] text-[var(--chart-2)]")} />
            </Button>
            <Button variant="outline" className="h-11" onClick={onProcess} disabled={busy}>
              {processMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              结构化解析
            </Button>
            {paper.arxiv_url ? (
              <Button asChild variant="outline" className="h-11">
                <a href={paper.arxiv_url} target="_blank" rel="noreferrer">
                  <ExternalLink className="size-4" />
                  arXiv
                </a>
              </Button>
            ) : null}
            {paper.pdf_url ? (
              <Button asChild variant="outline" className="h-11">
                <a href={paper.pdf_url} target="_blank" rel="noreferrer">
                  <FileText className="size-4" />
                  PDF
                </a>
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {paper.processing_status !== "processed" ? (
        <Alert>
          <Sparkles className="size-4" />
          <AlertTitle>这篇论文还未完成 Wiki 结构化</AlertTitle>
          <AlertDescription>可先查看摘要，或点击结构化解析生成 Wiki、概念和实验信息。</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.8fr)]">
        <Card className="min-h-[520px]">
          <CardContent className="p-4">
            {paper.wiki?.length ? (
              <Tabs value={activeSection} onValueChange={setActiveSection}>
                <TabsList className="mb-4 flex h-auto flex-wrap justify-start gap-2 bg-transparent p-0">
                  {paper.wiki.map((section) => (
                    <TabsTrigger key={section.section} value={section.section} className="min-h-11 rounded-lg border px-3">
                      {sectionNames[section.section] ?? section.section}
                    </TabsTrigger>
                  ))}
                </TabsList>
                {paper.wiki.map((section) => (
                  <TabsContent key={section.section} value={section.section} className="mt-0">
                    <MarkdownBlock content={section.content} />
                  </TabsContent>
                ))}
              </Tabs>
            ) : activeWiki ? (
              <MarkdownBlock content={activeWiki.content} />
            ) : (
              <AppEmptyState title="这篇论文还未生成 Wiki 内容" />
            )}
          </CardContent>
        </Card>

        <aside className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="inline-flex items-center gap-2 text-lg">
                <Tags className="size-4" />
                概念标签
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              {(paper.concepts ?? []).map((concept) => (
                <div key={concept.id} className="grid gap-1 rounded-lg bg-muted/60 p-3">
                  <strong className="text-sm">{concept.name}</strong>
                  <span className="text-xs text-muted-foreground">
                    {concept.relation} · {(concept.weight * 100).toFixed(0)}%
                  </span>
                </div>
              ))}
              {!paper.concepts?.length ? <AppEmptyState title="暂无概念标签" /> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3">
              <CardTitle className="inline-flex items-center gap-2 text-lg">
                <FileSearch className="size-4" />
                原文片段
              </CardTitle>
              <Badge variant="secondary" className="rounded-full">
                {chunkCount} 条
              </Badge>
            </CardHeader>
            <CardContent className="grid gap-2">
              {chunksQuery.isLoading ? <LoadingState label="正在加载片段" /> : null}
              {chunksQuery.isError ? (
                <Alert variant="destructive">
                  <AlertTitle>原文片段加载失败</AlertTitle>
                  <AlertDescription>请稍后重试，或重新执行结构化解析。</AlertDescription>
                </Alert>
              ) : null}
              {chunks.map((chunk) => (
                <article key={chunk.id} className="grid min-w-0 gap-2 rounded-lg border bg-background p-3">
                  <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                    <strong className="min-w-0 text-sm [overflow-wrap:anywhere]">{chunk.heading || `Chunk #${chunk.chunk_index + 1}`}</strong>
                    <Badge variant="outline" className="max-w-full rounded-full [overflow-wrap:anywhere]">
                      {sourceLabels[chunk.source_type] ?? chunk.source_type}
                    </Badge>
                  </div>
                  <p className="line-clamp-4 text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{plainSnippet(chunk.content, 260)}</p>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <span>#{chunk.chunk_index + 1}</span>
                    <span>{chunk.token_count} tokens</span>
                    <span>
                      {chunk.char_start}-{chunk.char_end}
                    </span>
                    {chunk.source_url ? (
                      <a
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                        href={chunk.source_url}
                        target="_blank"
                        rel="noreferrer"
                        aria-label={`打开${sourceLabels[chunk.source_type] ?? chunk.source_type}片段 #${chunk.chunk_index + 1} 来源`}
                      >
                        <ExternalLink className="size-3" />
                        来源
                      </a>
                    ) : null}
                  </div>
                </article>
              ))}
              {!chunks.length && !chunksQuery.isLoading && !chunksQuery.isError ? <AppEmptyState title="暂无原文片段" /> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="inline-flex items-center gap-2 text-lg">
                <Bookmark className="size-4" />
                笔记
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4">
              <form className="grid gap-3" onSubmit={onSubmitNote}>
                <div className="grid gap-2">
                  <Label htmlFor="paper-note">阅读笔记</Label>
                  <Textarea
                    id="paper-note"
                    className="min-h-28"
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="记录阅读笔记"
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="paper-comment">评论或对比点</Label>
                  <Input
                    id="paper-comment"
                    className="h-11"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder="补充评论"
                  />
                </div>
                <Button className="h-11" disabled={busy || !note.trim()}>
                  {addNoteMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
                  保存
                </Button>
              </form>

              <div className="grid gap-2">
                {(paper.notes ?? []).map((item) => (
                  <article key={item.id} className="rounded-lg border bg-background p-3">
                    <p className="text-sm leading-6">{item.note}</p>
                    {item.comment ? <span className="mt-1 block text-xs text-muted-foreground">{item.comment}</span> : null}
                  </article>
                ))}
                {!paper.notes?.length ? <AppEmptyState title="暂无笔记" /> : null}
              </div>
            </CardContent>
          </Card>
        </aside>
      </div>
    </section>
  )
}
