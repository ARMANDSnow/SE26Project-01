import { Brain, CheckCircle2, FileSearch, Loader2, MessageSquareText, Search, Send } from "lucide-react"
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

const sourceLabels: Record<string, string> = {
  html: "HTML",
  pdf: "PDF",
  metadata: "元数据",
  wiki: "Wiki",
}

const toolLabels: Record<string, string> = {
  search_metadata: "筛选论文",
  search_text: "搜索论文片段",
  open_evidence: "打开证据",
}

const executionLabels: Record<string, string> = {
  agentic_real: "真实模型自主探索",
  agentic_mock: "离线 Agent 演示",
  classic: "单轮快速问答",
}

const statusLabels: Record<string, string> = {
  completed: "探索完成",
  fallback: "引用校验降级",
  failed: "探索未完成",
}

const stopReasonLabels: Record<string, string> = {
  model_completed: "模型完成回答",
  evidence_opened: "已取得可核验证据",
  citation_validation_fallback: "模型输出未通过引用校验",
  no_opened_evidence: "没有打开可核验证据",
  no_evidence: "知识库证据不足",
  max_tool_calls: "达到工具调用上限",
  max_turns: "达到最大探索轮数",
  budget_forced_final: "工具预算结束后强制收尾",
  evidence_recovery_final: "编排器补全证据后完成回答",
  deadline_exceeded: "达到探索时间上限",
}

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
    if (askMutation.isPending) return []
    if (answer?.execution) return answer.citations
    if (answer?.citations.length) return answer.citations
    return searchQuery.data ?? []
  }, [answer, askMutation.isPending, searchQuery.data])

  return (
    <section className="grid gap-5">
      <PageHeader
        eyebrow="带出处的自然语言问答"
        title="智能问答"
        description="Agent 可自主搜索本地论文库、按需打开证据，再生成带出处的回答。"
      />

      <form className="grid gap-3 rounded-lg border bg-card p-3 md:grid-cols-[auto_minmax(0,1fr)_auto]" onSubmit={onAsk}>
        <MessageSquareText className="mt-3 hidden size-5 text-muted-foreground md:block" />
        <Input
          className="h-11"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          aria-label="问答问题"
          maxLength={2000}
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
          <AlertDescription>请检查输入长度、后端服务或真实模型配置后重试。</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(340px,0.82fr)]">
        <Card className="min-h-[430px]">
          <CardHeader className="flex flex-row items-center justify-between gap-3">
            <CardTitle className="inline-flex items-center gap-2 text-lg">
              <Brain className="size-4" />
              回答
            </CardTitle>
            {answer && !askMutation.isPending ? <Badge className="rounded-full">证据支持度 {(answer.confidence * 100).toFixed(0)}%</Badge> : null}
          </CardHeader>
          <CardContent>
            {askMutation.isPending ? (
              <LoadingState label="Agent 正在搜索并打开证据" />
            ) : answer ? (
              <div className="grid gap-4">
                <MarkdownBlock content={answer.answer} />
                <Progress value={Math.min(100, answer.confidence * 100)} aria-label={`证据支持度 ${(answer.confidence * 100).toFixed(0)}%`} />
                <div className="flex flex-wrap gap-2">
                  {answer.agent_trace.map((agent) => (
                    <Badge key={agent} variant="secondary" className="rounded-full">
                      {agent}
                    </Badge>
                  ))}
                </div>
                {answer.execution ? (
                  <div className="grid gap-3 border-t pt-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="inline-flex items-center gap-2 text-sm font-medium">
                        <Search className="size-4 text-primary" />
                        Agent 探索路径
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline" className="rounded-full">
                          {executionLabels[answer.execution.mode] ?? answer.execution.mode}
                        </Badge>
                        <Badge variant="secondary" className="rounded-full">
                          {answer.execution.tool_call_count} 次工具调用
                        </Badge>
                        <Badge
                          variant={answer.execution.status === "failed" ? "destructive" : answer.execution.status === "fallback" ? "secondary" : "outline"}
                          className="rounded-full"
                        >
                          {statusLabels[answer.execution.status] ?? answer.execution.status}
                        </Badge>
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground">
                      停止原因：{stopReasonLabels[answer.execution.stop_reason] ?? answer.execution.stop_reason}
                    </p>
                    {answer.execution.steps.length ? (
                      <ol className="grid gap-2" aria-label="Agent 工具调用记录">
                        {answer.execution.steps.map((step) => (
                          <li
                            key={`${step.index}-${step.tool}`}
                            className="grid min-w-0 grid-cols-[28px_minmax(0,1fr)_auto] items-center gap-2 rounded-md border bg-muted/35 px-3 py-2 text-sm"
                          >
                            <span className="grid size-7 place-items-center rounded-full bg-background text-xs font-semibold text-muted-foreground">
                              {step.index}
                            </span>
                            <span className="min-w-0 truncate">
                              {toolLabels[step.tool] ?? step.tool}
                              {step.note ? <span className="ml-2 text-muted-foreground">{step.note}</span> : null}
                            </span>
                            <span className="whitespace-nowrap text-xs text-muted-foreground">{step.result_count} 条结果</span>
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <p className="text-sm text-muted-foreground">本次使用单轮问答，没有工具探索步骤。</p>
                    )}
                  </div>
                ) : null}
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
              已打开的证据
            </CardTitle>
            <Badge variant="secondary" className="rounded-full">
              {evidence.length} 条
            </Badge>
          </CardHeader>
          <CardContent className="grid gap-2">
            {askMutation.isPending ? <LoadingState label="Agent 正在探索证据" /> : null}
            {!askMutation.isPending && searchQuery.isLoading && !evidence.length && !answer?.execution ? <LoadingState label="正在检索证据" /> : null}
            {evidence.map((item) => (
              <Link
                key={`${item.paper_id}-${item.source ?? "wiki"}-${item.chunk_id ?? item.id}-${item.score}`}
                to={`/papers/${item.paper_id}`}
                className="grid min-h-24 min-w-0 gap-1 rounded-lg border bg-background p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <strong className="line-clamp-2 text-sm [overflow-wrap:anywhere]">{item.paper_title}</strong>
                <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  {item.evidence_id ? `${item.evidence_id} · ` : ""}
                  {item.section_title}
                  {item.source === "chunk" && item.chunk_index !== undefined ? ` · #${item.chunk_index + 1}` : ""}
                  {" · "}
                  {sourceLabels[item.source_type ?? item.source ?? "wiki"] ?? item.source_type ?? item.source ?? "Wiki"}
                  {" · "}
                  匹配度 {(item.score * 100).toFixed(0)}%
                </span>
                <p className="line-clamp-2 text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">
                  <FileSearch className="mr-1 inline size-3.5" aria-hidden="true" />
                  {plainSnippet(item.content)}
                </p>
              </Link>
            ))}
            {!evidence.length && !askMutation.isPending && (!searchQuery.isLoading || Boolean(answer?.execution)) ? (
              <AppEmptyState title={answer?.execution ? "本次 Agent 未打开可核验证据" : "暂无证据片段"} />
            ) : null}
          </CardContent>
        </Card>
      </div>
    </section>
  )
}
