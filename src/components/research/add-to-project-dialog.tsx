import { useMemo, useRef, useState, type ReactNode } from "react"
import { Check, FolderPlus, Loader2 } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { useAddResearchProjectItemMutation, useResearchProjectBacklinksQuery, useResearchProjectsQuery } from "@/lib/query-hooks"
import type { ResearchProjectItemInput } from "@/types"

export function AddToProjectDialog({ item, children }: { item: ResearchProjectItemInput; children?: ReactNode }) {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const projects = useResearchProjectsQuery("active")
  const backlinks = useResearchProjectBacklinksQuery(item, open)
  const linked = useMemo(() => new Set((backlinks.data ?? []).map((entry) => entry.project_id)), [backlinks.data])

  return (
    <Sheet open={open} onOpenChange={(next) => {
      setOpen(next)
      if (!next) requestAnimationFrame(() => triggerRef.current?.focus())
    }}>
      <SheetTrigger asChild>
        {children ?? <Button ref={triggerRef} variant="outline" className="min-h-11"><FolderPlus className="size-4" />加入研究项目</Button>}
      </SheetTrigger>
      <SheetContent className="w-full gap-0 p-0 sm:max-w-md">
        <SheetHeader className="border-b pr-14">
          <SheetTitle>加入研究项目</SheetTitle>
          <SheetDescription>只列出你拥有且仍可编辑的项目；加入项目不会改变原始资料权限。</SheetDescription>
        </SheetHeader>
        <div className="grid gap-2 overflow-y-auto p-4" aria-live="polite">
          {projects.isLoading || backlinks.isLoading ? <p className="flex items-center gap-2 py-4 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin motion-reduce:animate-none" />正在读取项目</p> : null}
          {projects.isError || backlinks.isError ? <p role="alert" className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">项目读取失败，未假定资料已经加入。</p> : null}
          {(projects.data ?? []).map((project) => (
            <ProjectChoice key={project.id} projectId={project.id} title={project.title} description={project.description} item={item} linked={linked.has(project.id)} />
          ))}
          {!projects.isLoading && !projects.isError && !(projects.data?.length) ? <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">还没有可编辑的研究项目。请先在“我的资料库”创建项目。</p> : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function ProjectChoice({ projectId, title, description, item, linked }: {
  projectId: string; title: string; description: string; item: ResearchProjectItemInput; linked: boolean
}) {
  const mutation = useAddResearchProjectItemMutation(projectId)
  return (
    <button
      type="button"
      disabled={linked || mutation.isPending}
      onClick={() => mutation.mutate(item, {
        onSuccess: () => toast.success(`已加入“${title}”。`),
        onError: () => toast.error("加入项目失败；资料权限或项目状态可能已变化。"),
      })}
      className="flex min-h-14 w-full min-w-0 items-center gap-3 rounded-xl border px-3 py-2 text-left hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
    >
      <span className="min-w-0 flex-1">
        <span className="block break-words text-sm font-medium [overflow-wrap:anywhere]">{title}</span>
        {description ? <span className="mt-1 line-clamp-2 block text-xs text-muted-foreground">{description}</span> : null}
      </span>
      {linked ? <span className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><Check className="size-4" />已加入</span> : mutation.isPending ? <Loader2 className="size-4 shrink-0 animate-spin motion-reduce:animate-none" /> : <FolderPlus className="size-4 shrink-0" />}
    </button>
  )
}
