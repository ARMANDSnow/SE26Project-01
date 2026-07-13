import { Clock3, Columns3, History, Loader2, Plus, Rss, Star } from "lucide-react"
import { FormEvent, useEffect, useMemo, useState } from "react"
import { Link } from "react-router"
import { toast } from "sonner"
import { PageHeader } from "@/components/common/page-header"
import { LoadingState } from "@/components/common/loading-state"
import { AppEmptyState } from "@/components/common/empty-state"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { uniqueValues } from "@/lib/format"
import { useAddSubscriptionMutation, useHistoryQuery, usePapersQuery, useSubscriptionsQuery } from "@/lib/query-hooks"
import type { Paper } from "@/types"

function CompareColumn({ paper }: { paper?: Paper }) {
  if (!paper) {
    return <AppEmptyState title="暂无可对比论文" />
  }

  return (
    <article className="grid min-h-64 content-start gap-3 rounded-lg border bg-background p-4">
      <Badge className="w-fit rounded-full bg-primary/10 text-primary hover:bg-primary/10">{paper.primary_category}</Badge>
      <h3 className="text-base font-semibold leading-6">{paper.title}</h3>
      <p className="line-clamp-5 text-sm leading-6 text-muted-foreground">{paper.abstract}</p>
      <div className="flex flex-wrap gap-1.5">
        {uniqueValues(paper.categories).map((item) => (
          <Badge key={`${paper.id}-${item}`} variant="secondary" className="rounded-full">
            {item}
          </Badge>
        ))}
      </div>
    </article>
  )
}

export function LearningPage() {
  const favoritesQuery = usePapersQuery({ favorite: true, limit: 40 })
  const historyQuery = useHistoryQuery()
  const subscriptionsQuery = useSubscriptionsQuery()
  const addSubscriptionMutation = useAddSubscriptionMutation()
  const favorites = useMemo(() => favoritesQuery.data ?? [], [favoritesQuery.data])
  const history = historyQuery.data ?? []
  const subscriptions = subscriptionsQuery.data ?? []
  const [leftId, setLeftId] = useState<number | null>(null)
  const [rightId, setRightId] = useState<number | null>(null)
  const [topic, setTopic] = useState("")

  useEffect(() => {
    if (!favorites.length) return
    setLeftId((current) => current ?? favorites[0]?.id ?? null)
    setRightId((current) => current ?? favorites[1]?.id ?? favorites[0]?.id ?? null)
  }, [favorites])

  const left = favorites.find((paper) => paper.id === leftId)
  const right = favorites.find((paper) => paper.id === rightId)
  const latestHistory = history[0]
  const loading = favoritesQuery.isLoading || historyQuery.isLoading || subscriptionsQuery.isLoading

  const onSubmitTopic = async (event: FormEvent) => {
    event.preventDefault()
    const nextTopic = topic.trim()
    if (!nextTopic) return
    try {
      await addSubscriptionMutation.mutateAsync({ topic: nextTopic })
      setTopic("")
      toast.success("关注主题已保存。")
    } catch {
      toast.error("关注主题保存失败，请稍后重试。")
    }
  }

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="收藏、笔记、历史与对比阅读"
        title="学习管理"
        description="把已收藏论文、阅读历史和对比阅读放到同一条学习链路中。"
      />

      {loading ? (
        <LoadingState label="正在加载学习记录" skeleton />
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.8fr)_minmax(320px,0.85fr)]">
            <Card>
              <CardHeader>
                <CardTitle className="inline-flex items-center gap-2 text-lg">
                  <History className="size-4" />
                  继续阅读
                </CardTitle>
              </CardHeader>
              <CardContent>
                {latestHistory ? (
                  <Link
                    to={`/papers/${latestHistory.paper_id}`}
                    className="grid min-h-32 content-center gap-2 rounded-lg border bg-background p-4 transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="text-xs font-medium text-muted-foreground">{latestHistory.action}</span>
                    <strong className="line-clamp-2">{latestHistory.title}</strong>
                    <small className="text-xs text-muted-foreground">
                      {latestHistory.created_at} · {latestHistory.primary_category}
                    </small>
                  </Link>
                ) : (
                  <AppEmptyState title="暂无阅读历史" />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-3">
                <CardTitle className="inline-flex items-center gap-2 text-lg">
                  <Star className="size-4" />
                  收藏论文
                </CardTitle>
                <Badge variant="secondary" className="rounded-full">
                  {favorites.length} 篇
                </Badge>
              </CardHeader>
              <CardContent className="grid gap-2">
                {favorites.slice(0, 8).map((paper) => (
                  <Link
                    key={paper.id}
                    to={`/papers/${paper.id}`}
                    className="grid min-h-16 gap-1 rounded-lg border bg-background p-3 transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <strong className="line-clamp-1 text-sm">{paper.title}</strong>
                    <span className="text-xs text-muted-foreground">
                      {paper.primary_category} · {paper.published_at}
                    </span>
                  </Link>
                ))}
                {!favorites.length ? <AppEmptyState title="暂无收藏论文" /> : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-3">
                <CardTitle className="inline-flex items-center gap-2 text-lg">
                  <Rss className="size-4" />
                  关注主题
                </CardTitle>
                <Badge variant="secondary" className="rounded-full">
                  {subscriptions.length} 个
                </Badge>
              </CardHeader>
              <CardContent className="grid gap-4">
                <form className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={onSubmitTopic}>
                  <div className="grid gap-2">
                    <Label htmlFor="subscription-topic">研究主题</Label>
                    <Input
                      id="subscription-topic"
                      className="h-11"
                      value={topic}
                      onChange={(event) => setTopic(event.target.value)}
                      placeholder="RAG、知识图谱、长上下文"
                    />
                  </div>
                  <Button className="h-11 self-end" disabled={addSubscriptionMutation.isPending || !topic.trim()}>
                    {addSubscriptionMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
                    关注
                  </Button>
                </form>

                <div className="flex flex-wrap gap-2">
                  {subscriptions.map((item) => (
                    <Badge key={item.id} variant="secondary" className="rounded-full">
                      {item.topic}
                    </Badge>
                  ))}
                  {!subscriptions.length ? <AppEmptyState title="暂无关注主题" /> : null}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <Card>
              <CardHeader>
                <CardTitle className="inline-flex items-center gap-2 text-lg">
                  <Clock3 className="size-4" />
                  阅读历史
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-2">
                {history.map((item) => (
                  <Link
                    key={item.id}
                    to={`/papers/${item.paper_id}`}
                    className="grid min-h-16 gap-1 rounded-lg border bg-background p-3 transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="text-xs text-muted-foreground">{item.action}</span>
                    <strong className="line-clamp-1 text-sm">{item.title}</strong>
                    <small className="text-xs text-muted-foreground">{item.created_at}</small>
                  </Link>
                ))}
                {!history.length ? <AppEmptyState title="暂无历史记录" /> : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="inline-flex items-center gap-2 text-lg">
                  <Columns3 className="size-4" />
                  对比阅读
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="grid gap-2 md:grid-cols-2">
                  <Select value={leftId ? String(leftId) : ""} onValueChange={(value) => setLeftId(Number(value))} disabled={!favorites.length}>
                    <SelectTrigger className="h-11 w-full">
                      <SelectValue placeholder="选择左侧论文" />
                    </SelectTrigger>
                    <SelectContent>
                      {favorites.map((paper) => (
                        <SelectItem key={paper.id} value={String(paper.id)}>
                          {paper.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={rightId ? String(rightId) : ""} onValueChange={(value) => setRightId(Number(value))} disabled={!favorites.length}>
                    <SelectTrigger className="h-11 w-full">
                      <SelectValue placeholder="选择右侧论文" />
                    </SelectTrigger>
                    <SelectContent>
                      {favorites.map((paper) => (
                        <SelectItem key={paper.id} value={String(paper.id)}>
                          {paper.title}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  <CompareColumn paper={left} />
                  <CompareColumn paper={right} />
                </div>
                {!favorites.length ? (
                  <Button asChild variant="outline" className="h-11 w-fit">
                    <Link to="/papers">去论文库收藏论文</Link>
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </section>
  )
}
