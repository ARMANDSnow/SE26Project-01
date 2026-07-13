import { Brain, CheckCircle2, Loader2, MessageSquareText, Send } from "lucide-react"
import { FormEvent, useEffect, useMemo, useState } from "react"
import { Link } from "react-router"
import { PageHeader } from "@/components/common/page-header"
import { LoadingState } from "@/components/common/loading-state"
import { AppEmptyState } from "@/components/common/empty-state"
import { MarkdownBlock } from "@/components/common/markdown-block"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { plainSnippet } from "@/lib/format"
import { useAskQuestionMutation, useWikiSearchQuery } from "@/lib/query-hooks"

export function QAPage() {
  const [question, setQuestion] = useState("RAG 如何保证论文问答的出处可靠？")
  const [submittedQuestion, setSubmittedQuestion] = useState(question)
  const askMutation = useAskQuestionMutation()
  const searchQuery = useWikiSearchQuery(submittedQuestion, Boolean(submittedQuestion))
  const answer = askMutation.data

  const onAsk = async (event?: FormEvent) => {
    event?.preventDefault()
    if (!question.trim()) return
    setSubmittedQuestion(question.trim())
    await askMutation.mutateAsync({ question: question.trim() })
  }

  useEffect(() => {
    askMutation.mutate({ question: submittedQuestion })
    // Run once with the default question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const evidence = useMemo(() => {
    if (answer?.citations.length) return answer.citations
    return searchQuery.data ?? []
  }, [answer, searchQuery.data])

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="带出处的自然语言问答"
        title="智能问答"
        description="围绕论文、概念、方法或研究脉络提问，回答与证据片段保持并排可核验。"
      />

      <form className="grid gap-3 rounded-lg border bg-card p-3 md:grid-cols-[auto_minmax(0,1fr)_auto]" onSubmit={onAsk}>
        <MessageSquareText className="mt-3 hidden size-5 text-muted-foreground md:block" />
        <Input
          className="h-11"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          aria-label="问答问题"
          placeholder="围绕论文、概念、方法或研究脉络提问"
        />
        <Button className="h-11" disabled={askMutation.isPending || !question.trim()}>
          {askMutation.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          发送
        </Button>
      </form>

      {askMutation.isError ? (
        <Alert variant="destructive">
          <AlertTitle>问答失败</AlertTitle>
          <AlertDescription>请稍后重试，或确认后端服务是否运行。</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.82fr)]">
        <Card className="min-h-[430px]">
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="inline-flex items-center gap-2 text-lg">
              <Brain className="size-4" />
              回答
            </CardTitle>
            {answer ? <Badge className="rounded-full">置信度 {(answer.confidence * 100).toFixed(0)}%</Badge> : null}
          </CardHeader>
          <CardContent>
            {askMutation.isPending && !answer ? (
              <LoadingState label="正在生成回答" />
            ) : answer ? (
              <div className="grid gap-4">
                <MarkdownBlock content={answer.answer} />
                <Progress value={Math.min(100, answer.confidence * 100)} aria-label={`置信度 ${(answer.confidence * 100).toFixed(0)}%`} />
                <div className="flex flex-wrap gap-2">
                  {answer.agent_trace.map((agent) => (
                    <Badge key={agent} variant="secondary" className="rounded-full">
                      {agent}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : (
              <AppEmptyState title="等待问题输入" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="inline-flex items-center gap-2 text-lg">
              <CheckCircle2 className="size-4" />
              证据片段
            </CardTitle>
            <Badge variant="secondary" className="rounded-full">
              {evidence.length} 条
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-2">
            {searchQuery.isLoading && !evidence.length ? <LoadingState label="正在检索证据" /> : null}
            {evidence.map((item) => (
              <Link
                key={`${item.paper_id}-${item.section}-${item.score}`}
                to={`/papers/${item.paper_id}`}
                className="grid min-h-24 gap-1 rounded-lg border bg-background p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <strong className="line-clamp-2 text-sm">{item.paper_title}</strong>
                <span className="text-xs text-muted-foreground">
                  {item.section_title} · 匹配度 {(item.score * 100).toFixed(0)}%
                </span>
                <p className="line-clamp-2 text-sm leading-6 text-muted-foreground">{plainSnippet(item.content)}</p>
              </Link>
            ))}
            {!evidence.length && !searchQuery.isLoading ? <AppEmptyState title="暂无证据片段" /> : null}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
