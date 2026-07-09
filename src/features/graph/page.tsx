import { Network, Search } from "lucide-react"
import { FormEvent, KeyboardEvent, useEffect, useMemo, useState } from "react"
import { useNavigate, useSearchParams } from "react-router"
import { PageHeader } from "@/components/common/page-header"
import { LoadingState } from "@/components/common/loading-state"
import { AppEmptyState } from "@/components/common/empty-state"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { truncateLabel } from "@/lib/format"
import { useGraphQuery } from "@/lib/query-hooks"
import type { GraphData, GraphNode } from "@/types"

function graphNodeLabel(node: GraphNode) {
  return node.type === "paper" ? truncateLabel(node.label, 18) : truncateLabel(node.label, 22)
}

function useGraphLayout(graph?: GraphData) {
  return useMemo(() => {
    const nodes = graph?.nodes ?? []
    const centerX = 460
    const centerY = 270
    const conceptNodes = nodes.filter((node) => node.type === "concept")
    const paperNodes = nodes.filter((node) => node.type === "paper")
    const positions = new Map<string, { x: number; y: number }>()

    conceptNodes.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(conceptNodes.length, 1)
      positions.set(node.id, { x: centerX + Math.cos(angle) * 185, y: centerY + Math.sin(angle) * 138 })
    })

    paperNodes.forEach((node, index) => {
      const angle = (Math.PI * 2 * index) / Math.max(paperNodes.length, 1) + Math.PI / 8
      positions.set(node.id, { x: centerX + Math.cos(angle) * 320, y: centerY + Math.sin(angle) * 215 })
    })

    return positions
  }, [graph])
}

export function GraphPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const topicFromUrl = searchParams.get("topic") || "RAG"
  const [topic, setTopic] = useState(topicFromUrl)
  const graphQuery = useGraphQuery(topicFromUrl)
  const graph = graphQuery.data
  const layout = useGraphLayout(graph)

  useEffect(() => {
    setTopic(topicFromUrl)
  }, [topicFromUrl])

  const applyTopic = (event: FormEvent) => {
    event.preventDefault()
    const next = new URLSearchParams()
    if (topic.trim()) next.set("topic", topic.trim())
    setSearchParams(next)
  }

  const openPaperNode = (node: GraphNode) => {
    if (node.type === "paper") navigate(`/papers/${node.id.replace("p-", "")}`)
  }

  const onNodeKeyDown = (event: KeyboardEvent<SVGGElement>, node: GraphNode) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      openPaperNode(node)
    }
  }

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="论文概念可视化"
        title="知识图谱"
        description="查看主题、概念和论文之间的关联，并从论文节点回到阅读页。"
        actions={
          <form className="flex flex-wrap items-end gap-2" onSubmit={applyTopic}>
            <div className="grid gap-2">
              <Label htmlFor="graph-topic">研究主题</Label>
              <Input
                id="graph-topic"
                className="h-11 w-48"
                value={topic}
                onChange={(event) => setTopic(event.target.value)}
                placeholder="研究主题"
              />
            </div>
            <Button variant="outline" className="h-11" disabled={graphQuery.isFetching}>
              <Search className="size-4" />
              刷新
            </Button>
          </form>
        }
      />

      {graphQuery.isError ? (
        <Alert variant="destructive">
          <AlertTitle>知识图谱加载失败</AlertTitle>
          <AlertDescription>请稍后重试，或确认后端服务是否运行。</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Card className="overflow-hidden">
          <CardContent className="p-0">
            {graphQuery.isLoading ? (
              <LoadingState label="正在加载知识图谱" className="min-h-[520px]" />
            ) : graph?.nodes.length ? (
              <div className="p-3" aria-busy={graphQuery.isFetching}>
                <svg
                  viewBox="-50 -30 1020 610"
                  preserveAspectRatio="xMidYMid meet"
                  role="img"
                  aria-label={`论文概念知识图谱，主题 ${topicFromUrl}`}
                  className="min-h-[420px] w-full"
                >
                  {(graph?.links ?? []).map((link, index) => {
                    const source = layout.get(link.source)
                    const target = layout.get(link.target)
                    if (!source || !target) return null
                    return (
                      <line
                        key={`${link.source}-${link.target}-${index}`}
                        x1={source.x}
                        y1={source.y}
                        x2={target.x}
                        y2={target.y}
                        className="stroke-muted-foreground/40"
                        strokeWidth="1.6"
                      />
                    )
                  })}
                  {(graph?.nodes ?? []).map((node) => {
                    const position = layout.get(node.id)
                    if (!position) return null
                    const radius = node.type === "concept" ? Math.min(34, 18 + node.weight * 1.15) : 15
                    const isPaper = node.type === "paper"
                    return (
                      <g
                        key={node.id}
                        className={isPaper ? "cursor-pointer outline-none" : "outline-none"}
                        onClick={() => openPaperNode(node)}
                        onKeyDown={(event) => onNodeKeyDown(event, node)}
                        role={isPaper ? "button" : "img"}
                        tabIndex={isPaper ? 0 : undefined}
                        aria-label={node.label}
                      >
                        <title>{node.label}</title>
                        <circle
                          cx={position.x}
                          cy={position.y}
                          r={radius}
                          className={isPaper ? "fill-[var(--chart-2)] stroke-background" : "fill-primary stroke-background"}
                          strokeWidth="2"
                        />
                        <text
                          x={position.x}
                          y={position.y + radius + 18}
                          className="fill-foreground text-[12px] font-semibold"
                          textAnchor="middle"
                          pointerEvents="none"
                        >
                          {graphNodeLabel(node)}
                        </text>
                      </g>
                    )
                  })}
                </svg>
              </div>
            ) : (
              <AppEmptyState title="暂无知识图谱数据" description="尝试更换主题或先结构化解析论文。" />
            )}
          </CardContent>
        </Card>

        <aside className="grid content-start gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="inline-flex items-center gap-2 text-lg">
                <Network className="size-4" />
                图例
              </CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-2">
                <i className="size-3 rounded-full bg-primary" />
                概念节点
              </span>
              <span className="inline-flex items-center gap-2">
                <i className="size-3 rounded-full bg-[var(--chart-2)]" />
                论文节点
              </span>
              <span className="inline-flex items-center gap-2">
                <i className="h-0.5 w-6 bg-muted-foreground/40" />
                关联边
              </span>
            </CardContent>
          </Card>

          <div className="grid grid-cols-2 gap-3">
            <Card>
              <CardContent className="grid min-h-24 gap-1 p-4">
                <span className="text-xs font-semibold text-muted-foreground">节点</span>
                <strong className="text-3xl font-semibold tabular-nums">{graph?.nodes.length ?? 0}</strong>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="grid min-h-24 gap-1 p-4">
                <span className="text-xs font-semibold text-muted-foreground">关系</span>
                <strong className="text-3xl font-semibold tabular-nums">{graph?.links.length ?? 0}</strong>
              </CardContent>
            </Card>
          </div>

          <Badge variant="secondary" className="w-fit rounded-full">
            当前主题：{topicFromUrl}
          </Badge>
        </aside>
      </div>
    </section>
  )
}
