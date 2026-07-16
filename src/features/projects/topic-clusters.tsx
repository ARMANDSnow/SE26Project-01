import { Layers3 } from "lucide-react"
import { Link } from "react-router"
import type { ResearchProjectArtifact, TopicClusters } from "@/types"
import { ArtifactState, CitationLabels } from "./artifact-state"

export function TopicClustersView({ projectId, artifact }: { projectId: string; artifact?: ResearchProjectArtifact<TopicClusters> | null }) {
  const content = artifact?.content
  return <section aria-labelledby="project-clusters-heading">
    <div className="mb-4"><h2 id="project-clusters-heading" className="text-lg font-semibold">主题簇</h2><p className="mt-1 text-sm text-muted-foreground">论文可属于多个主题；依据不足的论文单独列出，不强行归类。</p></div>
    <ArtifactState artifact={artifact} empty="尚未生成主题簇。完成项目分析后会在这里显示。">
      <div className="grid gap-3 lg:grid-cols-2">
        {(content?.clusters ?? []).map((cluster) => (
          <article key={cluster.cluster_id} className="min-w-0 rounded-xl border p-4">
            <div className="flex min-w-0 items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-lg bg-muted"><Layers3 className="size-4" /></span><div className="min-w-0 flex-1"><h3 className="break-words font-semibold [overflow-wrap:anywhere]">{cluster.label}</h3><p className="mt-1 text-xs text-muted-foreground">{cluster.paper_ids.length} 篇论文 · {cluster.claim_ids.length} 条主张</p></div></div>
            <p className="mt-3 break-words text-sm leading-6 [overflow-wrap:anywhere]">{cluster.summary}</p>
            <div className="mt-3 flex flex-wrap gap-2">{cluster.paper_ids.map((paperId) => <Link key={paperId} to={`/papers/${paperId}`} className="inline-flex min-h-11 items-center rounded-lg border px-3 text-xs hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">打开论文 {paperId}</Link>)}{cluster.claim_ids.map((claimId, index) => <span key={claimId} className="inline-flex min-h-11 items-center rounded-lg bg-muted px-3 text-xs">研究主张 {index + 1}</span>)}</div>
            {cluster.distinguishing_features.length ? <div className="mt-3"><h4 className="text-xs font-semibold">区分特征</h4><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{cluster.distinguishing_features.map((feature) => <li key={feature.statement_id} className="break-words">{feature.text} <CitationLabels keys={feature.citation_keys} /></li>)}</ul></div> : null}
            {cluster.uncertainties.length ? <div className="mt-3"><h4 className="text-xs font-semibold">不确定项</h4><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{cluster.uncertainties.map((item) => <li key={item} className="break-words">{item}</li>)}</ul></div> : null}
            <div className="mt-3"><CitationLabels keys={cluster.citation_keys} /></div>
          </article>
        ))}
      </div>
      {content?.unclassified_paper_ids.length ? <section className="mt-4 rounded-xl border border-dashed p-4"><h3 className="font-semibold">依据不足 / 未分类</h3><p className="mt-1 break-words text-sm text-muted-foreground">论文 {content.unclassified_paper_ids.join("、")} 暂无足够的有效引用支持稳定归类。</p></section> : null}
    </ArtifactState>
    <span className="sr-only">项目 {projectId}</span>
  </section>
}
