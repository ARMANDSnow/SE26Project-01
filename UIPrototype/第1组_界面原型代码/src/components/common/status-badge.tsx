import { Badge } from "@/components/ui/badge"
import { readingText, statusText } from "@/lib/format"
import type { Paper } from "@/types"

export function ProcessingBadge({ status }: { status: Paper["processing_status"] }) {
  const variant = status === "processed" ? "default" : status === "pending" ? "secondary" : "destructive"

  return (
    <Badge variant={variant} className="h-6 rounded-full px-2 text-xs font-semibold">
      {statusText(status)}
    </Badge>
  )
}

export function ReadingBadge({ status }: { status: Paper["reading_status"] }) {
  return (
    <Badge variant="outline" className="h-6 rounded-full px-2 text-xs font-semibold">
      {readingText(status)}
    </Badge>
  )
}
