import { useMemo, useRef, useState } from "react"
import { ArrowLeft, ListChecks } from "lucide-react"
import { Link } from "react-router"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useResearchRunsQuery } from "@/lib/query-hooks"
import { useResearchRunLiveQuery } from "./use-research-run-stream"
import type { ResearchRun } from "@/types"
import { researchStatusLabel, researchStatusTone } from "./status"
import { WorkflowPanel } from "./workflow-panel"

const groups = [
  { key: "waiting", label: "等待确认", statuses: ["waiting_input"] },
  { key: "active", label: "执行中与暂停", statuses: ["queued", "running", "cancelling", "paused"] },
  { key: "completed", label: "已完成", statuses: ["completed"] },
  { key: "failed", label: "失败与取消", statuses: ["failed", "cancelled"] },
] as const

function RunButton({ run, onSelect }: { run: ResearchRun; onSelect: () => void }) {
  return <button type="button" onClick={onSelect} className="flex min-h-14 w-full items-center gap-3 rounded-lg border px-3 py-2 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="min-w-0 flex-1"><span className="line-clamp-2 block text-sm font-medium">{run.title}</span><span className="mt-1 block font-mono text-[11px] text-muted-foreground">{run.id.slice(0, 8)}</span></span><Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge></button>
}

export function TaskCenter() {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [selectedId, setSelectedId] = useState("")
  const runsQuery = useResearchRunsQuery()
  const selectedQuery = useResearchRunLiveQuery(selectedId)
  const waitingCount = runsQuery.data?.filter((run) => run.status === "waiting_input").length ?? 0
  const activeCount = runsQuery.data?.filter((run) => ["queued", "running", "cancelling"].includes(run.status)).length ?? 0
  const grouped = useMemo(() => groups.map((group) => ({ ...group, runs: (runsQuery.data ?? []).filter((run) => (group.statuses as readonly string[]).includes(run.status)) })), [runsQuery.data])
  return (
    <Sheet open={open} onOpenChange={(next) => { setOpen(next); if (!next) { setSelectedId(""); requestAnimationFrame(() => triggerRef.current?.focus()) } }}>
      <SheetTrigger asChild><Button ref={triggerRef} variant="outline" size="icon" className="relative size-11" aria-label={`打开任务中心，${waitingCount} 个等待确认，${activeCount} 个执行中`}><ListChecks className="size-4" />{waitingCount || activeCount ? <span className="absolute -right-1 -top-1 grid min-h-5 min-w-5 place-items-center rounded-full bg-primary px-1 text-[11px] font-semibold text-primary-foreground">{waitingCount || activeCount}</span> : null}</Button></SheetTrigger>
      <SheetContent className="w-full gap-0 overflow-hidden p-0 sm:max-w-md">
        {selectedQuery.data ? (
          <div className="flex min-h-0 flex-1 flex-col"><div className="flex items-center justify-between border-b p-2 pr-14"><Button variant="ghost" className="min-h-11" onClick={() => setSelectedId("")}><ArrowLeft className="size-4" />返回任务中心</Button><Button asChild size="sm" variant="outline" className="min-h-11"><Link to={`/runs/${selectedId}`} onClick={() => setOpen(false)}>完整页面</Link></Button></div><WorkflowPanel run={selectedQuery.data} compact /></div>
        ) : (
          <><SheetHeader className="border-b pr-14"><SheetTitle>任务中心</SheetTitle><SheetDescription>轻量读取历史 Run；只为当前展开任务读取快照。</SheetDescription></SheetHeader><div className="grid gap-5 overflow-y-auto p-4">{runsQuery.isLoading ? <p className="text-sm text-muted-foreground">正在读取任务…</p> : null}{runsQuery.isError ? <div role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">任务列表读取失败。<Button size="sm" variant="outline" className="mt-2 max-md:min-h-11" onClick={() => runsQuery.refetch()}>重试</Button></div> : grouped.map((group) => <section key={group.key} aria-labelledby={`task-group-${group.key}`}><div className="mb-2 flex items-center justify-between"><h2 id={`task-group-${group.key}`} className="text-sm font-semibold">{group.label}</h2><span className="font-mono text-xs text-muted-foreground">{group.runs.length}</span></div><div className="grid gap-2">{group.runs.length ? group.runs.map((run) => <RunButton key={run.id} run={run} onSelect={() => setSelectedId(run.id)} />) : <p className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground">暂无任务</p>}</div></section>)}</div></>
        )}
      </SheetContent>
    </Sheet>
  )
}
