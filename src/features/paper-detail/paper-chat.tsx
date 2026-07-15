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
  useLocalRuntime,
} from "@assistant-ui/react"
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown"
import { Check, ChevronLeft, ChevronRight, Copy, Edit3, Loader2, Plus, RefreshCw, Send, Square, X } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { createPaperChatThread, fetchChatMessages, fetchPaperChatThreads } from "@/api"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ChatThread } from "@/types"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? ""

function messageText(message: ThreadMessage): string {
  return message.content
    .filter((part): part is Extract<(typeof message.content)[number], { type: "text" }> => part.type === "text")
    .map((part) => part.text)
    .join("\n")
}

async function* streamChat(
  threadId: string,
  options: Parameters<ChatModelAdapter["run"]>[0],
): AsyncGenerator<{ content: Array<{ type: "text"; text: string }> }> {
  const messages = options.messages
  const current = messages[messages.length - 1]
  if (!current || current.role !== "user") throw new Error("缺少用户问题")
  const assistantMessageId = options.unstable_assistantMessageId ?? `msg_${crypto.randomUUID()}`
  const response = await fetch(`${API_BASE}/api/chat/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: options.abortSignal,
    body: JSON.stringify({
      thread_id: threadId,
      operation: "append",
      user_message: {
        id: current.id,
        parent_id: messages.length > 1 ? messages[messages.length - 2]?.id ?? null : null,
        content: messageText(current),
      },
      assistant_message_id: assistantMessageId,
      message_token_limit: 12000,
    }),
  })
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`)
  if (!response.body) throw new Error("浏览器未收到流式响应")

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
  return (
    <BranchPickerPrimitive.Root hideWhenSingleBranch className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <BranchPickerPrimitive.Previous className="rounded p-1 hover:bg-muted" aria-label="上一个分支">
        <ChevronLeft className="size-3.5" />
      </BranchPickerPrimitive.Previous>
      <span><BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count /></span>
      <BranchPickerPrimitive.Next className="rounded p-1 hover:bg-muted" aria-label="下一个分支">
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
          <ActionBarPrimitive.Edit className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="编辑消息">
            <Edit3 className="size-3.5" />
          </ActionBarPrimitive.Edit>
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="复制消息">
            <MessagePrimitive.If copied><Check className="size-3.5" /></MessagePrimitive.If>
            <MessagePrimitive.If copied={false}><Copy className="size-3.5" /></MessagePrimitive.If>
          </ActionBarPrimitive.Copy>
        </ActionBarPrimitive.Root>
      </div>
    </MessagePrimitive.Root>
  )
}

function AssistantMessage() {
  const MarkdownText = () => <MarkdownTextPrimitive />
  return (
    <MessagePrimitive.Root className="group mx-auto grid w-full max-w-3xl gap-2 px-3 py-3">
      <div className="rounded-2xl rounded-bl-md border bg-card px-4 py-3 text-sm leading-7">
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
        <MessagePrimitive.Error>
          <span className="text-destructive">生成失败，请重试。</span>
        </MessagePrimitive.Error>
      </div>
      <div className="flex items-center gap-1">
        <BranchPicker />
        <ActionBarPrimitive.Root className="flex items-center gap-1" hideWhenRunning>
          <ActionBarPrimitive.Reload className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="重新生成">
            <RefreshCw className="size-3.5" />
          </ActionBarPrimitive.Reload>
          <ActionBarPrimitive.Copy className="rounded p-1 text-muted-foreground hover:bg-muted" aria-label="复制回答">
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
            <Button type="submit" size="sm"><Check className="size-4" />保存并重新生成</Button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </MessagePrimitive.Root>
  )
}

function RuntimeChat({ thread }: { thread: ChatThread }) {
  const history = useMemo<ThreadHistoryAdapter>(() => ({
    async load() {
      const repository = await fetchChatMessages(thread.id)
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
            ...(row.role === "assistant" ? { status: { type: "complete" as const } } : {}),
          } as ThreadMessage,
        })),
      }
    },
    async append() {
      // The run endpoint persists user and assistant messages transactionally.
    },
  }), [thread.id])

  const adapter = useMemo<ChatModelAdapter>(() => ({
    async *run(options) {
      yield* streamChat(thread.id, options)
    },
  }), [thread.id])
  const runtime = useLocalRuntime(adapter, { adapters: { history } })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex min-h-0 flex-1 flex-col">
        <ThreadPrimitive.Viewport className="flex min-h-0 flex-1 flex-col overflow-y-auto py-3">
          <ThreadPrimitive.Empty>
            <div className="m-auto grid max-w-sm gap-2 px-6 text-center">
              <strong className="text-base">围绕当前论文开始提问</strong>
              <span className="text-sm leading-6 text-muted-foreground">论文完整解析正文会随每个问题发送，历史消息最多保留 12,000 tokens。</span>
            </div>
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages components={{ UserMessage, AssistantMessage, UserEditComposer: EditComposer }} />
        </ThreadPrimitive.Viewport>
        <div className="border-t bg-card/80 p-3 backdrop-blur">
          <ComposerPrimitive.Root className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border bg-background p-2 shadow-sm">
            <ComposerPrimitive.Input
              className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
              placeholder="针对这篇论文提问…"
            />
            <ThreadPrimitive.If running={false}>
              <ComposerPrimitive.Send asChild>
                <Button type="submit" size="icon" className="size-10" aria-label="发送"><Send className="size-4" /></Button>
              </ComposerPrimitive.Send>
            </ThreadPrimitive.If>
            <ThreadPrimitive.If running>
              <ComposerPrimitive.Cancel asChild>
                <Button type="button" size="icon" variant="destructive" className="size-10" aria-label="停止"><Square className="size-4" /></Button>
              </ComposerPrimitive.Cancel>
            </ThreadPrimitive.If>
          </ComposerPrimitive.Root>
        </div>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  )
}

export function PaperChat({ paperId, enabled }: { paperId: number; enabled: boolean }) {
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(true)

  const loadThreads = useCallback(async () => {
    setLoading(true)
    try {
      let items = await fetchPaperChatThreads(paperId)
      if (!items.length) items = [await createPaperChatThread(paperId)]
      setThreads(items)
      setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0].id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "对话加载失败")
    } finally {
      setLoading(false)
    }
  }, [paperId])

  useEffect(() => { void loadThreads() }, [loadThreads])

  const addThread = async () => {
    try {
      const created = await createPaperChatThread(paperId)
      setThreads((current) => [created, ...current])
      setSelectedId(created.id)
    } catch {
      toast.error("新建对话失败")
    }
  }

  const selected = threads.find((thread) => thread.id === selectedId)
  return (
    <div className="flex min-h-[560px] min-w-0 flex-col overflow-hidden rounded-xl border bg-card">
      <div className="flex items-center gap-2 border-b p-3">
        <Select value={selectedId} onValueChange={setSelectedId} disabled={loading || !threads.length}>
          <SelectTrigger className="h-10 min-w-0 flex-1"><SelectValue placeholder="选择对话" /></SelectTrigger>
          <SelectContent>{threads.map((thread) => <SelectItem key={thread.id} value={thread.id}>{thread.title}</SelectItem>)}</SelectContent>
        </Select>
        <Button size="icon" variant="outline" className="size-10" onClick={addThread} aria-label="新建对话"><Plus className="size-4" /></Button>
      </div>
      {!enabled ? (
        <div className="m-auto grid max-w-sm gap-2 p-6 text-center">
          <strong>请先完成论文全文解析</strong>
          <span className="text-sm leading-6 text-muted-foreground">Chat 不会使用摘要代替正文。解析完成后，论文全文会始终加入上下文。</span>
        </div>
      ) : loading ? (
        <div className="m-auto inline-flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />加载对话</div>
      ) : selected ? <RuntimeChat key={selected.id} thread={selected} /> : null}
    </div>
  )
}
