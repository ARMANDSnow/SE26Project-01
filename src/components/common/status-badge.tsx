import { Badge } from "@/components/ui/badge"
import { statusText } from "@/lib/format"
import type { Paper } from "@/types"

export function ProcessingBadge({ status }: { status: Paper["processing_status"] }) {
  const variant = status === "processed" ? "default" : status === "pending" ? "secondary" : "destructive"

  return (
    <Badge variant={variant} className="h-6 rounded-full px-2 text-xs font-semibold">
      {statusText(status)}
    </Badge>
  )
}

const preparationText: Record<Paper["preparation"]["status"], string> = {
  not_queued: "未排队",
  queued: "等待加工",
  download: "下载原文",
  parse: "解析全文",
  index: "建立索引",
  retry_wait: "等待重试",
  ready: "全文就绪",
  failed: "加工失败",
}

export function PreparationBadge({ status }: { status: Paper["preparation"]["status"] }) {
  const variant = status === "ready" ? "default" : status === "failed" ? "destructive" : "secondary"

  return (
    <Badge variant={variant} className="h-6 rounded-full px-2 text-xs font-semibold">
      {preparationText[status]}
    </Badge>
  )
}
