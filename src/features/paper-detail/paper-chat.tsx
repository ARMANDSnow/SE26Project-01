import { Loader2, Plus } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { createPaperChatThread, fetchPaperChatThreads } from "@/api"
import { ChatThread } from "@/components/chat/chat-thread"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { ChatThread as ChatThreadRecord } from "@/types"

export function PaperChat({ paperId, enabled }: { paperId: number; enabled: boolean }) {
  const [threads, setThreads] = useState<ChatThreadRecord[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [loading, setLoading] = useState(true)
  const bootstrapping = useRef(false)

  const loadThreads = useCallback(async () => {
    setLoading(true)
    try {
      let items = await fetchPaperChatThreads(paperId)
      if (!items.length && !bootstrapping.current) {
        bootstrapping.current = true
        try {
          items = [await createPaperChatThread(paperId)]
        } finally {
          bootstrapping.current = false
        }
      }
      setThreads(items)
      setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? "")
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
      ) : selected ? (
        <ChatThread
          key={selected.id}
          thread={selected}
          emptyTitle="围绕当前论文开始提问"
          emptyDescription="论文完整解析正文会随每个问题发送，历史消息最多保留 12,000 tokens。"
          placeholder="针对这篇论文提问…"
        />
      ) : null}
    </div>
  )
}
