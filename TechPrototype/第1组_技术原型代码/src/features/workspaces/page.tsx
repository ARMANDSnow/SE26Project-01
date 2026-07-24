import { useMemo, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useCreateWorkspaceMutation, useLibraryFoldersQuery, useResearchProjectsQuery, useWorkspacesQuery } from "@/lib/query-hooks"

export function WorkspacesPage() {
  const workspacesQuery = useWorkspacesQuery()
  const foldersQuery = useLibraryFoldersQuery()
  const projectsQuery = useResearchProjectsQuery("active")
  const createWorkspace = useCreateWorkspaceMutation()
  const [source, setSource] = useState<"project" | "folder">("project")
  const [sourceId, setSourceId] = useState("")
  const [title, setTitle] = useState("")
  const folders = useMemo(() => (foldersQuery.data ?? []).filter((folder) => !folder.is_root), [foldersQuery.data])

  const create = async () => {
    const cleanedTitle = title.trim()
    if (!cleanedTitle || !sourceId) return
    try {
      await createWorkspace.mutateAsync(
        source === "project"
          ? { title: cleanedTitle, project_id: sourceId }
          : { title: cleanedTitle, folder_id: Number(sourceId) },
      )
      setTitle("")
      setSourceId("")
      toast.success("Workspace \u5df2\u521b\u5efa")
    } catch (error) {
      const message = error instanceof Error ? error.message : ""
      toast.error(message.includes("workspace title already exists") ? "Workspace \u540d\u79f0\u5df2\u5b58\u5728\uff0c\u8bf7\u66f4\u6362\u540d\u79f0\u3002" : "Workspace \u521b\u5efa\u5931\u8d25")
    }
  }

  return (
    <section className="mx-auto grid w-full max-w-4xl gap-5">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">{"Workspace"}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{"\u4ece\u7814\u7a76\u9879\u76ee\u6216\u8d44\u6599\u5e93\u6587\u4ef6\u5939\u521b\u5efa\u5bf9\u8bdd\u4e0a\u4e0b\u6587\u3002"}</p>
      </header>

      <div className="grid gap-3 rounded-xl border bg-card p-4 md:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium">
          {"\u6765\u6e90"}
          <Select value={source} onValueChange={(value) => { setSource(value as "project" | "folder"); setSourceId("") }}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="project">{"\u7814\u7a76\u9879\u76ee"}</SelectItem>
              <SelectItem value="folder">{"\u8d44\u6599\u5e93\u6587\u4ef6\u5939"}</SelectItem>
            </SelectContent>
          </Select>
        </label>
        <label className="grid gap-1 text-sm font-medium">
          {source === "project" ? "\u7814\u7a76\u9879\u76ee" : "\u8d44\u6599\u5e93\u6587\u4ef6\u5939"}
          <Select value={sourceId || "none"} onValueChange={(value) => setSourceId(value === "none" ? "" : value)}>
            <SelectTrigger><SelectValue placeholder={"\u8bf7\u9009\u62e9"} /></SelectTrigger>
            <SelectContent>
              <SelectItem value="none" disabled>{"\u8bf7\u9009\u62e9"}</SelectItem>
              {source === "project"
                ? (projectsQuery.data ?? []).map((project) => <SelectItem key={project.id} value={project.id}>{project.title}</SelectItem>)
                : folders.map((folder) => <SelectItem key={folder.id} value={String(folder.id)}>{folder.path}</SelectItem>)}
            </SelectContent>
          </Select>
        </label>
        <label className="grid gap-1 text-sm font-medium md:col-span-2">
          {"Workspace \u540d\u79f0"}
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder={"Workspace \u540d\u79f0"} />
        </label>
        <div className="md:col-span-2">
          <Button disabled={!title.trim() || !sourceId || createWorkspace.isPending} onClick={() => void create()}>{"\u521b\u5efa Workspace"}</Button>
        </div>
      </div>

      <div className="rounded-xl border bg-card p-4">
        <h2 className="font-semibold">{"\u5df2\u521b\u5efa\u7684 Workspace"}</h2>
        <div className="mt-3 grid gap-2">
          {(workspacesQuery.data ?? []).map((workspace) => (
            <div key={workspace.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2">
              <span className="font-medium">{workspace.title}</span>
              <span className="text-sm text-muted-foreground">{workspace.project_title ?? workspace.folder_name ?? ""}</span>
            </div>
          ))}
          {!workspacesQuery.data?.length ? <p className="text-sm text-muted-foreground">{"\u8fd8\u6ca1\u6709 Workspace\u3002"}</p> : null}
        </div>
      </div>
    </section>
  )
}
