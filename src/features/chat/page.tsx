import { Bot, Loader2, MessageSquarePlus } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { createGeneralChatThread, fetchGeneralChatThreads } from "@/api"
import { ChatThread } from "@/components/chat/chat-thread"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { ChatThread as ChatThreadRecord } from "@/types"

export function ChatPage() {
  const [threads, setThreads] = useState<ChatThreadRecord[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(true)
  const bootstrapping = useRef(false)

  const loadThreads = useCallback(async () => {
    setLoading(true)
    try {
      let items = await fetchGeneralChatThreads()
      if (!items.length && !bootstrapping.current) {
        bootstrapping.current = true
        try {
          items = [await createGeneralChatThread()]
        } finally {
          bootstrapping.current = false
        }
      }
      setThreads(items)
      setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? "")
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "通用对话加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadThreads() }, [loadThreads])

  const addThread = async () => {
    try {
      const created = await createGeneralChatThread()
      setThreads((current) => [created, ...current])
      setSelectedId(created.id)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "新建对话失败")
    }
  }

  const selected = threads.find((thread) => thread.id === selectedId)

  return (
    <section className="grid min-h-[calc(100vh-7.5rem)] overflow-hidden rounded-xl border bg-card shadow-sm lg:grid-cols-[260px_minmax(0,1fr)]">
      <aside className="hidden min-h-0 border-r bg-muted/25 lg:flex lg:flex-col">
        <div className="border-b p-3">
          <Button className="h-11 w-full justify-start" onClick={addThread}>
            <MessageSquarePlus className="size-4" />
            新建对话
          </Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <p className="px-2 pb-2 pt-1 text-xs font-medium text-muted-foreground">最近对话</p>
          <div className="grid gap-1">
            {threads.map((thread) => (
              <button
                key={thread.id}
                type="button"
                onClick={() => setSelectedId(thread.id)}
                className={cn(
                  "min-h-11 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
                  selectedId === thread.id && "bg-accent font-medium text-accent-foreground",
                )}
              >
                <span className="block truncate">{thread.title}</span>
                <span className="mt-0.5 block truncate text-[11px] font-normal text-muted-foreground">{thread.updated_at}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="border-t p-3 text-xs leading-5 text-muted-foreground">
          <span className="inline-flex items-center gap-1.5 font-medium text-foreground"><Bot className="size-3.5" />通用 Chat</span>
          <p className="mt-1">真实模型 · 仅当前对话历史</p>
        </div>
      </aside>

      <div className="flex min-h-[620px] min-w-0 flex-col">
        <div className="flex items-center justify-between border-b px-3 py-2 lg:hidden">
          <span className="truncate text-sm font-medium">{selected?.title ?? "通用 Chat"}</span>
          <Button size="sm" variant="outline" onClick={addThread}><MessageSquarePlus className="size-4" />新建</Button>
        </div>
        {loading ? (
          <div className="m-auto inline-flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />加载对话</div>
        ) : selected ? (
          <ChatThread
            key={selected.id}
            thread={selected}
            emptyTitle="今天想研究什么？"
            emptyDescription="先从普通多轮对话开始。当前不会读取论文、资料库或任何外部上下文。"
            placeholder="输入问题，Enter 发送…"
            hero
          />
        ) : (
          <div className="m-auto grid gap-3 text-center">
            <strong>暂时无法创建对话</strong>
            <Button variant="outline" onClick={() => void loadThreads()}>重试</Button>
          </div>
        )}
      </div>
    </section>
  )
}
