import { cn } from "@/lib/utils"

export function MarkdownBlock({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("max-w-3xl space-y-3 text-sm leading-7 text-muted-foreground", className)}>
      {content.split("\n").map((line, index) => {
        const key = `${index}-${line.slice(0, 10)}`
        const trimmed = line.trim()

        if (line.startsWith("# ")) {
          return (
            <h2 key={key} className="pt-1 text-xl font-semibold text-foreground">
              {line.replace("# ", "")}
            </h2>
          )
        }

        if (trimmed.startsWith("- ")) {
          return (
            <p key={key} className="flex gap-2">
              <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
              <span>{trimmed.replace("- ", "")}</span>
            </p>
          )
        }

        if (/^\d+\./.test(trimmed)) {
          return (
            <p key={key} className="pl-4 tabular-nums">
              {trimmed}
            </p>
          )
        }

        if (!trimmed) return <div key={key} className="h-2" />

        return <p key={key}>{line}</p>
      })}
    </div>
  )
}
