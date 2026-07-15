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
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Edit3,
  GitFork,
  RefreshCw,
  Send,
  Square,
  X,
} from "lucide-react"
import { createContext, type FormEvent, useContext, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import { fetchChatMessages, updateChatThreadHead } from "@/api"
import { Button } from "@/components/ui/button"
import type { ChatThread } from "@/types"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ""

type ChatThreadProps = {
  thread: ChatThread
  emptyTitle: string
  emptyDescription: string
  placeholder: string
  hero?: boolean
}

type ChatScope = {
  threadId: string
}

const ChatScopeContext = createContext<ChatScope | null>(null)

function messageText(message: ThreadMessage): string {
  return message.content
    .filter((part): part is Extract<(typeof message.content)[number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("\n")
}

async function responseError(response: Response): Promise<string> {
  const raw = await response.text()
  try {
    const parsed = JSON.parse(raw) as { detail?: string }
    return parsed.detail || raw || `HTTP ${response.status}`
  } catch {
    return raw || `HTTP ${response.status}`
  }
}

async function* streamChat(
  threadId: string,
  persistedIds: Set<string>,
  options: Parameters<ChatModelAdapter["run"]>[0],
): AsyncGenerator<{ content: Array<{ type: "text"; text: string }> }> {
  const messages = options.messages
  const current = messages[messages.length - 1]
  if (!current || current.role !== "user") throw new Error("缺少用户问题")

  const assistantMessageId = options.unstable_assistantMessageId ?? `msg_${crypto.randomUUID()}`
  const regenerate = persistedIds.has(current.id)
  const previous = regenerate ? undefined : messages[messages.length - 2]
  const response = await fetch(`${API_BASE}/api/chat/runs`, {
    method: "POST",
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
        className="rounded p-1 hover:bg-muted disabled:opacity-35"
        aria-label="上一个分支"
        onClick={persistAfterSwitch}
      >
        <ChevronLeft className="size-3.5" />
      </BranchPickerPrimitive.Previous>
      <span className="tabular-nums"><BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count /></span>
      <BranchPickerPrimitive.Next
        className="rounded p-1 hover:bg-muted disabled:opacity-35"
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
          <ActionBarPrimitive.Edit className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="编辑并分叉" title="编辑并分叉">
            <Edit3 className="size-3.5" />
          </ActionBarPrimitive.Edit>
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="复制消息" title="复制消息">
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
          <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(false)}><X className="size-4" />取消</Button>
          <Button type="submit" size="sm" disabled={!text.trim()}><GitFork className="size-4" />创建分支</Button>
        </div>
      </form>
    )
  }

  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
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
          <ActionBarPrimitive.Reload className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="重新生成一个分支" title="重新生成一个分支">
            <RefreshCw className="size-3.5" />
          </ActionBarPrimitive.Reload>
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="复制回答" title="复制回答">
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
            <Button type="button" size="sm" variant="ghost"><X className="size-4" />取消</Button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <Button type="submit" size="sm"><GitFork className="size-4" />保存为新分支</Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  )
}

function Composer({ placeholder, hero = false }: { placeholder: string; hero?: boolean }) {
  return (
    <ComposerPrimitive.Root className={hero
      ? "mx-auto flex w-full max-w-3xl items-end gap-2 rounded-2xl border bg-card p-3 shadow-lg"
      : "mx-auto flex w-full max-w-3xl items-end gap-2 rounded-xl border bg-background p-2 shadow-sm"}
    >
      <ComposerPrimitive.Input
        className={hero
          ? "max-h-64 min-h-28 flex-1 resize-none bg-transparent px-2 py-2 text-base leading-7 outline-none"
          : "max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"}
        placeholder={placeholder}
      />
      <ThreadPrimitive.If running={false}>
        <ComposerPrimitive.Send asChild>
          <Button type="submit" size="icon" className="size-10 shrink-0" aria-label="发送"><Send className="size-4" /></Button>
        </ComposerPrimitive.Send>
      </ThreadPrimitive.If>
      <ThreadPrimitive.If running>
        <ComposerPrimitive.Cancel asChild>
          <Button type="button" size="icon" variant="destructive" className="size-10 shrink-0" aria-label="停止"><Square className="size-4" /></Button>
        </ComposerPrimitive.Cancel>
      </ThreadPrimitive.If>
    </ComposerPrimitive.Root>
  )
}

function ChatSurface({ emptyTitle, emptyDescription, placeholder, hero }: Omit<ChatThreadProps, "thread">) {
  const messageCount = useAuiState((state) => state.thread.messages.length)

  if (hero && messageCount === 0) {
    return (
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <div className="m-auto grid w-full gap-7 px-4 py-12">
          <div className="mx-auto grid max-w-2xl gap-3 text-center">
            <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">{emptyTitle}</h1>
            <p className="text-sm leading-6 text-muted-foreground md:text-base">{emptyDescription}</p>
          </div>
          <Composer placeholder={placeholder} hero />
          <p className="text-center text-xs text-muted-foreground">当前仅发送本对话历史，不接入论文、资料库、联网搜索或 Agent 工具。</p>
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
        <Composer placeholder={placeholder} />
      </div>
    </ThreadPrimitive.Root>
  )
}

export function ChatThread({ thread, emptyTitle, emptyDescription, placeholder, hero = false }: ChatThreadProps) {
  const persistedIdsRef = useRef(new Set<string>())
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
            content: [{ type: "text" as const, text: row.content }],
            createdAt: new Date(row.created_at),
            metadata: { custom: {} },
            ...(row.role === "assistant"
              ? { status: row.status === "complete" ? { type: "complete" as const } : { type: "incomplete" as const, reason: "error" as const } }
              : {}),
          } as ThreadMessage,
        })),
      }
    },
    async append() {
      // POST /api/chat/runs atomically persists the user and assistant messages.
    },
  }), [thread.id])

  const adapter = useMemo<ChatModelAdapter>(() => ({
    async *run(options) {
      yield* streamChat(thread.id, persistedIdsRef.current, options)
    },
  }), [thread.id])
  const runtime = useLocalRuntime(adapter, { adapters: { history } })

  return (
    <ChatScopeContext.Provider value={{ threadId: thread.id }}>
      <AssistantRuntimeProvider runtime={runtime}>
        <ChatSurface
          emptyTitle={emptyTitle}
          emptyDescription={emptyDescription}
          placeholder={placeholder}
          hero={hero}
        />
      </AssistantRuntimeProvider>
    </ChatScopeContext.Provider>
  )
}
