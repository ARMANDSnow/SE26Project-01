import { useState } from "react"
import { CalendarDays } from "lucide-react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import type { ResearchProjectArtifact, ResearchTimeline } from "@/types"
import { ArtifactState, CitationLabels } from "./artifact-state"

function eventDate(event: ResearchTimeline["events"][number]) {
  if (event.date) return event.date
  if (event.date_range?.start || event.date_range?.end) return [event.date_range.start, event.date_range.end].filter(Boolean).join(" – ")
  return "日期未确定"
}

const eventTypeLabel: Record<string, string> = {
  publication: "论文发表",
  proposal: "提出方法",
  improvement: "方法改进",
  contradiction: "反驳",
  turning_point: "关键转折",
}

function eventSortValue(event: ResearchTimeline["events"][number]) {
  return event.date_range?.start ?? event.date ?? event.date_range?.end ?? ""
}

export function TimelineView({ artifact }: { artifact?: ResearchProjectArtifact<ResearchTimeline> | null }) {
  const [showAllEvents, setShowAllEvents] = useState(false)
  const content = artifact?.content
  const events = content?.events ?? []
  const previewEventIds = new Set([
    ...events.filter((event) => event.citation_keys.length > 0).map((event) => event.event_id),
    ...events.filter((event) => event.citation_keys.length === 0).slice(-7).map((event) => event.event_id),
  ])
  const visibleEvents = (showAllEvents ? events : events.filter((event) => previewEventIds.has(event.event_id)))
    .slice()
    .sort((left, right) => eventSortValue(right).localeCompare(eventSortValue(left)))
  return <section aria-labelledby="project-timeline-heading">
    <div className="mb-4"><h2 id="project-timeline-heading" className="text-lg font-semibold">研究时间线</h2><p className="mt-1 text-sm text-muted-foreground">发布日期表示时间排序；提出、改进、反驳等演进描述必须有引用依据。</p></div>
    <ArtifactState artifact={artifact} empty="尚未生成研究时间线。">
      {!showAllEvents && events.length > visibleEvents.length ? <p className="mb-3 text-xs text-muted-foreground">优先展示有引用依据的演进事件与最近 7 条发布日期；其余 {events.length - visibleEvents.length} 条可展开审计。</p> : null}
      <ol id="project-timeline-events" className="grid gap-3">
        {visibleEvents.map((event) => (
          <li key={event.event_id} className="grid min-w-0 gap-3 rounded-xl border p-4 sm:grid-cols-[9rem_minmax(0,1fr)]">
            <div className="flex items-start gap-2 text-sm text-muted-foreground"><CalendarDays className="mt-0.5 size-4 shrink-0" /><time className="break-words">{eventDate(event)}</time></div>
            <article className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="break-words font-semibold [overflow-wrap:anywhere]">{event.title}</h3><span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">{eventTypeLabel[event.event_type] ?? "研究事件"}</span></div><p className="mt-2 break-words text-sm leading-6 [overflow-wrap:anywhere]">{event.description}</p><div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>置信度 {Math.round(event.confidence * 100)}%</span>{event.paper_ids.map((paperId, index) => <Link key={paperId} to={`/papers/${paperId}`} aria-label={`查看该事件关联的第 ${index + 1} 篇论文`} className="inline-flex min-h-11 items-center rounded-lg border px-3 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">查看论文{event.paper_ids.length > 1 ? ` ${index + 1}` : ""}</Link>)}<CitationLabels keys={event.citation_keys} /></div>{!event.citation_keys.length ? <p className="mt-2 text-xs text-muted-foreground">仅表达已验证元数据中的时间位置。</p> : null}</article>
          </li>
        ))}
      </ol>
      {events.length > visibleEvents.length || showAllEvents ? <Button type="button" variant="outline" className="mt-3 min-h-11" aria-expanded={showAllEvents} aria-controls="project-timeline-events" onClick={() => setShowAllEvents((value) => !value)}>{showAllEvents ? "收起完整时间线" : `展开全部 ${events.length} 个事件`}</Button> : null}
      {content?.periods.length ? <section className="mt-4" aria-labelledby="project-periods-heading"><h3 id="project-periods-heading" className="font-semibold">研究阶段</h3><div className="mt-2 grid gap-3 md:grid-cols-2">{content.periods.map((period) => <article key={period.period_id} className="min-w-0 rounded-xl border p-4"><p className="text-xs text-muted-foreground">{period.date_range.start} – {period.date_range.end}</p><h4 className="mt-1 break-words font-semibold [overflow-wrap:anywhere]">{period.title}</h4><p className="mt-2 break-words text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{period.description}</p><CitationLabels keys={period.citation_keys} /></article>)}</div></section> : null}
      {content?.turning_points.length ? <section className="mt-4 rounded-xl border p-4" aria-labelledby="project-turning-points-heading"><h3 id="project-turning-points-heading" className="font-semibold">关键转折</h3><ul className="mt-2 list-disc space-y-2 pl-5 text-sm text-muted-foreground">{content.turning_points.map((point, index) => <li key={`turning-point-${index}`} className="break-words [overflow-wrap:anywhere]">{point.text} <CitationLabels keys={point.citation_keys} /></li>)}</ul></section> : null}
      {content?.unresolved_questions.length ? <section className="mt-4 rounded-xl border border-dashed p-4"><h3 className="font-semibold">尚未解决的问题</h3><ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">{content.unresolved_questions.map((question) => <li key={question} className="break-words">{question}</li>)}</ul></section> : null}
    </ArtifactState>
  </section>
}
