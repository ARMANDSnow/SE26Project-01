import { CalendarDays } from "lucide-react"
import { Link } from "react-router"
import type { ResearchProjectArtifact, ResearchTimeline } from "@/types"
import { ArtifactState, CitationLabels } from "./artifact-state"

function eventDate(event: ResearchTimeline["events"][number]) {
  if (event.date) return event.date
  if (event.date_range?.start || event.date_range?.end) return [event.date_range.start, event.date_range.end].filter(Boolean).join(" – ")
  return "日期未确定"
}

export function TimelineView({ projectId, artifact }: { projectId: string; artifact?: ResearchProjectArtifact<ResearchTimeline> | null }) {
  const content = artifact?.content
  return <section aria-labelledby="project-timeline-heading">
    <div className="mb-4"><h2 id="project-timeline-heading" className="text-lg font-semibold">研究时间线</h2><p className="mt-1 text-sm text-muted-foreground">发布日期表示时间排序；提出、改进、反驳等演进描述必须有引用依据。</p></div>
    <ArtifactState artifact={artifact} empty="尚未生成研究时间线。">
      <ol className="grid gap-3">
        {(content?.events ?? []).map((event) => (
          <li key={event.event_id} className="grid min-w-0 gap-3 rounded-xl border p-4 sm:grid-cols-[9rem_minmax(0,1fr)]">
            <div className="flex items-start gap-2 text-sm text-muted-foreground"><CalendarDays className="mt-0.5 size-4 shrink-0" /><time className="break-words">{eventDate(event)}</time></div>
            <article className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="break-words font-semibold [overflow-wrap:anywhere]">{event.title}</h3><span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{event.event_type}</span></div><p className="mt-2 break-words text-sm leading-6 [overflow-wrap:anywhere]">{event.description}</p><div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>置信度 {Math.round(event.confidence * 100)}%</span>{event.paper_ids.map((paperId) => <Link key={paperId} to={`/papers/${paperId}`} className="inline-flex min-h-11 items-center rounded-lg border px-3 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">论文 {paperId}</Link>)}<CitationLabels keys={event.citation_keys} /></div>{!event.citation_keys.length ? <p className="mt-2 text-xs text-muted-foreground">仅表达已验证元数据中的时间位置。</p> : null}</article>
          </li>
        ))}
      </ol>
      {content?.unresolved_questions.length ? <section className="mt-4 rounded-xl border border-dashed p-4"><h3 className="font-semibold">尚未解决的问题</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{content.unresolved_questions.map((question) => <li key={question} className="break-words">{question}</li>)}</ul></section> : null}
    </ArtifactState>
    <span className="sr-only">项目 {projectId}</span>
  </section>
}
