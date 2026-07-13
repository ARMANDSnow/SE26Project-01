import { Star } from "lucide-react"
import { Link } from "react-router"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ProcessingBadge } from "@/components/common/status-badge"
import { cn } from "@/lib/utils"
import type { Paper } from "@/types"

type PaperTableProps = {
  papers: Paper[]
  onFavorite: (paper: Paper) => void
  favoriteBusy?: boolean
}

export function PaperTable({ papers, onFavorite, favoriteBusy = false }: PaperTableProps) {
  return (
    <div className="min-w-0 overflow-hidden rounded-lg border bg-card">
      <Table className="table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className="w-[46%]">论文</TableHead>
            <TableHead>分类</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>发布时间</TableHead>
            <TableHead className="text-right">操作</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {papers.map((paper) => (
            <TableRow key={paper.id} className="min-h-12">
              <TableCell className="min-w-0 whitespace-normal">
                <div className="min-w-0 space-y-1">
                  <Link
                    to={`/papers/${paper.id}`}
                    className="line-clamp-2 rounded-sm font-medium text-foreground [overflow-wrap:anywhere] hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {paper.title}
                  </Link>
                  <p className="line-clamp-1 text-xs text-muted-foreground">
                    {paper.authors.slice(0, 4).join("、")} · {paper.venue ?? paper.source ?? "arXiv"} · {paper.source_id}
                  </p>
                </div>
              </TableCell>
              <TableCell>
                <Badge variant="secondary" className="rounded-full">
                  {paper.primary_category}
                </Badge>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  <ProcessingBadge status={paper.processing_status} />
                </div>
              </TableCell>
              <TableCell className="text-muted-foreground">{paper.published_at}</TableCell>
              <TableCell>
                <div className="flex justify-end gap-2">
                  <Button
                    aria-label={paper.is_favorite ? "取消收藏" : "收藏"}
                    variant="ghost"
                    size="icon"
                    className="size-11"
                    onClick={() => onFavorite(paper)}
                    disabled={favoriteBusy}
                  >
                    <Star className={cn("size-4", paper.is_favorite && "fill-[var(--chart-2)] text-[var(--chart-2)]")} />
                  </Button>
                  <Button asChild variant="outline" className="h-11">
                    <Link to={`/papers/${paper.id}`}>打开</Link>
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
