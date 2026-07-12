import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Bot, ChevronRight, FileText, Folder, FolderPlus, Loader2, MoveRight, Sparkles, Trash2 } from "lucide-react"
import { Link } from "react-router"
import { toast } from "sonner"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import {
  useCreateLibraryFolderMutation,
  useDeleteLibraryFolderMutation,
  useLibraryFoldersQuery,
  useLibraryItemsQuery,
  useMoveLibraryItemMutation,
  useRecommendLibraryFolderMutation,
} from "@/lib/query-hooks"
import { cn } from "@/lib/utils"
import type { FolderRecommendation } from "@/types"

export function LibraryPage() {
  const foldersQuery = useLibraryFoldersQuery()
  const folders = useMemo(() => foldersQuery.data ?? [], [foldersQuery.data])
  const root = folders.find((folder) => folder.is_root)
  const [selectedFolderId, setSelectedFolderId] = useState<number | undefined>()
  const effectiveFolderId = selectedFolderId ?? root?.id
  const itemsQuery = useLibraryItemsQuery(effectiveFolderId === root?.id ? undefined : effectiveFolderId)
  const createMutation = useCreateLibraryFolderMutation()
  const deleteMutation = useDeleteLibraryFolderMutation()
  const moveMutation = useMoveLibraryItemMutation()
  const recommendMutation = useRecommendLibraryFolderMutation()
  const [folderName, setFolderName] = useState("")
  const [folderDescription, setFolderDescription] = useState("")
  const [moveTargets, setMoveTargets] = useState<Record<number, string>>({})
  const [recommendation, setRecommendation] = useState<(FolderRecommendation & { itemId: number; title: string }) | null>(null)

  useEffect(() => {
    if (root && selectedFolderId === undefined) setSelectedFolderId(root.id)
  }, [root, selectedFolderId])

  const selectedFolder = folders.find((folder) => folder.id === effectiveFolderId)
  const targetFolders = folders.filter((folder) => !folder.is_root)

  const createFolder = async (event: FormEvent) => {
    event.preventDefault()
    if (!folderName.trim()) return
    try {
      await createMutation.mutateAsync({
        name: folderName.trim(),
        description: folderDescription.trim(),
        parent_id: effectiveFolderId,
      })
      setFolderName("")
      setFolderDescription("")
      toast.success("文件夹已创建。")
    } catch {
      toast.error("文件夹创建失败，名称可能已存在。")
    }
  }

  const moveItem = async (itemId: number, folderId: number) => {
    try {
      await moveMutation.mutateAsync({ itemId, folderId })
      setRecommendation(null)
      toast.success("论文已移动。")
    } catch {
      toast.error("论文移动失败。")
    }
  }

  const requestRecommendation = async (itemId: number, title: string) => {
    setRecommendation(null)
    try {
      const result = await recommendMutation.mutateAsync(itemId)
      setRecommendation({ ...result, itemId, title })
    } catch {
      toast.error(targetFolders.filter((folder) => !folder.is_system).length ? "无法获取目录推荐，请检查 LLM 配置。" : "请先创建一个普通文件夹。")
    }
  }

  const removeSelectedFolder = async () => {
    if (!selectedFolder || selectedFolder.is_system) return
    try {
      await deleteMutation.mutateAsync(selectedFolder.id)
      setSelectedFolderId(root?.id)
      toast.success("空文件夹已删除。")
    } catch {
      toast.error("只能删除不含论文和子目录的空文件夹。")
    }
  }

  if (foldersQuery.isLoading) return <LoadingState label="正在加载个人资料库" skeleton />

  return (
    <section className="grid gap-5">
      <PageHeader eyebrow="个人论文空间" title="我的资料库" description="用文件夹整理收藏论文，需要时让 LLM 推荐目录，确认后再移动。" />

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader><CardTitle className="flex items-center gap-2 text-lg"><Folder className="size-4" />文件夹</CardTitle></CardHeader>
          <CardContent className="grid gap-4">
            <nav className="grid gap-1" aria-label="资料库文件夹">
              {folders.map((folder) => {
                const depth = Math.max(0, folder.path.split(" / ").length - 1)
                return (
                  <button
                    key={folder.id}
                    type="button"
                    onClick={() => setSelectedFolderId(folder.id)}
                    className={cn("flex min-h-10 items-center gap-2 rounded-md px-3 text-left text-sm hover:bg-accent", effectiveFolderId === folder.id && "bg-primary/10 font-medium text-primary")}
                    style={{ paddingLeft: `${12 + depth * 18}px` }}
                  >
                    <Folder className="size-4 shrink-0" />
                    <span className="min-w-0 flex-1 truncate">{folder.name}</span>
                    <Badge variant="secondary" className="rounded-full">{folder.item_count}</Badge>
                  </button>
                )
              })}
            </nav>

            <form className="grid gap-2 border-t pt-4" onSubmit={createFolder}>
              <Label htmlFor="folder-name">在当前目录中新建</Label>
              <Input id="folder-name" value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="文件夹名称" />
              <Input value={folderDescription} onChange={(event) => setFolderDescription(event.target.value)} placeholder="目录主题说明（供 LLM 参考）" />
              <Button disabled={!folderName.trim() || createMutation.isPending}>
                {createMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <FolderPlus className="size-4" />}新建文件夹
              </Button>
            </form>
            {selectedFolder && !selectedFolder.is_system ? (
              <Button variant="outline" onClick={removeSelectedFolder} disabled={deleteMutation.isPending}>
                <Trash2 className="size-4" />删除当前空文件夹
              </Button>
            ) : null}
          </CardContent>
        </Card>

        <div className="grid min-w-0 gap-4">
          <Card>
            <CardContent className="flex flex-wrap items-center gap-2 p-4">
              {(selectedFolder?.path ?? "我的资料库").split(" / ").map((part, index) => (
                <span key={`${part}-${index}`} className="inline-flex items-center gap-2 text-sm">
                  {index > 0 ? <ChevronRight className="size-4 text-muted-foreground" /> : null}{part}
                </span>
              ))}
              {selectedFolder?.description ? <span className="ml-auto text-sm text-muted-foreground">{selectedFolder.description}</span> : null}
            </CardContent>
          </Card>

          {recommendation ? (
            <Card className="border-primary/40 bg-primary/5">
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Sparkles className="size-4 text-primary" />AI 目录推荐</CardTitle></CardHeader>
              <CardContent className="grid gap-3">
                <p className="text-sm"><strong>{recommendation.title}</strong></p>
                <p className="text-sm">推荐放入：<strong>{recommendation.folder_path}</strong></p>
                <p className="text-sm text-muted-foreground">{recommendation.reason}</p>
                <div className="flex flex-wrap gap-2">
                  <Button onClick={() => moveItem(recommendation.itemId, recommendation.folder_id)} disabled={moveMutation.isPending}><MoveRight className="size-4" />确认移动</Button>
                  <Button variant="outline" onClick={() => setRecommendation(null)}>取消</Button>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {itemsQuery.isLoading ? <LoadingState label="正在加载论文" skeleton /> : null}
          {!itemsQuery.isLoading && !(itemsQuery.data?.length) ? <AppEmptyState title="当前目录暂无收藏论文" description="去论文库收藏后，论文会先进入“待整理”。" /> : null}
          {(itemsQuery.data ?? []).map((item) => (
            <Card key={item.library_item_id}>
              <CardContent className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_auto]">
                <div className="min-w-0 space-y-2">
                  <div className="flex flex-wrap items-center gap-2"><Badge variant="secondary">{item.primary_category}</Badge><span className="text-xs text-muted-foreground">收藏于 {item.saved_at}</span></div>
                  <Link to={`/papers/${item.id}`} className="block font-semibold hover:text-primary">{item.title}</Link>
                  <p className="line-clamp-2 text-sm leading-6 text-muted-foreground">{item.abstract}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2 xl:max-w-md xl:justify-end">
                  <Button variant="outline" onClick={() => requestRecommendation(item.library_item_id, item.title)} disabled={recommendMutation.isPending || !targetFolders.some((folder) => !folder.is_system)}>
                    {recommendMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Bot className="size-4" />}AI 推荐目录
                  </Button>
                  <Select value={moveTargets[item.library_item_id] ?? ""} onValueChange={(value) => setMoveTargets((current) => ({ ...current, [item.library_item_id]: value }))}>
                    <SelectTrigger className="w-44"><SelectValue placeholder="手动选择目录" /></SelectTrigger>
                    <SelectContent>{targetFolders.map((folder) => <SelectItem key={folder.id} value={String(folder.id)}>{folder.path}</SelectItem>)}</SelectContent>
                  </Select>
                  <Button variant="secondary" size="icon" aria-label="移动到所选目录" disabled={!moveTargets[item.library_item_id] || moveMutation.isPending} onClick={() => moveItem(item.library_item_id, Number(moveTargets[item.library_item_id]))}><MoveRight className="size-4" /></Button>
                </div>
              </CardContent>
            </Card>
          ))}
          <Button asChild variant="outline" className="w-fit"><Link to="/papers"><FileText className="size-4" />去论文库收藏论文</Link></Button>
        </div>
      </div>
    </section>
  )
}
