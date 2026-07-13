import { Loader2 } from "lucide-react"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type LoadingStateProps = {
  label: string
  skeleton?: boolean
  className?: string
}

export function LoadingState({ label, skeleton = false, className }: LoadingStateProps) {
  if (skeleton) {
    return (
      <div className={cn("grid gap-3 rounded-lg border bg-card p-4", className)} aria-busy="true">
        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          <span>{label}</span>
        </div>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-8 w-1/2" />
      </div>
    )
  }

  return (
    <div
      className={cn(
        "flex min-h-32 items-center justify-center gap-2 rounded-lg text-sm font-medium text-muted-foreground",
        className
      )}
      aria-busy="true"
    >
      <Loader2 className="size-4 animate-spin" />
      <span>{label}</span>
    </div>
  )
}
