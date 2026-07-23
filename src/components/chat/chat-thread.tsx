import {
  ActionBarPrimitive,
  AssistantRuntimeProvider,
  BranchPickerPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  type ChatModelAdapter,
  type ThreadHistoryAdapter,
  type ThreadMessage,
  useAui,
  useAuiState,
  useLocalRuntime,
} from "@assistant-ui/react"
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown"
import { useQueryClient } from "@tanstack/react-query"
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit3,
  GitFork,
  FlaskConical,
  MessageSquare,
  RefreshCw,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react"
import { createContext, type FormEvent, type ReactNode, useContext, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { API_BASE, fetchChatMessages, routeChatMessage, updateChatThreadHead } from "@/api"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ResearchRunDataUI, ResearchRunUiContext } from "@/components/chat/research-run-message"
import { queryKeys, useUpdateChatThreadWorkspaceMutation, useWorkspacesQuery } from "@/lib/query-hooks"
import type { ChatContentPart, ChatRouteMode, ChatThread, ResearchRun } from "@/types"

type ChatThreadProps = {
  thread: ChatThread
  emptyTitle: string
  emptyDescription: string
  placeholder: string
  hero?: boolean
  onOpenRun?: (runId: string, opener?: HTMLElement | null) => void
  runBar?: ReactNode
  initialMode?: ChatRouteMode
  routingEnabled?: boolean
  onResearchRunCreated?: (runId: string) => void
  workspaceSelectionEnabled?: boolean
}

type ChatScope = {
  threadId: string
}

const ChatScopeContext = createContext<ChatScope | null>(null)
const noop = () => undefined

function messageText(message: ThreadMessage): string {
  return message.content
    .filter((part): part is Extract<(typeof message.content)[number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("\n")
}

async function responseError(response: Response): Promise<string> {
  const raw = await response.text()
  try {
    const parsed = JSON.parse(raw) as { detail?: string | { message?: string; code?: string } }
    if (typeof parsed.detail === "string") {
      if (parsed.detail === "LLM is not configured. Set LLM_API_KEY and restart the backend.") {
        return "\u6a21\u578b\u5c1a\u672a\u914d\u7f6e\u3002\u8bf7\u5728\u542f\u52a8\u540e\u7aef\u7684\u73af\u5883\u4e2d\u8bbe\u7f6e LLM_API_KEY \u540e\u91cd\u542f\u670d\u52a1\u3002"
      }
      return parsed.detail
    }
    if (parsed.detail?.message) return parsed.detail.message
    return raw || `HTTP ${response.status}`
  } catch {
    return raw || `HTTP ${response.status}`
  }
}

async function* streamNormalChat(
  threadId: string,
  persistedIds: Set<string>,
  options: Parameters<ChatModelAdapter["run"]>[0],
): AsyncGenerator<{ content: ChatContentPart[] }> {
  const messages = options.messages
  const current = messages[messages.length - 1]
  if (!current || current.role !== "user") throw new Error("缺少用户问题")

  const assistantMessageId = options.unstable_assistantMessageId ?? `msg_${crypto.randomUUID()}`
  const regenerate = persistedIds.has(current.id)
  const previous = regenerate ? undefined : messages[messages.length - 2]
  const response = await fetch(`${API_BASE}/api/chat/runs`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    signal: options.abortSignal,
    body: JSON.stringify({
      thread_id: threadId,
      operation: regenerate ? "regenerate" : "append",
      user_message: regenerate
        ? undefined
        : {
            id: current.id,
            parent_id: previous?.id ?? null,
            content: messageText(current),
          },
      parent_message_id: regenerate ? current.id : undefined,
      assistant_message_id: assistantMessageId,
      message_token_limit: 12000,
    }),
  })
  if (!response.ok) throw new Error(await responseError(response))
  if (!response.body) throw new Error("浏览器未收到流式响应")

  persistedIds.add(current.id)
  persistedIds.add(assistantMessageId)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let accumulated = ""

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    const blocks = buffer.split("\n\n")
    buffer = blocks.pop() ?? ""
    for (const block of blocks) {
      const event = block.split("\n").find((line) => line.startsWith("event:"))?.slice(6).trim()
      const raw = block.split("\n").find((line) => line.startsWith("data:"))?.slice(5).trim()
      if (!raw) continue
      const data = JSON.parse(raw) as { delta?: string; message?: string; content?: string }
      if (event === "text.delta" && data.delta) {
        accumulated += data.delta
        yield { content: [{ type: "text", text: accumulated }] }
      } else if (event === "run.failed") {
        throw new Error(data.message || "回答生成失败")
      } else if (event === "message.completed" && data.content !== undefined) {
        accumulated = data.content
        yield { content: [{ type: "text", text: accumulated }] }
      }
    }
    if (done) break
  }
}

async function* routeAndStreamChat(
  threadId: string,
  mode: ChatRouteMode,
  persistedIds: Set<string>,
  options: Parameters<ChatModelAdapter["run"]>[0],
  onResearchRun: (run: ResearchRun) => void,
): AsyncGenerator<{ content: ChatContentPart[] }> {
  const messages = options.messages
  const current = messages[messages.length - 1]
  if (!current || current.role !== "user") throw new Error("缺少用户问题")
  const regenerate = persistedIds.has(current.id)
  if (regenerate) {
    yield* streamNormalChat(threadId, persistedIds, options)
    return
  }
  const previous = messages[messages.length - 2]
  const assistantMessageId = options.unstable_assistantMessageId ?? `msg_${crypto.randomUUID()}`
  const routed = await routeChatMessage({
    thread_id: threadId,
    mode,
    user_message: { id: current.id, parent_id: previous?.id ?? null, content: messageText(current) },
    assistant_message_id: assistantMessageId,
    message_token_limit: 12000,
  })
  if (routed.route === "normal_chat") {
    yield* streamNormalChat(threadId, persistedIds, options)
    return
  }
  persistedIds.add(current.id)
  persistedIds.add(assistantMessageId)
  onResearchRun(routed.run)
  yield { content: [
    { type: "text", text: `已创建主题调研任务「${routed.run.title}」。Workflow 将按数据库中的真实步骤检索、筛选与读取论文；缺少模型配置时会明确失败。` },
    { type: "data", name: "research-run", data: { run_id: routed.run.id } },
  ] }
}

function BranchPicker() {
  const scope = useContext(ChatScopeContext)
  const aui = useAui()

  const persistAfterSwitch = () => {
    if (!scope) return
    window.setTimeout(() => {
      const messages = aui.thread().getState().messages
      const headId = messages[messages.length - 1]?.id
      void updateChatThreadHead(scope.threadId, headId).catch(() => {
        toast.error("分支已切换，但当前分支位置保存失败。")
      })
    }, 0)
  }

  return (
    <BranchPickerPrimitive.Root hideWhenSingleBranch className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <BranchPickerPrimitive.Previous
        className="rounded p-1 hover:bg-muted disabled:opacity-35 max-md:min-h-11 max-md:min-w-11"
        aria-label="上一个分支"
        onClick={persistAfterSwitch}
      >
        <ChevronLeft className="size-3.5" />
      </BranchPickerPrimitive.Previous>
      <span className="tabular-nums"><BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count /></span>
      <BranchPickerPrimitive.Next
        className="rounded p-1 hover:bg-muted disabled:opacity-35 max-md:min-h-11 max-md:min-w-11"
        aria-label="下一个分支"
        onClick={persistAfterSwitch}
      >
        <ChevronRight className="size-3.5" />
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  )
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="group mx-auto grid w-full max-w-3xl justify-items-end gap-1 px-3 py-2">
      <div className="max-w-[88%] rounded-2xl rounded-br-md bg-primary px-4 py-3 text-sm leading-6 text-primary-foreground">
        <MessagePrimitive.Parts />
      </div>
      <div className="flex items-center gap-1">
        <BranchPicker />
        <ActionBarPrimitive.Root className="flex items-center gap-1" hideWhenRunning>
          <ActionBarPrimitive.Edit className="rounded p-1 text-muted-foreground hover:bg-muted max-md:min-h-11 max-md:min-w-11" aria-label="编辑并分叉" title="编辑并分叉">
            <Edit3 className="size-3.5" />
          </ActionBarPrimitive.Edit>
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted max-md:min-h-11 max-md:min-w-11" aria-label="复制消息" title="复制消息">
            <MessagePrimitive.If copied><Check className="size-3.5" /></MessagePrimitive.If>
            <MessagePrimitive.If copied={false}><Copy className="size-3.5" /></MessagePrimitive.If>
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  )
}

function ForkAction() {
  const aui = useAui()
  const messageId = useAuiState((state) => state.message.id)
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("")

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const content = text.trim()
    if (!content) return
    aui.thread().append({
      parentId: messageId,
      role: "user",
      content: [{ type: "text", text: content }],
      startRun: true,
    })
    setText("")
    setOpen(false)
  }

  if (open) {
    return (
      <form className="mt-2 grid w-full gap-2 rounded-xl border bg-background p-3" onSubmit={submit}>
        <label className="text-xs font-medium text-muted-foreground" htmlFor={`fork-${messageId}`}>从这条回答继续新的方向</label>
        <textarea
          id={`fork-${messageId}`}
          autoFocus
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="min-h-20 resize-y bg-transparent text-sm leading-6 outline-none"
          placeholder="输入新分支中的下一条问题…"
        />
        <div className="flex justify-end gap-2">
          <Button type="button" size="sm" variant="ghost" className="max-md:min-h-11" onClick={() => setOpen(false)}><X className="size-4" />取消</Button>
          <Button type="submit" size="sm" className="max-md:min-h-11" disabled={!text.trim()}><GitFork className="size-4" />创建分支</Button>
        </div>
      </form>
    )
  }

  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground max-md:min-h-11"
      onClick={() => setOpen(true)}
      title="从这里分叉"
    >
      <GitFork className="size-3.5" />
      分叉
    </button>
  )
}

function AssistantMessage() {
  const MarkdownText = () => <MarkdownTextPrimitive />
  const hasResearchRun = useAuiState((state) => state.message.content.some((part) => part.type === "data" && part.name === "research-run"))
  return (
    <MessagePrimitive.Root className="group mx-auto grid w-full max-w-3xl gap-2 px-3 py-3">
      <div className="rounded-2xl rounded-bl-md border bg-card px-4 py-3 text-sm leading-7">
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
        <MessagePrimitive.Error>
          <span className="text-destructive">生成失败，请检查模型配置或稍后重试。</span>
        </MessagePrimitive.Error>
        <ForkAction />
      </div>
      <div className="flex items-center gap-1">
        <BranchPicker />
        <ActionBarPrimitive.Root className="flex items-center gap-1" hideWhenRunning>
          {!hasResearchRun ? <ActionBarPrimitive.Reload className="rounded p-1 text-muted-foreground hover:bg-muted max-md:min-h-11 max-md:min-w-11" aria-label="重新生成一个分支" title="重新生成一个分支">
            <RefreshCw className="size-3.5" />
          </ActionBarPrimitive.Reload> : null}
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted max-md:min-h-11 max-md:min-w-11" aria-label="复制回答" title="复制回答">
            <Copy className="size-3.5" />
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  )
}

function EditComposer() {
  return (
    <MessagePrimitive.Root className="mx-auto w-full max-w-3xl px-3 py-2">
      <ComposerPrimitive.Root className="grid gap-2 rounded-xl border bg-card p-3">
        <ComposerPrimitive.Input className="min-h-24 resize-none bg-transparent text-sm outline-none" />
        <div className="flex justify-end gap-2">
          <ComposerPrimitive.Cancel asChild>
            <Button type="button" size="sm" variant="ghost" className="max-md:min-h-11"><X className="size-4" />取消</Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button type="submit" size="sm" className="max-md:min-h-11"><GitFork className="size-4" />保存为新分支</Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  )
}

function Composer({ placeholder, hero = false, mode, onModeChange, routingEnabled, workspaceSelectionEnabled, workspaceId, onWorkspaceChange }: { placeholder: string; hero?: boolean; mode: ChatRouteMode; onModeChange: (mode: ChatRouteMode) => void; routingEnabled: boolean; workspaceSelectionEnabled: boolean; workspaceId?: string | null; onWorkspaceChange: (workspaceId?: string) => void }) {
  const ModeIcon = mode === "deep_research" ? FlaskConical : mode === "normal" ? MessageSquare : Sparkles
  const scope = useContext(ChatScopeContext)
  const messageCount = useAuiState((state) => state.thread.messages.length)
  const workspacesQuery = useWorkspacesQuery()
  const updateWorkspace = useUpdateChatThreadWorkspaceMutation()
  const workspaceLocked = messageCount > 0
  const [pendingWorkspaceId, setPendingWorkspaceId] = useState(workspaceId ?? "")

  const selectWorkspace = (value: string) => {
    if (!scope || workspaceLocked) return
    const nextWorkspaceId = value === "none" ? undefined : value
    setPendingWorkspaceId(nextWorkspaceId ?? "")
    updateWorkspace.mutate(
      { threadId: scope.threadId, workspaceId: nextWorkspaceId },
      {
        onSuccess: (thread) => onWorkspaceChange(thread.workspace_id ?? undefined),
        onError: () => {
          setPendingWorkspaceId(workspaceId ?? "")
          toast.error("\u7ed1\u5b9a Workspace \u5931\u8d25")
        },
      },
    )
  }

  return (
    <ComposerPrimitive.Root className={hero ? "mx-auto grid w-full max-w-3xl gap-2 rounded-2xl border bg-card p-3 shadow-lg" : "mx-auto grid w-full max-w-3xl gap-2 rounded-xl border bg-background p-2 shadow-sm"}>
      <ComposerPrimitive.Input
        className={hero
          ? "max-h-64 min-h-28 flex-1 resize-none bg-transparent px-2 py-2 text-base leading-7 outline-none"
          : "max-h-40 min-h-11 w-full resize-none bg-transparent px-2 py-2 text-sm outline-none"}
        placeholder={placeholder}
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          {routingEnabled ? (
            <Select value={mode} onValueChange={(value) => onModeChange(value as ChatRouteMode)}>
              <SelectTrigger id="chat-route-mode" aria-label={"\u56de\u7b54\u6a21\u5f0f"} className="min-h-11 rounded-xl bg-background px-2.5">
                <span className="grid size-7 shrink-0 place-items-center rounded-full bg-muted text-muted-foreground" aria-hidden="true"><ModeIcon className="size-3.5" /></span>
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper" align="start">
                <SelectItem value="auto" className="min-h-11"><Sparkles />{"\u81ea\u52a8\u5224\u65ad"}</SelectItem>
                <SelectItem value="normal" className="min-h-11"><MessageSquare />{"\u666e\u901a\u5bf9\u8bdd"}</SelectItem>
                <SelectItem value="deep_research" className="min-h-11"><FlaskConical />{"\u6df1\u5ea6\u7814\u7a76"}</SelectItem>
              </SelectContent>
            </Select>
          ) : null}
          {workspaceSelectionEnabled ? (
            <Select value={pendingWorkspaceId || "none"} onValueChange={selectWorkspace} disabled={workspaceLocked || updateWorkspace.isPending}>
              <SelectTrigger aria-label={"\u7ed1\u5b9a Workspace"} className="min-h-11 min-w-0 max-w-52 rounded-xl bg-background px-2.5">
                <SelectValue placeholder="Workspace" />
              </SelectTrigger>
              <SelectContent position="popper" align="start">
                <SelectItem value="none">{"\u4e0d\u7ed1\u5b9a Workspace"}</SelectItem>
                {(workspacesQuery.data ?? []).map((workspace) => <SelectItem key={workspace.id} value={workspace.id}>{workspace.title}</SelectItem>)}
              </SelectContent>
            </Select>
          ) : null}
        </div>
        <ThreadPrimitive.If running={false}><ComposerPrimitive.Send asChild><Button type="submit" size="icon" className="size-11 shrink-0" aria-label={"\u53d1\u9001"} disabled={updateWorkspace.isPending}><Send className="size-4" /></Button></ComposerPrimitive.Send></ThreadPrimitive.If>
        <ThreadPrimitive.If running><ComposerPrimitive.Cancel asChild><Button type="button" size="icon" variant="destructive" className="size-11 shrink-0" aria-label={"\u505c\u6b62"}><Square className="size-4" /></Button></ComposerPrimitive.Cancel></ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  )
}

const modeHint: Record<ChatRouteMode, string> = {
  auto: "自动判断问题类型；只有明确的主题论文调研才会创建 Research Run。",
  normal: "普通对话不会创建 Research Run。",
  deep_research: "深度研究将启动真实、可恢复的主题论文调研；每一步和预算都以数据库记录为准。",
}

function ChatSurface({ emptyTitle, emptyDescription, placeholder, hero, runBar, mode, onModeChange, routingEnabled = false, workspaceSelectionEnabled = false, workspaceId, onWorkspaceChange }: Omit<ChatThreadProps, "thread" | "onOpenRun" | "initialMode"> & { mode: ChatRouteMode; onModeChange: (mode: ChatRouteMode) => void; workspaceId?: string | null; onWorkspaceChange: (workspaceId?: string) => void }) {
  const messageCount = useAuiState((state) => state.thread.messages.length)

  if (hero && messageCount === 0) {
    return (
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <div className="m-auto grid w-full gap-7 px-4 py-12">
          <div className="mx-auto grid max-w-2xl gap-3 text-center">
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">{emptyTitle}</h1>
            <p className="text-sm leading-6 text-muted-foreground md:text-base">{emptyDescription}</p>
          </div>
          <Composer placeholder={placeholder} hero mode={mode} onModeChange={onModeChange} routingEnabled={routingEnabled} workspaceSelectionEnabled={workspaceSelectionEnabled} workspaceId={workspaceId} onWorkspaceChange={onWorkspaceChange} />
          <p className="text-center text-xs text-muted-foreground" aria-live="polite">{routingEnabled ? modeHint[mode] : "当前对话使用原有上下文契约。"}</p>
        </div>
      </ThreadPrimitive.Root>
    )
  }

  return (
    <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
      <ThreadPrimitive.Viewport className="flex min-h-0 flex-1 flex-col overflow-y-auto py-3">
        <ThreadPrimitive.Empty>
          <div className="m-auto grid max-w-sm gap-2 px-6 text-center">
            <strong className="text-base">{emptyTitle}</strong>
            <span className="text-sm leading-6 text-muted-foreground">{emptyDescription}</span>
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage, UserEditComposer: EditComposer }} />
      </ThreadPrimitive.Viewport>
      <div className="border-t bg-card/80 p-3 backdrop-blur">
        {runBar}
        <Composer placeholder={placeholder} mode={mode} onModeChange={onModeChange} routingEnabled={routingEnabled} workspaceSelectionEnabled={workspaceSelectionEnabled} workspaceId={workspaceId} onWorkspaceChange={onWorkspaceChange} />
      </div>
    </ThreadPrimitive.Root>
  )
}

export function ChatThread({ thread, emptyTitle, emptyDescription, placeholder, hero = false, onOpenRun = noop, runBar, initialMode = "auto", routingEnabled = false, onResearchRunCreated = noop, workspaceSelectionEnabled = false }: ChatThreadProps) {
  const persistedIdsRef = useRef(new Set<string>())
  const [mode, setMode] = useState<ChatRouteMode>(initialMode)
  const [workspaceId, setWorkspaceId] = useState(thread.workspace_id)
  const queryClient = useQueryClient()
  const history = useMemo<ThreadHistoryAdapter>(() => ({
    async load() {
      const repository = await fetchChatMessages(thread.id)
      persistedIdsRef.current = new Set(repository.messages.map((row) => row.id))
      return {
        headId: repository.headId ?? null,
        messages: repository.messages.map((row) => ({
          parentId: row.parent_id ?? null,
          message: {
            id: row.id,
            role: row.role,
            content: row.content_parts,
            createdAt: new Date(row.created_at),
            metadata: { custom: {} },
            ...(row.role === "assistant"
              ? { status: row.status === "complete" ? { type: "complete" as const } : { type: "incomplete" as const, reason: "error" as const } }
              : {}),
          } as unknown as ThreadMessage,
        })),
      }
    },
    async append() {
      // POST /api/chat/runs atomically persists the user and assistant messages.
    },
  }), [thread.id])

  const adapter = useMemo<ChatModelAdapter>(() => ({
    async *run(options) {
      if (routingEnabled) {
        yield* routeAndStreamChat(thread.id, mode, persistedIdsRef.current, options, (run) => {
          queryClient.setQueryData(queryKeys.researchRun(run.id), run)
          void queryClient.invalidateQueries({ queryKey: queryKeys.researchRuns })
          onResearchRunCreated(run.id)
        })
      } else {
        yield* streamNormalChat(thread.id, persistedIdsRef.current, options)
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.chatThreads })
    },
  }), [mode, onResearchRunCreated, queryClient, routingEnabled, thread.id])
  const runtime = useLocalRuntime(adapter, { adapters: { history } })

  return (
    <ChatScopeContext.Provider value={{ threadId: thread.id }}>
      <ResearchRunUiContext.Provider value={{ openRun: onOpenRun }}>
      <AssistantRuntimeProvider runtime={runtime}>
        <ResearchRunDataUI />
        <ChatSurface
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
          placeholder={placeholder}
          hero={hero}
          runBar={runBar}
          mode={mode}
          onModeChange={setMode}
          routingEnabled={routingEnabled}
          workspaceSelectionEnabled={workspaceSelectionEnabled}
          workspaceId={workspaceId}
          onWorkspaceChange={setWorkspaceId}
        />
      </AssistantRuntimeProvider>
      </ResearchRunUiContext.Provider>
    </ChatScopeContext.Provider>
  )
}
