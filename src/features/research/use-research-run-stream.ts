import { useEffect, useRef } from "react"
import { type QueryClient, useQueryClient } from "@tanstack/react-query"
import { API_BASE } from "@/api"
import { queryKeys, useResearchRunQuery } from "@/lib/query-hooks"

const terminalStatuses = new Set(["completed", "failed", "cancelled"])
const eventTypes = [
  "run.created", "run.pause_requested", "run.cancel_requested", "run.resumed", "run.retried",
  "run.paused", "run.cancelled", "run.completed", "run.failed", "step.started",
  "step.completed", "step.lease_recovered", "decision.requested", "decision.resolved",
  "artifact.created", "paper.updated",
]
type SharedStream = { source: EventSource; refs: number; cursor: number; timer?: number; handler: EventListener }
const sharedStreams = new Map<string, SharedStream>()

function subscribe(runId: string, cursor: number, queryClient: QueryClient) {
  const existing = sharedStreams.get(runId)
  if (existing) {
    existing.refs += 1
    existing.cursor = Math.max(existing.cursor, cursor)
    return () => release(runId)
  }
  const source = new EventSource(`${API_BASE}/api/research/runs/${encodeURIComponent(runId)}/events?after=${cursor}`, { withCredentials: true })
  const stream: SharedStream = { source, refs: 1, cursor, handler: (() => undefined) as EventListener }
  stream.handler = ((event: MessageEvent) => {
    const eventId = Number(event.lastEventId)
    if (!Number.isFinite(eventId) || eventId <= stream.cursor) return
    stream.cursor = eventId
    window.clearTimeout(stream.timer)
    stream.timer = window.setTimeout(() => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchRun(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchArtifacts(runId) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.researchRunPapers(runId) })
    }, 150)
  }) as EventListener
  eventTypes.forEach((eventType) => source.addEventListener(eventType, stream.handler))
  sharedStreams.set(runId, stream)
  return () => release(runId)
}

function release(runId: string) {
  const stream = sharedStreams.get(runId)
  if (!stream) return
  stream.refs -= 1
  if (stream.refs > 0) return
  window.clearTimeout(stream.timer)
  eventTypes.forEach((eventType) => stream.source.removeEventListener(eventType, stream.handler))
  stream.source.close()
  sharedStreams.delete(runId)
}

export function useResearchRunLiveQuery(runId: string) {
  const query = useResearchRunQuery(runId)
  const queryClient = useQueryClient()
  const cursorRef = useRef(0)
  useEffect(() => { cursorRef.current = Math.max(cursorRef.current, query.data?.latest_event_id ?? 0) }, [query.data?.latest_event_id])
  const active = Boolean(query.data && !terminalStatuses.has(query.data.status))
  useEffect(() => {
    if (!runId || !active) return
    return subscribe(runId, cursorRef.current, queryClient)
  }, [active, queryClient, runId])
  return query
}
