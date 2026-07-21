import { BookOpen, Clock3, FileText, Star } from "lucide-react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { PreparationBadge } from "@/components/common/status-badge"
import { uniqueValues } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Paper } from "@/types"

type PaperCardProps = {
  paper: Paper
  compact?: boolean
  onFavorite?: (paper: Paper) => void
  favoriteBusy?: boolean
}

export function PaperCard({ paper, compact = false, onFavorite, favoriteBusy = false }: PaperCardProps) {
  const categories = uniqueValues(paper.categories).slice(0, compact ? 3 : 5)

  return (
    <article
      className={cn(
        "grid gap-4 rounded-lg border bg-card p-4 text-card-foreground shadow-sm transition-colors hover:border-primary/40 hover:bg-accent/30",
        !compact && "lg:grid-cols-[minmax(0,1fr)_auto]"
      )}
    >
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge className="h-6 rounded-full bg-primary/10 px-2 text-xs font-semibold text-primary hover:bg-primary/10">
            {paper.primary_category}
          </Badge>
          <PreparationBadge status={paper.preparation.status} />
        </div>

        <div className="space-y-2">
          <h2 className="text-base font-semibold leading-6 text-foreground">
            <Link className="rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" to={`/papers/${paper.id}`}>
              {paper.title}
            </Link>
          </h2>
          <p className={cn("text-sm leading-6 text-muted-foreground", compact ? "line-clamp-2" : "line-clamp-3")}>
            {paper.abstract}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span className="inline-flex min-w-0 items-center gap-1">
            <BookOpen className="size-3.5" />
            <span className="truncate">{paper.authors.slice(0, 3).join("、")}</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock3 className="size-3.5" />
            {paper.published_at}
          </span>
          <span className="inline-flex items-center gap-1">
            <FileText className="size-3.5" />
            {paper.venue ?? paper.source ?? "arXiv"} · {paper.source_id}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {categories.map((category) => (
            <Badge key={`${paper.id}-${category}`} variant="secondary" className="rounded-full px-2 text-xs">
              {category}
            </Badge>
          ))}
        </div>
      </div>

      <div className="flex items-start gap-2 lg:justify-end">
        {onFavorite ? (
          <Button
            aria-label={paper.is_favorite ? "取消收藏" : "收藏"}
            aria-pressed={paper.is_favorite}
            variant={paper.is_favorite ? "secondary" : "outline"}
            size="icon"
            className="size-11"
            onClick={() => onFavorite(paper)}
            disabled={favoriteBusy}
          >
            <Star className={cn("size-4", paper.is_favorite && "fill-[var(--chart-2)] text-[var(--chart-2)]")} />
          </Button>
        ) : null}
        <Button asChild variant="outline" className="h-11">
          <Link to={`/papers/${paper.id}`}>阅读</Link>
        </Button>
      </div>
    </article>
  )
}
