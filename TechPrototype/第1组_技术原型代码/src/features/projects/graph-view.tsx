import { useMemo, useRef, useState, type MouseEvent } from "react"
import { ExternalLink, GitBranch, Quote } from "lucide-react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import { CitationEvidenceInspector } from "@/components/research/citation-evidence-inspector"
import type { ResearchGraph, ResearchGraphEdge, ResearchGraphNode, ResearchProjectArtifact } from "@/types"
import { ArtifactState } from "./artifact-state"

const nodeTypeLabel: Record<ResearchGraphNode["node_type"], string> = {
  project: "项目", run: "调研任务", paper: "论文", report: "报告", topic_cluster: "主题簇", synthesis_claim: "研究主张",
}
const edgeTypeLabel: Record<ResearchGraphEdge["relation_type"], string> = {
  contains: "包含", generated_from: "生成自", cites: "引用", supports: "支持", contradicts: "反驳", belongs_to_cluster: "属于主题簇", precedes: "时间先后", influences: "影响",
}
const deterministicEdgeTypes = new Set<ResearchGraphEdge["relation_type"]>(["contains", "generated_from", "cites", "precedes"])

function nodeHref(projectId: string, node: ResearchGraphNode) {
  if (node.status === "inaccessible") return null
  const reference = node.entity_ref.split(":")
  if (node.node_type === "project") return `/library/projects/${projectId}`
  if (node.node_type === "run" && reference.length > 1) return `/runs/${reference.slice(1).join(":")}`
  if (node.node_type === "paper" && Number(reference[1]) > 0) return `/papers/${Number(reference[1])}`
  if (node.node_type === "report" && reference[1] && Number(reference[2]) > 0) return `/runs/${reference[1]}/reports/${Number(reference[2])}`
  return null
}

function graphLayout(nodes: ResearchGraphNode[]) {
  const groups = new Map<ResearchGraphNode["node_type"], ResearchGraphNode[]>()
  for (const node of nodes) groups.set(node.node_type, [...(groups.get(node.node_type) ?? []), node])
  const order: ResearchGraphNode["node_type"][] = ["project", "run", "paper", "report", "topic_cluster", "synthesis_claim"]
  const positions = new Map<string, { x: number; y: number }>()
  order.forEach((type, column) => (groups.get(type) ?? []).forEach((node, row) => positions.set(node.node_id, { x: 20 + column * 190, y: 24 + row * 82 })))
  const rows = Math.max(1, ...Array.from(groups.values(), (items) => items.length))
  return { positions, width: 1160, height: Math.max(260, rows * 82 + 40) }
}

export function GraphView({ projectId, artifact }: { projectId: string; artifact?: ResearchProjectArtifact<ResearchGraph> | null }) {
  const [selectedNodeId, setSelectedNodeId] = useState("")
  const [selectedEdgeId, setSelectedEdgeId] = useState("")
  const [showFullGraph, setShowFullGraph] = useState(false)
  const [showAllNodes, setShowAllNodes] = useState(false)
  const [showAllEdges, setShowAllEdges] = useState(false)
  const evidenceOpener = useRef<HTMLElement | SVGElement | null>(null)
  const content = artifact?.content
  const accessibleNodes = useMemo(() => (content?.nodes ?? []).filter((node) => node.status !== "inaccessible"), [content?.nodes])
  const accessibleEdges = useMemo(() => (content?.edges ?? []).filter((edge) => edge.status !== "inaccessible"), [content?.edges])
  const highlightedIds = useMemo(() => {
    const ids = new Set(accessibleNodes.filter((node) => ["project", "run", "report"].includes(node.node_type)).map((node) => node.node_id))
    for (const edge of accessibleEdges) if (!deterministicEdgeTypes.has(edge.relation_type)) { ids.add(edge.source_node_id); ids.add(edge.target_node_id) }
    return ids
  }, [accessibleEdges, accessibleNodes])
  const canvasNodes = useMemo(() => showFullGraph ? accessibleNodes : accessibleNodes.filter((node) => highlightedIds.has(node.node_id)), [accessibleNodes, highlightedIds, showFullGraph])
  const canvasIds = useMemo(() => new Set(canvasNodes.map((node) => node.node_id)), [canvasNodes])
  const canvasEdges = useMemo(() => accessibleEdges.filter((edge) => canvasIds.has(edge.source_node_id) && canvasIds.has(edge.target_node_id)), [accessibleEdges, canvasIds])
  const layout = useMemo(() => graphLayout(canvasNodes), [canvasNodes])
  const priorityNodes = (content?.nodes ?? []).filter((node) => node.status === "inaccessible" || highlightedIds.has(node.node_id))
  const priorityEdges = (content?.edges ?? []).filter((edge) => edge.status === "inaccessible" || !deterministicEdgeTypes.has(edge.relation_type) || (canvasIds.has(edge.source_node_id) && canvasIds.has(edge.target_node_id)))
  const listedNodes = showAllNodes ? (content?.nodes ?? []) : priorityNodes.slice(0, 8)
  const listedEdges = showAllEdges ? (content?.edges ?? []) : priorityEdges.slice(0, 8)
  const selectedNode = content?.nodes.find((node) => node.node_id === selectedNodeId)
  const selectedEdge = content?.edges.find((edge) => edge.edge_id === selectedEdgeId)
  const openEvidence = (edge: ResearchGraphEdge, opener: HTMLElement | SVGElement) => { evidenceOpener.current = opener; setSelectedEdgeId(edge.edge_id) }

  return <section aria-labelledby="project-graph-heading">
    <div className="mb-4"><h2 id="project-graph-heading" className="text-lg font-semibold">研究关系图</h2><p className="mt-1 text-sm text-muted-foreground">确定性关系来自项目数据；语义关系必须能打开引用与原文证据。</p></div>
    <ArtifactState artifact={artifact} empty="尚未生成研究关系图。">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><p className="text-xs text-muted-foreground">默认聚焦有 Citation 依据的语义网络，完整图仍可审计。</p><Button type="button" variant="outline" className="min-h-11" aria-expanded={showFullGraph} aria-controls="project-graph-canvas" onClick={() => setShowFullGraph((value) => !value)}>{showFullGraph ? "只看重点关系" : "查看完整关系图"}</Button></div>
      <div className="hidden min-w-0 gap-4 md:grid xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 overflow-hidden rounded-xl border bg-muted/20 p-2">
          <svg id="project-graph-canvas" viewBox={`0 0 ${layout.width} ${layout.height}`} className="block h-auto max-h-[68vh] min-h-[420px] w-full" role="group" aria-label="可交互研究关系图">
            {canvasEdges.map((edge) => {
              const source = layout.positions.get(edge.source_node_id ?? "")
              const target = layout.positions.get(edge.target_node_id ?? "")
              if (!source || !target) return null
              const selected = selectedEdgeId === edge.edge_id
              const deterministic = deterministicEdgeTypes.has(edge.relation_type)
              const label = `${edgeTypeLabel[edge.relation_type]}${deterministic ? "，系统确定关系" : "，有引用依据"}`
              return <g key={edge.edge_id}><line x1={source.x + 160} y1={source.y + 28} x2={target.x} y2={target.y + 28} stroke="currentColor" strokeWidth={selected ? 4 : 1.5} className={selected ? "text-primary" : "text-border"} /><line x1={source.x + 160} y1={source.y + 28} x2={target.x} y2={target.y + 28} stroke="transparent" strokeWidth="18" role="button" tabIndex={0} aria-label={label} onClick={(event) => openEvidence(edge, event.currentTarget)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openEvidence(edge, event.currentTarget) } }}><title>{label}</title></line></g>
            })}
            {canvasNodes.map((node) => {
              const position = layout.positions.get(node.node_id)!
              const selected = selectedNodeId === node.node_id
              return <foreignObject key={node.node_id} x={position.x} y={position.y} width="160" height="58"><button type="button" aria-pressed={selected} onClick={() => setSelectedNodeId(node.node_id)} className={`flex h-14 w-full min-w-0 flex-col justify-center rounded-xl border bg-card px-3 text-left text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? "border-primary" : ""}`}><span className="text-[10px] text-muted-foreground">{nodeTypeLabel[node.node_type]}</span><span className="line-clamp-2 break-words font-medium [overflow-wrap:anywhere]">{node.label || "未命名节点"}</span></button></foreignObject>
            })}
          </svg>
        </div>
        <aside className="min-w-0 rounded-xl border p-4" aria-live="polite">
          {selectedNode ? <NodeDetail projectId={projectId} node={selectedNode} /> : selectedEdge ? <EdgeDetail edge={selectedEdge} onEvidence={(event) => openEvidence(selectedEdge, event.currentTarget)} /> : <div className="text-sm text-muted-foreground"><GitBranch className="mb-2 size-5" />选择节点或关系查看详情。所有关系也可通过下方列表操作。</div>}
        </aside>
      </div>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section><h3 className="mb-2 font-semibold">节点列表</h3><div id="project-graph-node-list" className="grid gap-2">{listedNodes.map((node) => node.status === "inaccessible" ? <div key={node.node_id} className="rounded-xl border border-dashed p-3 text-sm text-muted-foreground">节点不可访问，内容已隐藏。</div> : <button key={node.node_id} type="button" aria-expanded={selectedNodeId === node.node_id} aria-controls="mobile-node-detail" className="min-h-14 min-w-0 rounded-xl border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setSelectedNodeId(node.node_id)}><span className="block text-xs text-muted-foreground">{nodeTypeLabel[node.node_type]}</span><span className="block break-words text-sm font-medium [overflow-wrap:anywhere]">{node.label}</span></button>)}</div>{(content?.nodes.length ?? 0) > 8 ? <Button type="button" variant="outline" className="mt-2 min-h-11" aria-expanded={showAllNodes} aria-controls="project-graph-node-list" onClick={() => setShowAllNodes((value) => !value)}>{showAllNodes ? "收起节点" : `展开全部 ${content?.nodes.length ?? 0} 个节点`}</Button> : null}{selectedNode ? <div id="mobile-node-detail" className="mt-3 rounded-xl border p-4 md:hidden" aria-live="polite"><NodeDetail projectId={projectId} node={selectedNode} /></div> : null}</section>
        <section><h3 className="mb-2 font-semibold">关系列表</h3><div id="project-graph-edge-list" className="grid gap-2">{listedEdges.map((edge) => { const deterministic = deterministicEdgeTypes.has(edge.relation_type); return edge.status === "inaccessible" ? <div key={edge.edge_id} className="rounded-xl border border-dashed p-3 text-sm text-muted-foreground">关系不可访问，端点与类型已隐藏。</div> : <button key={edge.edge_id} type="button" className="min-h-14 min-w-0 rounded-xl border p-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={(event) => openEvidence(edge, event.currentTarget)}><span className="block break-words text-sm font-medium">{edgeTypeLabel[edge.relation_type]}</span><span className="mt-1 block text-xs text-muted-foreground">{deterministic ? "系统确定关系" : `有 ${edge.citation_keys.length} 条引用依据`}</span></button> })}</div>{(content?.edges.length ?? 0) > 8 ? <Button type="button" variant="outline" className="mt-2 min-h-11" aria-expanded={showAllEdges} aria-controls="project-graph-edge-list" onClick={() => setShowAllEdges((value) => !value)}>{showAllEdges ? "收起关系" : `展开全部 ${content?.edges.length ?? 0} 条关系`}</Button> : null}</section>
      </div>
    </ArtifactState>
    {artifact ? <CitationEvidenceInspector projectId={projectId} artifactVersion={artifact.version} entityKind="edge" entityId={selectedEdgeId} open={Boolean(selectedEdgeId)} onOpenChange={(open) => { if (!open) { setSelectedEdgeId(""); requestAnimationFrame(() => evidenceOpener.current?.focus()) } }} /> : null}
  </section>
}

function NodeDetail({ projectId, node }: { projectId: string; node: ResearchGraphNode }) {
  const href = nodeHref(projectId, node)
  return <div className="min-w-0"><p className="text-xs text-muted-foreground">{nodeTypeLabel[node.node_type]}</p><h3 className="mt-1 break-words font-semibold [overflow-wrap:anywhere]">{node.label}</h3>{href ? <Button asChild variant="outline" className="mt-4 min-h-11"><Link to={href}>打开详情<ExternalLink className="size-4" /></Link></Button> : null}</div>
}

function EdgeDetail({ edge, onEvidence }: { edge: ResearchGraphEdge; onEvidence: (event: MouseEvent<HTMLButtonElement>) => void }) {
  const deterministic = deterministicEdgeTypes.has(edge.relation_type)
  return <div><p className="text-xs text-muted-foreground">研究关系</p><h3 className="mt-1 font-semibold">{edgeTypeLabel[edge.relation_type]}</h3><p className="mt-2 text-sm text-muted-foreground">{deterministic ? "由项目成员关系或版本关系确定性生成。" : `绑定 ${edge.citation_keys.length} 条当前引用。`}</p><Button variant="outline" className="mt-4 min-h-11" onClick={onEvidence}><Quote className="size-4" />{deterministic ? "查看关系说明" : "查看引用依据"}</Button></div>
}
