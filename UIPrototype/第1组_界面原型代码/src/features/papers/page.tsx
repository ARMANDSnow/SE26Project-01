import { Filter, Loader2, RefreshCw, Search } from "lucide-react"
import { FormEvent, useEffect, useMemo, useState } from "react"
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
import { PaperFilters, useFavoriteMutation, useIngestArxivMutation, usePapersQuery } from "@/lib/query-hooks"
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

export function PapersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = filtersFromParams(searchParams)
  const [q, setQ] = useState(filters.q ?? "")
  const [category, setCategory] = useState(filters.category ?? "")
  const [concept, setConcept] = useState(filters.concept ?? "")
  const [favoriteOnly, setFavoriteOnly] = useState(Boolean(filters.favorite))

  const papersQuery = usePapersQuery(filters)
  const ingestMutation = useIngestArxivMutation()
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
      const result = await ingestMutation.mutateAsync({
        categories: category ? [category] : [],
        keywords,
        max_results: 8,
      })
      toast.success(`已从 arXiv 新增 ${result.count} 篇论文，抓取 ${result.fetched_count} 篇，去重 ${result.duplicate_count} 篇。`)
    } catch {
      toast.warning("arXiv 抓取失败，当前仍可使用内置样例数据。")
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
        eyebrow="论文自动抓取与管理"
        title="论文库"
        description="以标题、作者、摘要、分类和概念标签检索论文，并进入详情页继续阅读。"
        actions={
          <Button className="h-11" onClick={onIngest} disabled={ingestMutation.isPending || papersQuery.isFetching}>
            {ingestMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            同步 arXiv
          </Button>
        }
      />

      <Card>
        <CardContent className="p-4">
          <form className="grid gap-3 xl:grid-cols-[minmax(260px,1fr)_180px_180px_auto_auto]" onSubmit={applyFilters} aria-label="论文检索筛选">
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
