import { FileText } from "lucide-react"
import type { ReactNode } from "react"
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"

type AppEmptyStateProps = {
  title: string
  description?: string
  action?: ReactNode
}

export function AppEmptyState({ title, description, action }: AppEmptyStateProps) {
  return (
    <Empty className="min-h-36 border border-dashed bg-muted/30">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <FileText className="size-4" />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        {description ? <EmptyDescription>{description}</EmptyDescription> : null}
      </EmptyHeader>
      {action ? <EmptyContent>{action}</EmptyContent> : null}
    </Empty>
  )
}
