import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Archive, Bot, ChevronRight, FileText, Folder, FolderPlus, GitBranch, Loader2, MoveRight, Sparkles, Trash2 } from "lucide-react"
import { Link, useSearchParams } from "react-router"
import { toast } from "sonner"
import { AddToProjectDialog } from "@/components/research/add-to-project-dialog"
import { AppEmptyState } from "@/components/common/empty-state"
import { LoadingState } from "@/components/common/loading-state"
import { PageHeader } from "@/components/common/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  useCreateLibraryFolderMutation, useCreateResearchProjectMutation, useDeleteLibraryFolderMutation,
  useLibraryFoldersQuery, useLibraryItemsQuery, useMoveLibraryItemMutation,
  useRecommendLibraryFolderMutation, useResearchProjectsQuery, useResearchReportLibraryQuery,
} from "@/lib/query-hooks"
import { cn } from "@/lib/utils"
import type { FolderRecommendation } from "@/types"

type LibraryView = "papers" | "projects" | "reports"

export function LibraryPage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get("view")
  const view: LibraryView = requested === "projects" || requested === "reports" ? requested : "papers"
  const setView = (next: LibraryView) => setParams((current) => { current.set("view", next); return current }, { replace: true })
  return <section className="grid min-w-0 gap-5">
    <PageHeader eyebrow="个人研究空间" title="我的资料库" description="集中管理收藏论文、研究项目和固定版本报告。" />
    <div className="grid grid-cols-3 rounded-xl bg-muted p-1" role="tablist" aria-label="资料库内容">
      {[{ value: "papers", label: "论文", icon: FileText }, { value: "projects", label: "研究项目", icon: GitBranch }, { value: "reports", label: "报告", icon: Archive }].map((item) => <button key={item.value} id={`library-tab-${item.value}`} type="button" role="tab" aria-controls="library-tabpanel" aria-selected={view === item.value} tabIndex={view === item.value ? 0 : -1} onClick={() => setView(item.value as LibraryView)} className="flex min-h-11 items-center justify-center gap-2 rounded-lg px-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-background aria-selected:shadow-sm"><item.icon className="size-4" /><span className="max-sm:sr-only">{item.label}</span></button>)}
    </div>
    <div id="library-tabpanel" role="tabpanel" aria-labelledby={`library-tab-${view}`}>{view === "papers" ? <PaperLibrary /> : view === "projects" ? <ProjectLibrary /> : <ReportLibrary />}</div>
  </section>
}

function ProjectLibrary() {
  const active = useResearchProjectsQuery("active")
  const archived = useResearchProjectsQuery("archived")
  const create = useCreateResearchProjectMutation()
  const [showArchived, setShowArchived] = useState(false)
  const [title, setTitle] = useState("")
  const [description, setDescription] = useState("")
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!title.trim()) return
    try { await create.mutateAsync({ title: title.trim(), description: description.trim() }); setTitle(""); setDescription(""); toast.success("研究项目已创建。") } catch { toast.error("项目创建失败，请检查名称长度或是否重复。") }
  }
  const projects = showArchived ? archived.data ?? [] : active.data ?? []
  return <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
    <Card className="h-fit"><CardHeader><CardTitle className="flex items-center gap-2 text-lg"><FolderPlus className="size-4" />创建研究项目</CardTitle></CardHeader><CardContent><form className="grid gap-3" onSubmit={submit}><div className="grid gap-2"><Label htmlFor="new-project-title">项目名称</Label><Input id="new-project-title" className="min-h-11" maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：可追溯 RAG 研究" /></div><div className="grid gap-2"><Label htmlFor="new-project-description">研究说明</Label><Textarea id="new-project-description" maxLength={4000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="研究问题、范围和预期产物" /></div><Button className="min-h-11" disabled={!title.trim() || create.isPending}>{create.isPending ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <FolderPlus className="size-4" />}创建项目</Button></form></CardContent></Card>
    <div className="min-w-0"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><h2 className="text-lg font-semibold">{showArchived ? "已归档项目" : "进行中的项目"}</h2><p className="mt-1 text-sm text-muted-foreground">项目不会扩大 Run、论文、报告或引用的访问权限。</p></div><Button variant="outline" className="min-h-11" onClick={() => setShowArchived((value) => !value)}>{showArchived ? "查看进行中" : "查看已归档"}</Button></div>{active.isLoading || archived.isLoading ? <LoadingState label="正在读取研究项目" skeleton /> : null}{active.isError || archived.isError ? <p role="alert" className="rounded-xl border border-destructive/40 p-4 text-sm text-destructive">研究项目读取失败。</p> : null}<div className="grid gap-3 md:grid-cols-2">{projects.map((project) => <Link key={project.id} to={`/library/projects/${project.id}`} className="min-w-0 rounded-xl border p-4 hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><div className="flex min-w-0 items-start justify-between gap-2"><h3 className="break-words font-semibold [overflow-wrap:anywhere]">{project.title}</h3><Badge variant="outline">{project.status === "archived" ? "已归档" : "进行中"}</Badge></div>{project.description ? <p className="mt-2 line-clamp-2 break-words text-sm leading-6 text-muted-foreground">{project.description}</p> : null}<div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">{project.item_count != null ? <span>{project.item_count} 项资料</span> : null}{project.stale_item_count != null && project.stale_item_count > 0 ? <span>{project.stale_item_count} 项待更新</span> : null}<span>更新于 {project.updated_at}</span></div></Link>)}</div>{!projects.length && !active.isLoading && !archived.isLoading ? <AppEmptyState title={showArchived ? "没有已归档项目" : "还没有研究项目"} description={showArchived ? "归档后的项目会保留历史版本并显示在这里。" : "创建项目后，可以从 Run、论文和报告加入资料。"} /> : null}</div>
  </div>
}

function ReportLibrary() {
  const reports = useResearchReportLibraryQuery()
  if (reports.isLoading) return <LoadingState label="正在读取研究报告" skeleton />
  if (reports.isError) return <p role="alert" className="rounded-xl border border-destructive/40 p-4 text-sm text-destructive">报告读取失败，未把网络错误解释为没有报告。</p>
  return <section aria-labelledby="library-reports-heading"><div className="mb-3"><h2 id="library-reports-heading" className="text-lg font-semibold">研究报告</h2><p className="mt-1 text-sm text-muted-foreground">每条记录固定到明确版本；历史版本不会静默漂移。</p></div><div className="grid gap-3 lg:grid-cols-2">{(reports.data ?? []).map((report) => report.status === "inaccessible" ? <article key={`${report.artifact_id}-${report.artifact_version}`} className="rounded-xl border border-dashed p-4 text-sm text-muted-foreground">报告不可访问，标题、主题与引用已隐藏。</article> : <article key={`${report.artifact_id}-${report.artifact_version}`} className="min-w-0 rounded-xl border p-4"><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">v{report.artifact_version}</Badge><Badge variant={report.status === "stale" ? "outline" : "secondary"}>{report.status === "stale" ? "历史/已失效" : "当前有效"}</Badge></div><h3 className="mt-3 break-words font-semibold [overflow-wrap:anywhere]">{report.title}</h3><p className="mt-1 break-words text-sm text-muted-foreground">{report.topic}</p><p className="mt-2 text-xs text-muted-foreground">来源：{report.run_title}</p><div className="mt-4 flex flex-wrap gap-2"><Button asChild variant="outline" className="min-h-11"><Link to={`/runs/${report.run_id}/reports/${report.artifact_version}`}>打开报告</Link></Button><AddToProjectDialog item={{ item_type: "research_report", artifact_id: report.artifact_id, artifact_version: report.artifact_version }} /></div></article>)}</div>{!reports.data?.length ? <AppEmptyState title="还没有研究报告" description="完成主题调研并通过引用校验后，报告会出现在这里。" /> : null}</section>
}

function PaperLibrary() {
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
  useEffect(() => { if (root && selectedFolderId === undefined) setSelectedFolderId(root.id) }, [root, selectedFolderId])
  const selectedFolder = folders.find((folder) => folder.id === effectiveFolderId)
  const targetFolders = folders.filter((folder) => !folder.is_root)
  const createFolder = async (event: FormEvent) => { event.preventDefault(); if (!folderName.trim()) return; try { await createMutation.mutateAsync({ name: folderName.trim(), description: folderDescription.trim(), parent_id: effectiveFolderId }); setFolderName(""); setFolderDescription(""); toast.success("文件夹已创建。") } catch { toast.error("文件夹创建失败，名称可能已存在。") } }
  const moveItem = async (itemId: number, folderId: number) => { try { await moveMutation.mutateAsync({ itemId, folderId }); setRecommendation(null); toast.success("论文已移动。") } catch { toast.error("论文移动失败。") } }
  const requestRecommendation = async (itemId: number, itemTitle: string) => { setRecommendation(null); try { const result = await recommendMutation.mutateAsync(itemId); setRecommendation({ ...result, itemId, title: itemTitle }) } catch { toast.error(targetFolders.some((folder) => !folder.is_system) ? "无法获取目录推荐，请检查 LLM 配置。" : "请先创建一个普通文件夹。") } }
  const removeSelectedFolder = async () => { if (!selectedFolder || selectedFolder.is_system) return; try { await deleteMutation.mutateAsync(selectedFolder.id); setSelectedFolderId(root?.id); toast.success("空文件夹已删除。") } catch { toast.error("只能删除不含论文和子目录的空文件夹。") } }
  if (foldersQuery.isLoading) return <LoadingState label="正在加载个人论文" skeleton />
  return <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]"><Card className="h-fit"><CardHeader><CardTitle className="flex items-center gap-2 text-lg"><Folder className="size-4" />文件夹</CardTitle></CardHeader><CardContent className="grid gap-4"><nav className="grid gap-1" aria-label="资料库文件夹">{folders.map((folder) => { const depth = Math.max(0, folder.path.split(" / ").length - 1); return <button key={folder.id} type="button" onClick={() => setSelectedFolderId(folder.id)} className={cn("flex min-h-11 items-center gap-2 rounded-lg px-3 text-left text-sm hover:bg-accent", effectiveFolderId === folder.id && "bg-primary/10 font-medium text-primary")} style={{ paddingLeft: `${12 + depth * 18}px` }}><Folder className="size-4 shrink-0" /><span className="min-w-0 flex-1 truncate">{folder.name}</span><Badge variant="secondary">{folder.item_count}</Badge></button> })}</nav><form className="grid gap-2 border-t pt-4" onSubmit={createFolder}><Label htmlFor="folder-name">在当前目录中新建</Label><Input id="folder-name" className="min-h-11" value={folderName} onChange={(event) => setFolderName(event.target.value)} placeholder="文件夹名称" /><Input className="min-h-11" value={folderDescription} onChange={(event) => setFolderDescription(event.target.value)} placeholder="目录主题说明" /><Button className="min-h-11" disabled={!folderName.trim() || createMutation.isPending}>{createMutation.isPending ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <FolderPlus className="size-4" />}新建文件夹</Button></form>{selectedFolder && !selectedFolder.is_system ? <Button variant="outline" className="min-h-11" onClick={removeSelectedFolder} disabled={deleteMutation.isPending}><Trash2 className="size-4" />删除当前空文件夹</Button> : null}</CardContent></Card><div className="grid min-w-0 gap-4"><Card><CardContent className="flex flex-wrap items-center gap-2 p-4">{(selectedFolder?.path ?? "我的资料库").split(" / ").map((part, index) => <span key={`${part}-${index}`} className="inline-flex items-center gap-2 text-sm">{index ? <ChevronRight className="size-4 text-muted-foreground" /> : null}{part}</span>)}{selectedFolder?.description ? <span className="ml-auto break-words text-sm text-muted-foreground">{selectedFolder.description}</span> : null}</CardContent></Card>{recommendation ? <Card className="border-primary/40 bg-primary/5"><CardHeader><CardTitle className="flex items-center gap-2 text-base"><Sparkles className="size-4 text-primary" />AI 目录推荐</CardTitle></CardHeader><CardContent className="grid gap-3"><p className="break-words text-sm"><strong>{recommendation.title}</strong></p><p className="text-sm">推荐放入：<strong>{recommendation.folder_path}</strong></p><p className="text-sm text-muted-foreground">{recommendation.reason}</p><div className="flex flex-wrap gap-2"><Button className="min-h-11" onClick={() => moveItem(recommendation.itemId, recommendation.folder_id)} disabled={moveMutation.isPending}><MoveRight className="size-4" />确认移动</Button><Button variant="outline" className="min-h-11" onClick={() => setRecommendation(null)}>取消</Button></div></CardContent></Card> : null}{itemsQuery.isLoading ? <LoadingState label="正在加载论文" skeleton /> : null}{!itemsQuery.isLoading && !itemsQuery.data?.length ? <AppEmptyState title="当前目录暂无收藏论文" description="去论文库收藏后，论文会先进入“待整理”。" /> : null}{(itemsQuery.data ?? []).map((item) => <Card key={item.library_item_id}><CardContent className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_auto]"><div className="min-w-0 space-y-2"><div className="flex flex-wrap items-center gap-2"><Badge variant="secondary">{item.primary_category}</Badge><span className="text-xs text-muted-foreground">收藏于 {item.saved_at}</span></div><Link to={`/papers/${item.id}`} className="block break-words font-semibold hover:text-primary [overflow-wrap:anywhere]">{item.title}</Link><p className="line-clamp-2 text-sm leading-6 text-muted-foreground">{item.abstract}</p></div><div className="flex flex-wrap items-center gap-2 xl:max-w-md xl:justify-end"><AddToProjectDialog item={{ item_type: "paper", paper_id: item.id }} /><Button variant="outline" className="min-h-11" onClick={() => requestRecommendation(item.library_item_id, item.title)} disabled={recommendMutation.isPending || !targetFolders.some((folder) => !folder.is_system)}>{recommendMutation.isPending ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Bot className="size-4" />}推荐目录</Button><Select value={moveTargets[item.library_item_id] ?? ""} onValueChange={(value) => setMoveTargets((current) => ({ ...current, [item.library_item_id]: value }))}><SelectTrigger className="min-h-11 w-44"><SelectValue placeholder="手动选择目录" /></SelectTrigger><SelectContent>{targetFolders.map((folder) => <SelectItem key={folder.id} value={String(folder.id)}>{folder.path}</SelectItem>)}</SelectContent></Select><Button variant="secondary" size="icon" className="size-11" aria-label="移动到所选目录" disabled={!moveTargets[item.library_item_id] || moveMutation.isPending} onClick={() => moveItem(item.library_item_id, Number(moveTargets[item.library_item_id]))}><MoveRight className="size-4" /></Button></div></CardContent></Card>)}<Button asChild variant="outline" className="min-h-11 w-fit"><Link to="/papers"><FileText className="size-4" />去论文库收藏论文</Link></Button></div></div>
}
