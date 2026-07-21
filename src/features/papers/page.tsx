import { Filter, Loader2, RefreshCw, Search, Upload } from "lucide-react"
import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router"
import { toast } from "sonner"
import { PageHeader } from "@/components/common/page-header"
import { LoadingState } from "@/components/common/loading-state"
import { AppEmptyState } from "@/components/common/empty-state"
import { PaperCard } from "@/components/papers/paper-card"
import { PaperTable } from "@/components/papers/paper-table"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { defaultCategories, uniqueValues } from "@/lib/format"
import { PaperFilters, useFavoriteMutation, useIngestArxivMutation, useIngestSourceMutation, usePapersQuery, useUploadPaperMutation } from "@/lib/query-hooks"
import type { Paper } from "@/types"

function filtersFromParams(searchParams: URLSearchParams): PaperFilters {
  return {
    q: searchParams.get("q") ?? "",
    category: searchParams.get("category") ?? "",
    concept: searchParams.get("concept") ?? "",
    favorite: searchParams.get("favorite") === "true",
    limit: 80,
  }
}

const SOURCE_INGEST_MAX_RESULTS = 50

export function PapersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = filtersFromParams(searchParams)
  const [q, setQ] = useState(filters.q ?? "")
  const [category, setCategory] = useState(filters.category ?? "")
  const [concept, setConcept] = useState(filters.concept ?? "")
  const [favoriteOnly, setFavoriteOnly] = useState(Boolean(filters.favorite))
  const [source, setSource] = useState<"arxiv" | "usenix" | "sigops">("arxiv")
  const [venue, setVenue] = useState("osdi")
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [uploadVisibility, setUploadVisibility] = useState<"private" | "public">("private")
  const fileInputRef = useRef<HTMLInputElement>(null)

  const papersQuery = usePapersQuery(filters)
  const ingestMutation = useIngestArxivMutation()
  const sourceIngestMutation = useIngestSourceMutation()
  const uploadMutation = useUploadPaperMutation()
  const favoriteMutation = useFavoriteMutation()
  const papers = papersQuery.data ?? []

  useEffect(() => {
    setQ(filters.q ?? "")
    setCategory(filters.category ?? "")
    setConcept(filters.concept ?? "")
    setFavoriteOnly(Boolean(filters.favorite))
  }, [filters.q, filters.category, filters.concept, filters.favorite])

  const categories = useMemo(
    () => uniqueValues([...papers.flatMap((paper) => paper.categories), ...defaultCategories]).slice(0, 12),
    [papers]
  )

  const activeFilters = [
    filters.q && `关键词：${filters.q}`,
    filters.category && `分类：${filters.category}`,
    filters.concept && `概念：${filters.concept}`,
    filters.favorite && "仅收藏",
  ].filter((item): item is string => Boolean(item))

  const applyFilters = (event?: FormEvent) => {
    event?.preventDefault()
    const next = new URLSearchParams()
    if (q.trim()) next.set("q", q.trim())
    if (category) next.set("category", category)
    if (concept.trim()) next.set("concept", concept.trim())
    if (favoriteOnly) next.set("favorite", "true")
    setSearchParams(next)
  }

  const resetFilters = () => {
    setQ("")
    setCategory("")
    setConcept("")
    setFavoriteOnly(false)
    setSearchParams(new URLSearchParams())
  }

  const onIngest = async () => {
    const keywords = q.trim() ? q.trim().split(/\s+/).filter(Boolean) : ["RAG"]
    try {
      const result = source === "arxiv"
        ? await ingestMutation.mutateAsync({ categories: category ? [category] : [], keywords, max_results: 8 })
        : await sourceIngestMutation.mutateAsync({
            source,
            venue: venue.trim() || (source === "usenix" ? "osdi" : "sosp"),
            year: Number(year) || new Date().getFullYear(),
            max_results: SOURCE_INGEST_MAX_RESULTS,
          })
      toast.success(`已导入 ${result.count} 篇论文，其中 ${result.queued_count} 篇已进入后台加工。`)
    } catch {
      toast.warning("论文导入失败，请确认会议年份、来源页面和网络连接。")
    }
  }

  const onSourceChange = (value: "arxiv" | "usenix" | "sigops") => {
    setSource(value)
    if (value === "usenix") setVenue("osdi")
    if (value === "sigops") setVenue("sosp")
  }

  const onUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const paper = await uploadMutation.mutateAsync({
        file,
        year: Number(year) || new Date().getFullYear(),
        visibility: uploadVisibility,
      })
      toast.success(`已${uploadVisibility === "private" ? "私有" : "公开"}上传《${paper.title}》，后台将自动解析全文。`)
    } catch {
      toast.error("PDF 上传或读取失败，请确认文件未加密且不超过 30 MB。")
    } finally {
      event.target.value = ""
    }
  }

  const onFavorite = async (paper: Paper) => {
    try {
      await favoriteMutation.mutateAsync({ paperId: paper.id, favorite: !paper.is_favorite })
      toast.success(paper.is_favorite ? "已取消收藏。" : "已收藏论文。")
    } catch {
      toast.error("收藏状态更新失败，请稍后重试。")
    }
  }

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="论文自动导入与管理"
        title="论文库"
        description="以标题、作者、摘要、分类和概念标签检索论文，并进入详情页继续阅读。"
        actions={
          <div className="flex flex-wrap gap-2">
            <input ref={fileInputRef} type="file" accept="application/pdf,.pdf" className="hidden" onChange={onUpload} />
            <Select value={uploadVisibility} onValueChange={(value) => setUploadVisibility(value as "private" | "public")}>
              <SelectTrigger className="h-11 w-[132px]" aria-label="上传可见性">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="private">私有上传</SelectItem>
                <SelectItem value="public">公开上传</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" className="h-11" onClick={() => fileInputRef.current?.click()} disabled={uploadMutation.isPending}>
              {uploadMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              上传 PDF
            </Button>
            <Button className="h-11" onClick={onIngest} disabled={ingestMutation.isPending || sourceIngestMutation.isPending || papersQuery.isFetching}>
              {ingestMutation.isPending || sourceIngestMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
              导入来源论文
            </Button>
          </div>
        }
      />

      <Card>
        <CardContent className="p-4">
          <form className="grid gap-3 xl:grid-cols-[minmax(220px,1fr)_160px_150px_150px_100px_auto]" onSubmit={applyFilters} aria-label="论文检索筛选">
            <div className="grid gap-2 xl:col-auto">
              <Label htmlFor="paper-q">搜索</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="paper-q"
                  className="h-11 pl-9"
                  value={q}
                  onChange={(event) => setQ(event.target.value)}
                  placeholder="标题、作者、摘要、关键词"
                />
              </div>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="paper-category">分类</Label>
              <Select value={category || "all"} onValueChange={(value) => setCategory(value === "all" ? "" : value)}>
                <SelectTrigger id="paper-category" className="h-11 w-full">
                  <SelectValue placeholder="全部分类" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部分类</SelectItem>
                  {categories.map((item) => (
                    <SelectItem key={item} value={item}>
                      {item}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="ingest-source">导入来源</Label>
              <Select value={source} onValueChange={(value) => onSourceChange(value as "arxiv" | "usenix" | "sigops")}>
                <SelectTrigger id="ingest-source" className="h-11 w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="arxiv">arXiv</SelectItem>
                  <SelectItem value="usenix">USENIX</SelectItem>
                  <SelectItem value="sigops">SIGOPS / SOSP</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {source !== "arxiv" ? (
              <>
                <div className="grid gap-2">
                  <Label htmlFor="ingest-venue">会议</Label>
                  <Input id="ingest-venue" className="h-11" value={venue} onChange={(event) => setVenue(event.target.value)} placeholder={source === "usenix" ? "osdi 或 atc" : "sosp"} />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="ingest-year">年份</Label>
                  <Input id="ingest-year" className="h-11" inputMode="numeric" value={year} onChange={(event) => setYear(event.target.value)} />
                </div>
              </>
            ) : <div className="hidden xl:block" />}

            <div className="grid gap-2">
              <Label htmlFor="paper-concept">概念</Label>
              <Input
                id="paper-concept"
                className="h-11"
                value={concept}
                onChange={(event) => setConcept(event.target.value)}
                placeholder="概念标签"
              />
            </div>

            <div className="flex min-h-11 items-end gap-2 xl:pt-7">
              <Switch id="favorite-only" checked={favoriteOnly} onCheckedChange={setFavoriteOnly} />
              <Label htmlFor="favorite-only" className="pb-2 text-sm font-medium">
                仅收藏
              </Label>
            </div>

            <div className="flex items-end gap-2">
              <Button type="submit" variant="outline" className="h-11" disabled={papersQuery.isFetching}>
                {papersQuery.isFetching ? <Loader2 className="size-4 animate-spin" /> : <Filter className="size-4" />}
                检索
              </Button>
              <Button type="button" variant="ghost" className="h-11" onClick={resetFilters}>
                重置
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <span className="font-semibold text-foreground">{papersQuery.isFetching ? "正在检索" : `显示 ${papers.length} 篇论文`}</span>
        <div className="flex flex-wrap gap-1.5">
          {activeFilters.length ? (
            activeFilters.map((item) => (
              <Badge key={item} variant="secondary" className="rounded-full">
                {item}
              </Badge>
            ))
          ) : (
            <Badge variant="secondary" className="rounded-full">
              全部论文
            </Badge>
          )}
        </div>
      </div>

      {papersQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>论文检索失败</AlertTitle>
          <AlertDescription>请稍后重试，或确认后端服务是否运行。</AlertDescription>
        </Alert>
      ) : null}

      {papersQuery.isLoading ? (
        <LoadingState label="正在加载论文列表" skeleton />
      ) : papers.length ? (
        <>
          <div className="hidden lg:block" aria-busy={papersQuery.isFetching}>
            <PaperTable papers={papers} onFavorite={onFavorite} favoriteBusy={favoriteMutation.isPending} />
          </div>
          <div className="grid gap-3 lg:hidden" aria-busy={papersQuery.isFetching}>
            {papers.map((paper) => (
              <PaperCard
                key={paper.id}
                paper={paper}
                onFavorite={onFavorite}
                favoriteBusy={favoriteMutation.isPending}
              />
            ))}
          </div>
        </>
      ) : (
        <AppEmptyState
          title="没有匹配的论文"
          description="尝试减少筛选条件，或同步新的 arXiv 论文。"
          action={
            <Button variant="outline" className="h-11" onClick={resetFilters}>
              清空筛选
            </Button>
          }
        />
      )}
    </section>
  )
}
