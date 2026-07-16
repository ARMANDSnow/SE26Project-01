import { useMemo, useRef, useState } from "react"
import { CircleAlert, ListChecks, Loader2, Plus } from "lucide-react"
import { Link } from "react-router"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { Textarea } from "@/components/ui/textarea"
import {
  useCreateResearchRunMutation,
  useResearchRunsQuery,
} from "@/lib/query-hooks"
import type { ResearchRun } from "@/types"
import { researchStatusLabel, researchStatusTone } from "./status"

const groups = [
  { key: "waiting", label: "等待确认", statuses: ["waiting_input", "paused"] },
  { key: "active", label: "执行中", statuses: ["queued", "running", "cancelling"] },
  { key: "completed", label: "已完成", statuses: ["completed"] },
  { key: "failed", label: "失败与取消", statuses: ["failed", "cancelled"] },
] as const

function RunLink({ run, onNavigate }: { run: ResearchRun; onNavigate: () => void }) {
  return (
    <Button
      asChild
      variant="ghost"
      className="h-auto min-h-14 w-full justify-start whitespace-normal border px-3 py-2 text-left"
    >
      <Link to={`/runs/${run.id}`} onClick={onNavigate}>
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 block text-sm font-medium">{run.title}</span>
          <span className="mt-1 block font-mono text-[12px] text-muted-foreground">
            {run.id.slice(0, 8)}
          </span>
        </span>
        <Badge variant={researchStatusTone[run.status]}>{researchStatusLabel[run.status]}</Badge>
      </Link>
    </Button>
  )
}

export function TaskCenter() {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const runsQuery = useResearchRunsQuery()
  const createRun = useCreateResearchRunMutation()
  const [title, setTitle] = useState("")
  const [goal, setGoal] = useState("")
  const waitingCount = runsQuery.data?.filter((run) => run.status === "waiting_input").length ?? 0
  const grouped = useMemo(
    () => groups.map((group) => ({
      ...group,
      runs: (runsQuery.data ?? []).filter((run) => (group.statuses as readonly string[]).includes(run.status)),
    })),
    [runsQuery.data],
  )

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!title.trim() || !goal.trim()) return
    await createRun.mutateAsync({ title: title.trim(), goal: goal.trim() })
    setTitle("")
    setGoal("")
  }

  return (
    <Sheet
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) requestAnimationFrame(() => triggerRef.current?.focus())
      }}
    >
      <SheetTrigger asChild>
        <Button ref={triggerRef} variant="outline" size="icon" className="relative size-11" aria-label="打开任务中心">
          <ListChecks className="size-4" />
          {waitingCount > 0 ? (
            <span className="absolute -right-1 -top-1 grid min-h-5 min-w-5 place-items-center rounded-full bg-destructive px-1 text-[11px] font-semibold text-destructive-foreground">
              {waitingCount}
            </span>
          ) : null}
        </Button>
      </SheetTrigger>
      <SheetContent className="w-full overflow-y-auto sm:max-w-md">
        <SheetHeader className="border-b pr-14">
          <SheetTitle>任务中心</SheetTitle>
          <SheetDescription>Research Run 由数据库恢复；关闭面板不会停止任务。</SheetDescription>
        </SheetHeader>

        <form className="grid gap-3 border-b p-4" onSubmit={submit}>
          <div>
            <h2 className="text-sm font-semibold">新建 Harness 骨架</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">仅验证可恢复流程，不会生成论文调研结论。</p>
          </div>
          <Input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="任务标题"
            aria-label="任务标题"
            maxLength={160}
          />
          <Textarea
            value={goal}
            onChange={(event) => setGoal(event.target.value)}
            placeholder="描述要交给后续研究流程的目标"
            aria-label="研究目标"
            maxLength={20_000}
            className="min-h-24"
          />
          <Button type="submit" disabled={!title.trim() || !goal.trim() || createRun.isPending}>
            {createRun.isPending ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
            创建 Harness
          </Button>
          {createRun.isError ? (
            <p className="flex gap-2 text-sm text-destructive" role="alert">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />创建失败，请稍后重试。
            </p>
          ) : null}
        </form>

        <div className="grid gap-5 p-4">
          {runsQuery.isLoading ? <p className="text-sm text-muted-foreground">正在读取任务…</p> : null}
          {runsQuery.isError ? (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3" role="alert">
              <p className="text-sm text-destructive">任务列表读取失败，已保存的 Run 不会因此丢失。</p>
              <Button className="mt-2" size="sm" variant="outline" onClick={() => runsQuery.refetch()}>
                重试读取
              </Button>
            </div>
          ) : null}
          {!runsQuery.isError ? grouped.map((group) => (
            <section key={group.key} aria-labelledby={`task-group-${group.key}`}>
              <div className="mb-2 flex items-center justify-between">
                <h2 id={`task-group-${group.key}`} className="text-sm font-semibold">{group.label}</h2>
                <span className="font-mono text-xs text-muted-foreground">{group.runs.length}</span>
              </div>
              <div className="grid gap-2">
                {group.runs.length > 0
                  ? group.runs.map((run) => <RunLink key={run.id} run={run} onNavigate={() => setOpen(false)} />)
                  : <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">暂无任务</p>}
              </div>
            </section>
          )) : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}
