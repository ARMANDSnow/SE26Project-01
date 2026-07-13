import { BarChart3, FileText, GitBranch, MessageSquareText, Search } from "lucide-react"
import { Link } from "react-router"
import { PageHeader } from "@/components/common/page-header"
import { LoadingState } from "@/components/common/loading-state"
import { AppEmptyState } from "@/components/common/empty-state"
import { PaperCard } from "@/components/papers/paper-card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { usePapersQuery, useStatsQuery } from "@/lib/query-hooks"
import { cn } from "@/lib/utils"

const metricTone = {
  teal: "border-l-primary",
  clay: "border-l-[color-mix(in_oklch,var(--primary),var(--foreground)_18%)]",
  ochre: "border-l-[color-mix(in_oklch,var(--primary),var(--background)_18%)]",
  rosewood: "border-l-[color-mix(in_oklch,var(--destructive),var(--primary)_28%)]",
}

function MetricCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: number | string
  detail: string
  tone: keyof typeof metricTone
}) {
  return (
    <Card className={cn("border-l-4", metricTone[tone])}>
      <CardContent className="grid min-h-28 gap-1 p-4">
        <span className="text-xs font-semibold text-muted-foreground">{label}</span>
        <strong className="text-3xl font-semibold tabular-nums text-foreground">{value}</strong>
        <small className="text-xs text-muted-foreground">{detail}</small>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const statsQuery = useStatsQuery()
  const papersQuery = usePapersQuery({ limit: 6 })
  const stats = statsQuery.data
  const papers = papersQuery.data ?? []
  const loading = statsQuery.isLoading || papersQuery.isLoading
  const completion = stats ? Math.round((stats.processed / Math.max(stats.papers, 1)) * 100) : 0

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="科研论文知识工作台"
        title="PaperWiki"
        description="面向 arXiv 论文检索、结构化 Wiki、出处问答和学习管理的研究工作台。"
        actions={
          <>
            <Button asChild variant="outline" className="h-11">
              <Link to="/papers">
                <Search className="size-4" />
                检索论文
              </Link>
            </Button>
            <Button asChild className="h-11">
              <Link to="/qa">
                <MessageSquareText className="size-4" />
                带出处提问
              </Link>
            </Button>
          </>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-busy={loading}>
        <MetricCard label="论文记录" value={stats?.papers ?? "..."} tone="teal" detail="可检索条目" />
        <MetricCard label="已结构化" value={`${completion}%`} tone="clay" detail={`${stats?.processed ?? 0} 篇已解析`} />
        <MetricCard label="概念节点" value={stats?.concepts ?? "..."} tone="ochre" detail="知识图谱节点" />
        <MetricCard label="收藏笔记" value={(stats?.favorites ?? 0) + (stats?.notes ?? 0)} tone="rosewood" detail="学习资产" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.75fr)]">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="inline-flex items-center gap-2 text-lg">
              <BarChart3 className="size-4" />
              主题分布
            </CardTitle>
            <Button asChild variant="link" className="h-11 px-0">
              <Link to="/papers">查看论文库</Link>
            </Button>
          </CardHeader>
          <CardContent className="grid gap-3">
            {statsQuery.isLoading ? <LoadingState label="正在加载主题分布" /> : null}
            {(stats?.categories ?? []).map((item) => (
              <div key={item.category} className="grid grid-cols-[84px_minmax(0,1fr)_40px] items-center gap-3 text-sm">
                <span className="font-medium text-muted-foreground">{item.category}</span>
                <Progress value={Math.min(100, (item.count / Math.max(stats?.papers ?? 1, 1)) * 100)} className="h-2" />
                <strong className="text-right tabular-nums">{item.count}</strong>
              </div>
            ))}
            {!statsQuery.isLoading && !stats?.categories.length ? <AppEmptyState title="暂无主题分布" /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="inline-flex items-center gap-2 text-lg">
              <GitBranch className="size-4" />
              处理流水线
            </CardTitle>
            <Badge className="rounded-full">运行中</Badge>
          </CardHeader>
          <CardContent className="grid gap-2">
            {["FetcherAgent", "ReaderAgent", "SummaryAgent", "ValidatorAgent", "QAAgent"].map((agent, index) => (
              <div key={agent} className="grid min-h-12 grid-cols-[32px_minmax(0,1fr)] items-center gap-3 rounded-lg bg-accent/35 px-3">
                <span className="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
                  {index + 1}
                </span>
                <strong className="truncate text-sm">{agent}</strong>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <section className="grid gap-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h2 className="inline-flex items-center gap-2 text-lg font-semibold">
              <FileText className="size-4" />
              最新论文
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">从检索结果进入详情页，再沉淀 Wiki、笔记和问答证据。</p>
          </div>
          <Button asChild variant="link" className="h-11 px-0">
            <Link to="/papers">全部论文</Link>
          </Button>
        </div>

        {papersQuery.isLoading ? (
          <LoadingState label="正在加载论文" skeleton />
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {papers.slice(0, 6).map((paper) => (
              <PaperCard key={paper.id} paper={paper} compact />
            ))}
          </div>
        )}
      </section>
    </section>
  )
}
