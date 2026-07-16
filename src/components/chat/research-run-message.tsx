import { makeAssistantDataUI } from "@assistant-ui/react"
import { ArrowRight, FlaskConical, Loader2 } from "lucide-react"
import { createContext, useContext } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useResearchRunQuery } from "@/lib/query-hooks"
import { researchStatusLabel, researchStatusTone } from "@/features/research/status"

type ResearchRunUiContextValue = { openRun: (runId: string, opener?: HTMLElement | null) => void }
export const ResearchRunUiContext = createContext<ResearchRunUiContextValue>({ openRun: () => undefined })

function ResearchRunCard({ runId }: { runId: string }) {
  const query = useResearchRunQuery(runId)
  const { openRun } = useContext(ResearchRunUiContext)
  if (query.isLoading) return <div className="my-2 flex min-h-20 items-center gap-2 rounded-xl border bg-muted/30 p-4 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />恢复 Research Run…</div>
  if (!query.data) return <div className="my-2 rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">该 Research Run 不存在或无权访问。</div>
  const run = query.data
  const steps = run.steps ?? []
  const done = steps.filter((step) => step.status === "completed").length
  return (
    <section className="my-2 overflow-hidden rounded-xl border bg-[var(--surface-raised)] shadow-sm" aria-label={`Research Run：${run.title}`}>
      <div className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><FlaskConical className="size-4" /></span>
        <div className="min-w-0 flex-1"><p className="text-xs font-medium text-muted-foreground">Research Harness</p><h3 className="mt-0.5 line-clamp-2 text-sm font-semibold">{run.title}</h3><p className="mt-1 text-xs text-muted-foreground">真实三步骨架 · {done}/{steps.length} 步完成</p></div>
        <Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge>
      </div>
      <Button variant="ghost" className="min-h-11 w-full justify-between rounded-none border-t px-4" onClick={(event) => openRun(run.id, event.currentTarget)}>查看 Workflow<ArrowRight className="size-4" /></Button>
    </section>
  )
}

export const ResearchRunDataUI = makeAssistantDataUI<{ run_id: string }>({
  name: "research-run",
  render: ({ data }) => <ResearchRunCard runId={data.run_id} />,
})
