import { FlaskConical, Loader2, MessageSquarePlus } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router"
import { toast } from "sonner"
import { ChatThread } from "@/components/chat/chat-thread"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { WorkflowPanel } from "@/features/research/workflow-panel"
import { researchStatusLabel } from "@/features/research/status"
import { useResearchRunLiveQuery } from "@/features/research/use-research-run-stream"
import { useCreateGeneralChatThreadMutation, useGeneralChatThreadsQuery, useResearchRunsQuery } from "@/lib/query-hooks"
import type { ChatRouteMode } from "@/types"

export function ChatPage() {
  const [params, setParams] = useSearchParams()
  const threadsQuery = useGeneralChatThreadsQuery()
  const createThread = useCreateGeneralChatThreadMutation()
  const runsQuery = useResearchRunsQuery()
  const [workflowOpen, setWorkflowOpen] = useState(() => Boolean(params.get("run")) && !window.matchMedia("(min-width: 1200px)").matches)
  const workflowOpener = useRef<HTMLElement | null>(null)
  const bootstrapping = useRef(false)

  useEffect(() => {
    if (threadsQuery.isLoading || threadsQuery.isError || threadsQuery.data?.length || bootstrapping.current) return
    bootstrapping.current = true
    createThread.mutate(undefined, {
      onSuccess: (thread) => setParams((current) => { current.set("thread", thread.id); return current }, { replace: true }),
      onError: () => toast.error("通用对话创建失败"),
    })
  }, [createThread, setParams, threadsQuery.data?.length, threadsQuery.isError, threadsQuery.isLoading])

  const requestedThreadId = params.get("thread") ?? ""
  const selected = (threadsQuery.data ?? []).find((thread) => thread.id === requestedThreadId) ?? threadsQuery.data?.[0]
  useEffect(() => {
    if (selected && selected.id !== requestedThreadId) setParams((current) => { current.set("thread", selected.id); return current }, { replace: true })
  }, [requestedThreadId, selected, setParams])

  const activeRunId = params.get("run") ?? ""
  const runQuery = useResearchRunLiveQuery(activeRunId)
  const threadRuns = useMemo(() => (runsQuery.data ?? []).filter((run) => run.thread_id === selected?.id), [runsQuery.data, selected?.id])
  const latestThreadRun = threadRuns[0]
  const initialMode = (params.get("mode") === "deep_research" ? "deep_research" : params.get("mode") === "normal" ? "normal" : "auto") as ChatRouteMode

  const openRun = useCallback((runId: string, opener?: HTMLElement | null) => {
    workflowOpener.current = opener ?? null
    setParams((current) => { current.set("run", runId); return current })
    if (!window.matchMedia("(min-width: 1200px)").matches) setWorkflowOpen(true)
  }, [setParams])
  const selectRun = useCallback((runId: string) => setParams((current) => { current.set("run", runId); return current }), [setParams])
  const closeWorkflow = () => {
    setWorkflowOpen(false)
    requestAnimationFrame(() => {
      const fallback = Array.from(document.querySelectorAll<HTMLElement>("[data-workflow-run]"))
        .find((element) => element.dataset.workflowRun === activeRunId)
      ;(workflowOpener.current ?? fallback)?.focus()
    })
  }

  const runBar = latestThreadRun ? (
    <button type="button" onClick={(event) => openRun(latestThreadRun.id, event.currentTarget)} className="mb-2 flex min-h-11 w-full items-center gap-2 rounded-lg border bg-muted/60 px-3 text-left text-sm min-[1200px]:hidden">
      <FlaskConical className="size-4 shrink-0 text-primary" /><span className="min-w-0 flex-1 truncate">{latestThreadRun.title}</span><span className="shrink-0 text-xs text-muted-foreground">{researchStatusLabel[latestThreadRun.status]}</span>
    </button>
  ) : null

  return (
    <section className="grid h-[calc(100dvh-4rem)] min-h-[540px] min-w-0 overflow-hidden bg-card min-[1200px]:grid-cols-[minmax(0,1fr)_minmax(380px,430px)]">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="flex min-h-12 items-center justify-between border-b px-3 min-[1200px]:hidden">
          <div className="flex min-w-0 items-center gap-2"><span className="truncate text-sm font-medium">{selected?.title ?? "PaperWiki Chat"}</span></div>
          {latestThreadRun ? <Button size="sm" variant="outline" className="min-h-11" onClick={(event) => openRun(latestThreadRun.id, event.currentTarget)}><FlaskConical className="size-4" />Workflow</Button> : null}
        </div>
        {threadsQuery.isLoading || createThread.isPending ? <div className="m-auto inline-flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />加载对话</div> : selected ? (
          <ChatThread key={selected.id} thread={selected} emptyTitle="今天想研究什么？" emptyDescription="可以普通问答，也可以选择“深度研究”启动真实、可恢复的主题论文调研。" placeholder="输入问题，Enter 发送…" hero onOpenRun={openRun} onResearchRunCreated={selectRun} runBar={runBar} initialMode={initialMode} routingEnabled workspaceSelectionEnabled />
        ) : (
          <div className="m-auto grid gap-3 text-center"><strong>暂时无法创建对话</strong><Button variant="outline" onClick={() => threadsQuery.refetch()}><MessageSquarePlus className="size-4" />重试</Button></div>
        )}
      </div>
      <aside className="hidden min-h-0 border-l min-[1200px]:flex">
        {runQuery.data ? <WorkflowPanel run={runQuery.data} /> : <div className="m-auto max-w-xs p-8 text-center"><FlaskConical className="mx-auto size-8 text-muted-foreground" /><h2 className="mt-3 font-semibold">Workflow</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">从 Run 卡片打开工作流；这里只展示数据库中的真实步骤、论文、工具摘要和预算。</p></div>}
      </aside>
      <Sheet open={workflowOpen} onOpenChange={(open) => open ? setWorkflowOpen(true) : closeWorkflow()}>
        <SheetContent className="w-full gap-0 p-0 sm:max-w-[460px] max-md:h-[100dvh] max-md:!w-screen max-md:max-w-none" showCloseButton={false}>
          <SheetHeader className="sr-only"><SheetTitle>Research Workflow</SheetTitle><SheetDescription>当前 Research Run 的真实执行状态</SheetDescription></SheetHeader>
          {runQuery.data ? <WorkflowPanel run={runQuery.data} onClose={closeWorkflow} /> : <div className="m-auto text-sm text-muted-foreground">正在恢复 Workflow…</div>}
        </SheetContent>
      </Sheet>
    </section>
  )
}
