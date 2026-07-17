import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"

function normalizeLooseMarkdown(content: string) {
  const output: string[] = []
  let inFence = false
  let previousKind = ""
  for (const line of content.split("\n")) {
    const trimmed = line.trim()
    if (trimmed.startsWith("```") || trimmed.startsWith("~~~")) inFence = !inFence
    const kind = /^\d+\.\s/.test(trimmed) ? "ordered"
      : /^[-*+]\s/.test(trimmed) ? "unordered"
        : /^#{1,6}\s/.test(trimmed) || /^(-{3,}|_{3,}|\*{3,})$/.test(trimmed) ? "block"
          : ""
    const previous = output[output.length - 1] ?? ""
    if (!inFence && kind && previous.trim() && kind !== previousKind) output.push("")
    output.push(line)
    previousKind = kind
  }
  return output.join("\n")
}

export function MarkdownBlock({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("max-w-3xl space-y-3 break-words text-sm leading-7 text-muted-foreground [overflow-wrap:anywhere]", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h2 className="pt-2 text-2xl font-semibold leading-tight text-foreground">{children}</h2>,
          h2: ({ children }) => <h3 className="pt-2 text-xl font-semibold leading-tight text-foreground">{children}</h3>,
          h3: ({ children }) => <h4 className="pt-1 text-base font-semibold text-foreground">{children}</h4>,
          h4: ({ children }) => <h5 className="pt-1 font-semibold text-foreground">{children}</h5>,
          p: ({ children }) => <p>{children}</p>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-6">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-6 tabular-nums">{children}</ol>,
          li: ({ children }) => <li className="pl-1">{children}</li>,
          strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
          blockquote: ({ children }) => <blockquote className="border-l-2 border-primary/40 pl-4 italic">{children}</blockquote>,
          a: ({ children, href }) => <a href={href} target="_blank" rel="noreferrer" className="font-medium text-primary underline underline-offset-4">{children}</a>,
          pre: ({ children }) => <pre className="max-w-full overflow-x-auto rounded-lg bg-muted p-4 text-xs leading-6 text-foreground">{children}</pre>,
          code: ({ children, className: codeClassName }) => codeClassName
            ? <code className={codeClassName}>{children}</code>
            : <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">{children}</code>,
          table: ({ children }) => <div className="max-w-full overflow-x-auto rounded-lg border"><table className="w-full min-w-[32rem] border-collapse text-left text-xs">{children}</table></div>,
          thead: ({ children }) => <thead className="bg-muted/70 text-foreground">{children}</thead>,
          th: ({ children }) => <th className="border-b px-3 py-2 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border-b px-3 py-2 align-top">{children}</td>,
          hr: () => <hr className="border-border" />,
        }}
      >
        {normalizeLooseMarkdown(content)}
      </ReactMarkdown>
    </div>
  )
}
