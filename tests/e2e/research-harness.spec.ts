import { expect, test, type Page } from "@playwright/test"

const now = "2026-07-16T10:00:00Z"
const stepTitles = [
  "理解研究目标", "制定检索计划", "检索本地论文库", "搜索 arXiv 候选", "去重并导入候选",
  "筛选候选论文", "获取并解析全文", "检索正文与定位证据", "抽取结构化阅读卡", "完成调研数据集",
  "制定综合计划", "构建论文对比矩阵", "生成跨论文主张", "登记引用", "严格校验引用", "生成研究报告", "完成可追溯研究报告",
]
const stepKeys = [
  "brief", "query_planning", "local_search", "arxiv_search", "dedup_import", "screening", "fulltext_acquisition", "reading", "extraction", "finalize_dataset",
  "synthesis_planning", "comparison_matrix", "cross_paper_claims", "citation_registry", "citation_verification", "report_generation", "finalize_cited_report",
]
const sourceHash = "a".repeat(64)
const evidenceId = `EV-${"a".repeat(24)}`

function topicRun(id: string, title: string, status = "completed") {
  const waiting = status === "waiting_input"
  return {
    id, user_id: 1, thread_id: "e2e-thread", title, goal: title, mode: "topic", status,
    requested_action: null, state_version: status === "completed" ? 20 : 8, plan_version: 1,
    budget: { kind: "topic", max_candidates: 50, max_fulltext_papers: 12, max_model_calls: 40, max_tool_calls: 100, max_wall_clock_seconds: 1800 },
    usage: { candidate_papers: 3, fulltext_papers: 1, model_calls: 8, tool_calls: 11, successful_calls: 19, failed_calls: 0, wall_clock_seconds: 42 },
    error_code: status === "failed" ? "tool_timeout" : null,
    error_message: status === "failed" ? "研究工具执行超时，可从检查点重试。" : null,
    created_at: now, started_at: now, updated_at: now, completed_at: status === "completed" ? now : null,
    latest_event_id: 20,
    steps: stepTitles.map((stepTitle, index) => ({
      id: `step-${index}`, run_id: id,
      step_key: stepKeys[index],
      step_type: `topic.${index}`, title: stepTitle,
      agent_name: index < 1 || index === 9 || index === 16 ? "Coordinator Agent" : index < 4 ? "Search Agent" : index === 5 ? "Screening Agent" : index < 8 ? "Reader Agent" : index === 8 ? "Extraction Agent" : index === 11 ? "Comparison Agent" : index === 14 ? "Citation Verifier Agent" : index === 15 ? "Report Agent" : "Synthesis Agent",
      status: waiting && index === 6 ? "waiting_input" : status === "failed" && index === 6 ? "failed" : (waiting && index > 6) || (status === "failed" && index > 6) ? "queued" : "completed",
      position: index, attempt_count: 1, max_attempts: 3,
      output: index === 2 ? { candidate_count: 2, tool_calls: [{ tool: "local_paper_search", status: "completed", attempt: 1, summary: "本地检索返回 2 篇论文", duration_ms: 18 }] } : {},
      started_at: now, completed_at: waiting && index >= 6 ? null : status === "failed" && index >= 6 ? null : now,
    })),
    decisions: waiting ? [{
      id: "budget-decision", run_id: id, step_id: "step-6", status: "pending",
      question: "继续执行将超过本次调研预算，请选择下一步。", recommended_option: "narrow_scope",
      options: [
        { id: "continue", label: "继续并提高预算", description: "提高受控上限后继续。" },
        { id: "narrow_scope", label: "缩小范围", description: "冻结当前规模并完成收尾。" },
        { id: "stop", label: "停止任务", description: "保留已完成数据。" },
      ], created_at: now,
    }] : [],
  }
}

function topicArtifacts(id: string) {
  const base = { run_id: id, schema_version: 1, version: 1, status: "completed", source_step_id: "step-0", is_current: true, created_at: now, updated_at: now }
  return [
    { ...base, id: "brief-artifact", artifact_type: "research_brief", content: { topic: "RAG 证据链", research_questions: ["如何评估检索证据质量？"], scope: "2023–2026 年带实证评估的论文", inclusion_criteria: ["包含实验"], exclusion_criteria: ["非论文"], date_range: { start_year: 2023, end_year: 2026 }, preferred_sources: ["local", "arxiv"], output_language: "zh-CN", constraints: [], schema_version: 1 } },
    { ...base, id: "paper-brief-artifact", artifact_type: "paper_brief", paper_id: 101, source_hash: sourceHash, source_step_id: "step-8", content: { paper_id: 101, source: "arxiv", source_id: "2501.00001", title: "A Very Long Paper Title About Retrieval-Augmented Generation Evidence Grounding Without Horizontal Overflow on Mobile Screens", authors: ["Ada Lovelace"], year: 2025, research_question: "检索证据如何提高可追溯性？", method: "先检索正文块，再基于白名单证据生成回答。", dataset: "CitationBench", experiments: "引用准确率与检索召回率", key_findings: ["证据约束提高引用准确率。"], limitations: ["仅评估英文数据。"], relevance: "直接回答研究问题。", evidence_ids: [{ evidence_id: evidenceId, chunk_id: 501, paper_id: 101, source_hash: sourceHash, chunk_index: 0, char_start: 0, char_end: 120, heading: "Method" }], source_hash: sourceHash, schema_version: 1 } },
    { ...base, id: "synthesis-plan", artifact_type: "synthesis_plan", source_step_id: "step-10", content: { topic: "RAG 证据链", research_questions: ["如何评估检索证据质量？"], comparison_dimensions: ["引用准确率", "证据覆盖"], synthesis_strategy: "仅综合已打开且通过当前 source hash 校验的 Chunk Evidence。", expected_outputs: ["论文对比矩阵", "可追溯研究报告"], constraints: ["事实性结论必须带引用"], schema_version: 1 } },
    { ...base, id: "comparison-matrix", artifact_type: "comparison_matrix", source_step_id: "step-11", content: { dimensions: ["引用准确率"], papers: [{ paper_id: 101, title: "A Very Long Paper Title About Retrieval-Augmented Generation Evidence Grounding Without Horizontal Overflow on Mobile Screens" }], cells: [{ cell_id: "cell-1", dimension: "引用准确率", paper_id: 101, value: "白名单证据约束提高引用准确率。", citation_keys: ["C1"], evidence_ids: [evidenceId] }], agreements: [{ statement_id: "agreement-1", text: "证据约束是可追溯回答的共同基础。", citation_keys: ["C1"] }], disagreements: [], missing_evidence: [{ dimension: "多语言迁移", paper_id: 101, uncertainty: "当前证据只覆盖英文数据。" }], schema_version: 1 } },
    { ...base, id: "synthesis-claims", artifact_type: "synthesis_claims", source_step_id: "step-12", content: { claims: [{ claim_id: "claim-1", claim: "证据约束提高引用准确率。", claim_type: "finding", confidence: 0.91, supporting_citations: ["C1"], contradicting_citations: [], covered_paper_ids: [101], caveats: ["仅评估英文数据"], schema_version: 1 }], schema_version: 1 } },
    { ...base, id: "citation-registry", artifact_type: "citation_registry", version: 2, source_step_id: "step-13", content: { entries: [{ citation_key: "C1", claim_id: "claim-1", paper_id: 101, chunk_id: 501, evidence_id: evidenceId, source: "arxiv", source_id: "2501.00001", source_hash: sourceHash, heading: "Method", char_start: 0, char_end: 120 }], schema_version: 1 } },
    { ...base, id: "citation-validation", artifact_type: "citation_validation_result", source_step_id: "step-14", content: { valid_citation_keys: ["C1"], stale_citation_keys: [], inaccessible_citation_keys: [], invalid_citation_keys: [], verified_claim_ids: ["claim-1"], schema_version: 1 } },
    currentReport(id),
  ]
}

function reportContent(title: string, registryVersion = 2) {
  const cited = (statement_id: string, text: string) => ({ statement_id, text, citation_keys: ["C1"] })
  return { title, topic: "RAG 证据链", executive_summary: [cited("summary-1", "证据白名单能提高调研结论的可追溯性。")], research_questions: ["如何评估检索证据质量？"], findings: [cited("finding-1", "证据约束提高引用准确率。")], agreements: [cited("report-agreement-1", "来源哈希校验是引用有效性的基础。")], disagreements: [], limitations: ["当前仅纳入一篇满足条件的论文。"], research_gaps: ["仍需验证多语言论文。"], conclusion: [cited("conclusion-1", "报告结论可追溯到当前有效 Chunk Evidence。")], citation_keys: ["C1"], generated_from_artifact_versions: { synthesis_plan: 1, comparison_matrix: 1, synthesis_claims: 1, citation_registry: registryVersion, citation_validation_result: 1 }, schema_version: 1 }
}

function currentReport(id: string) {
  return { id: "research-report-v2", run_id: id, artifact_type: "research_report", schema_version: 1, source_step_id: "step-15", version: 2, status: "completed", content: reportContent("可追溯 RAG 证据链研究报告"), source_hash: null, is_current: true, created_at: now, updated_at: now }
}

function topicReports(id: string) {
  return [
    { ...currentReport(id), id: "research-report-v1", version: 1, is_current: false, status: "stale", content: reportContent("历史 RAG 证据链研究报告", 1) },
    currentReport(id),
  ]
}

function topicCitations(id: string) {
  const current = { id: "citation-1", run_id: id, artifact_id: "citation-registry", artifact_version: 2, citation_key: "C1", claim_id: "claim-1", paper_id: 101, chunk_id: 501, evidence_id: evidenceId, source: "arxiv", source_id: "2501.00001", source_hash: sourceHash, heading: "Method", char_start: 0, char_end: 120, quote_hash: "b".repeat(64), status: "valid", created_at: now, updated_at: now }
  return [
    { ...current, id: "citation-old", artifact_id: "citation-registry-v1", artifact_version: 1, status: "stale" },
    { id: "citation-inaccessible", run_id: id, artifact_id: "citation-registry-v1", artifact_version: 1, citation_key: "C2", status: "inaccessible", created_at: now, updated_at: now },
    { ...current, id: "citation-invalid", artifact_id: "citation-registry-v1", artifact_version: 1, citation_key: "C3", status: "invalid" },
    current,
  ]
}

function topicPapers(id: string) {
  const base = { run_id: id, source_step_id: "step-5", source: "arxiv", source_hash: sourceHash, authors: ["Ada Lovelace"], abstract: "Evidence-grounded retrieval.", published_at: "2025-01-01", primary_category: "cs.CL", source_url: "https://arxiv.org/abs/2501.00001", processing_status: "processed", created_at: now, updated_at: now }
  return [
    { ...base, paper_id: 101, source_id: "2501.00001", stage: "extracted", rank: 1, score: 0.96, inclusion_reason: "直接评估证据可追溯性", exclusion_reason: null, title: "A Very Long Paper Title About Retrieval-Augmented Generation Evidence Grounding Without Horizontal Overflow on Mobile Screens" },
    { ...base, paper_id: 102, source_id: "2501.00002", stage: "excluded", rank: null, score: 0.21, inclusion_reason: null, exclusion_reason: "没有报告可复核的实证结果", title: "A Survey Without Empirical Evaluation" },
    { ...base, paper_id: 103, source_id: "2501.00003", stage: "candidate", rank: null, score: null, inclusion_reason: null, exclusion_reason: null, title: "Candidate Awaiting Screening" },
  ]
}

async function installTopicFixtures(page: Page, state: { status: string; title: string }) {
  await page.route("**/api/research/runs/**", async (route) => {
    const url = new URL(route.request().url())
    const match = url.pathname.match(/\/api\/research\/runs\/([^/]+)/)
    if (!match) return route.fallback()
    const runId = match[1]
    if (url.pathname.endsWith("/events")) return route.fulfill({ status: 200, contentType: "text/event-stream", body: "" })
    const citationEvidence = url.pathname.match(/\/citations\/(citation-1|citation-old)\/evidence$/)?.[1]
    if (citationEvidence) {
      const citation = topicCitations(runId).find((item) => item.id === citationEvidence)!
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...citation, excerpt: citation.status === "valid" ? "Evidence-constrained generation improves citation accuracy." : null }) })
    }
    if (url.pathname.endsWith("/citations")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: topicCitations(runId) }) })
    if (url.pathname.endsWith("/reports")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: topicReports(runId) }) })
    if (url.pathname.endsWith("/report-regeneration") && route.request().method() === "POST") { state.status = "running"; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(topicRun(runId, state.title, state.status)) }) }
    if (url.pathname.endsWith("/artifacts")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: topicArtifacts(runId) }) })
    if (url.pathname.endsWith("/papers")) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: topicPapers(runId) }) })
    const action = url.pathname.match(/\/(pause|resume|cancel|retry)$/)?.[1]
    if (action && route.request().method() === "POST") {
      state.status = action === "pause" ? "paused" : action === "cancel" ? "cancelled" : "running"
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(topicRun(runId, state.title, state.status)) })
    }
    if (url.pathname === `/api/research/runs/${runId}`) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(topicRun(runId, state.title, state.status)) })
    return route.fallback()
  })
  await page.route("**/api/research/decisions/*/resolve", async (route) => {
    state.status = "running"
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(topicRun("control-run", state.title, state.status)) })
  })
}

async function register(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "没有账户？创建账户" }).click()
  await page.getByLabel("用户名").fill(`e2e_${Date.now()}_${Math.floor(Math.random() * 10000)}`)
  await page.getByLabel("密码").fill("playwright-password")
  await page.getByRole("button", { name: "注册并登录" }).click()
  await expect(page.getByRole("button", { name: "打开任务中心" })).toBeVisible()
  await expect(page.getByPlaceholder("输入问题，Enter 发送…")).toBeVisible()
}

async function selectAnswerMode(page: Page, label: "自动判断" | "普通对话" | "深度研究") {
  const trigger = page.getByRole("combobox", { name: "回答模式" })
  await trigger.click()
  await page.getByRole("option", { name: label }).click()
}

test("routes deep research into a persisted data card and responsive workflow", async ({ page }, testInfo) => {
  const errors: string[] = []
  await page.emulateMedia({ reducedMotion: "reduce" })
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("401 (Unauthorized)")) errors.push(message.text())
  })
  await register(page)
  expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true)

  if (testInfo.project.name === "mobile-390") {
    for (const target of [page.getByLabel("回答模式"), page.getByRole("button", { name: "发送" })]) {
      expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
  }

  const taskTrigger = page.getByRole("button", { name: "打开任务中心" })
  await taskTrigger.focus()
  await taskTrigger.click()
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible()
  await expect(page.getByText("新建 Harness 骨架")).toHaveCount(0)
  await page.keyboard.press("Escape")
  await expect(taskTrigger).toBeFocused()

  await selectAnswerMode(page, "深度研究")
  const title = `Playwright Topic ${testInfo.project.name}`
  const state = { status: "completed", title }
  await installTopicFixtures(page, state)
  await page.getByPlaceholder("输入问题，Enter 发送…").fill(`${title}\n验证真实主题调研数据链路`)
  await page.getByRole("button", { name: "发送" }).click()
  const card = page.getByRole("region", { name: new RegExp(title) })
  await expect(card).toBeVisible()
  await expect(card.getByText("真实可恢复数据链路", { exact: false })).toBeVisible()
  const openButton = card.getByRole("button", { name: "查看 Workflow" })
  await openButton.focus()
  await openButton.click()
  await expect(page).toHaveURL(/\?thread=.*&run=/)
  let workflow = testInfo.project.name === "desktop-1440" ? page.locator("aside:visible") : page.locator('[role="dialog"]:visible')
  await expect(workflow.getByRole("heading", { name: title })).toBeVisible()
  await expect(workflow.getByRole("heading", { name: "RAG 证据链" })).toBeVisible()
  await expect(workflow.getByLabel("实际预算使用").getByText("8/40")).toBeVisible()
  await workflow.getByRole("button", { name: /搜集论文/ }).click()
  const localStep = workflow.getByRole("button", { name: /检索本地论文库/ })
  await localStep.click()
  await expect(workflow.getByText("本地检索返回 2 篇论文")).toBeVisible()
  await workflow.getByRole("tab", { name: "数据集" }).click()
  await workflow.getByRole("tab", { name: "论文", exact: true }).click()
  await expect(workflow.getByText("直接评估证据可追溯性")).toBeVisible()
  await expect(workflow.getByText("没有报告可复核的实证结果")).toBeVisible()
  await expect(workflow.getByText("Candidate Awaiting Screening")).toBeVisible()
  await workflow.getByRole("button", { name: "全文就绪" }).click()
  await expect(workflow.getByText(/A Very Long Paper Title/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
  await workflow.getByRole("tab", { name: "阅读卡", exact: true }).click()
  const briefButton = workflow.getByRole("button", { name: /A Very Long Paper Title/ })
  await briefButton.click()
  await expect(workflow.getByText("证据约束提高引用准确率。")).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
  await workflow.getByRole("tab", { name: "综合报告" }).click()
  await expect(workflow.getByRole("heading", { name: "可追溯 RAG 证据链研究报告" })).toBeVisible()
  await expect(workflow.getByText("证据白名单能提高调研结论的可追溯性。")).toBeVisible()
  const fullReportLink = workflow.getByRole("link", { name: "打开完整报告" })
  await fullReportLink.click()
  await expect(page).toHaveURL(/\/runs\/[^/]+\/reports\/2/)
  if (testInfo.project.name === "mobile-390") {
    await page.getByRole("combobox", { name: "报告内容" }).click()
    await page.getByRole("option", { name: "引用", exact: true }).click()
  } else {
    await page.getByRole("tab", { name: "引用", exact: true }).click()
  }
  const citationButton = page.getByRole("button", { name: /引用 1/ }).first()
  await citationButton.focus()
  await page.keyboard.press("Enter")
  await expect(page.getByText("Evidence-constrained generation improves citation accuracy.")).toBeVisible()
  await expect(page.getByText("Method", { exact: true })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(citationButton).toBeFocused()
  await page.goBack()
  workflow = testInfo.project.name === "desktop-1440" ? page.locator("aside:visible") : page.locator('[role="dialog"]:visible')
  await workflow.getByRole("tab", { name: "综合报告" }).click()
  const versionSelect = workflow.getByLabel("版本")
  await versionSelect.selectOption("1")
  await expect(workflow.getByText(/这是历史版本/)).toBeVisible()
  await expect(workflow.getByRole("heading", { name: "历史 RAG 证据链研究报告" })).toBeVisible()
  await versionSelect.selectOption("2")
  await expect(workflow.getByRole("heading", { name: "可追溯 RAG 证据链研究报告" })).toBeVisible()
  if (testInfo.project.name === "mobile-390") {
    for (const target of [fullReportLink, versionSelect, workflow.getByRole("button", { name: "生成新版本" })]) expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  await workflow.getByRole("button", { name: "生成新版本" }).click()
  await expect.poll(() => state.status).toBe("running")
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)

  if (testInfo.project.name !== "desktop-1440") {
    const close = page.getByRole("button", { name: "关闭 Workflow" })
    await close.click()
    await expect(openButton).toBeFocused()
    await openButton.click()
  }

  await page.reload()
  workflow = testInfo.project.name === "desktop-1440" ? page.locator("aside:visible") : page.locator('[role="dialog"]:visible')
  await expect(workflow.getByRole("heading", { name: title })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
  if (testInfo.project.name === "mobile-390") {
    expect((await workflow.getByRole("button", { name: "关闭 Workflow" }).boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    for (const tab of await workflow.getByRole("tab").all()) expect((await tab.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  const theme = page.getByRole("button", { name: "切换到深色主题" })
  if (await theme.isVisible()) { await theme.click(); await expect(page.locator("html")).toHaveClass(/dark/) }
  if (testInfo.project.name !== "desktop-1440") await page.getByRole("button", { name: "关闭 Workflow" }).click()
  await taskTrigger.click()
  const runInCenter = page.getByRole("button", { name: new RegExp(title) })
  await expect(runInCenter).toBeVisible()
  await runInCenter.click()
  await expect(page.getByRole("heading", { name: title }).last()).toBeVisible()
  await page.getByRole("button", { name: "返回任务中心" }).click()
  await page.keyboard.press("Escape")
  await expect(taskTrigger).toBeFocused()
  expect(errors).toEqual([])
})

test("handles budget decision and safe run controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "control state machine runs once on desktop")
  await register(page)
  const state = { status: "waiting_input", title: "Budget control topic" }
  await installTopicFixtures(page, state)
  await page.goto("/runs/control-run")
  const decision = page.getByRole("heading", { name: "继续执行将超过本次调研预算，请选择下一步。" })
  await expect(decision).toBeVisible()
  await expect(decision.locator("..")).toBeFocused()
  await page.getByRole("button", { name: /缩小范围/ }).click()
  await expect(page.getByRole("button", { name: "暂停" })).toBeVisible()
  await page.getByRole("button", { name: "暂停" }).click()
  await expect(page.getByRole("button", { name: "继续" })).toBeVisible()
  await page.getByRole("button", { name: "继续" }).click()
  await page.getByRole("button", { name: "停止" }).click()
  await expect(page.getByRole("alertdialog")).toBeVisible()
  await page.getByRole("button", { name: "返回" }).click()
  await page.getByRole("button", { name: "停止" }).click()
  await page.getByRole("button", { name: "确认停止" }).click()
  await expect(page.getByText("已取消", { exact: true })).toBeVisible()
  state.status = "failed"
  await page.reload()
  await page.getByRole("button", { name: "重试" }).click()
  await expect(page.getByRole("button", { name: "暂停" })).toBeVisible()
})

test("keeps normal chat streaming, reload and explicit fork outside Research", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "ordinary Chat regression runs once on desktop")
  await register(page)
  let routeCalls = 0
  let chatRunCalls = 0
  await page.route("**/api/chat/route", async (route) => {
    routeCalls += 1
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ route: "normal_chat", reason: "explicit" }) })
  })
  await page.route("**/api/chat/runs", async (route) => {
    chatRunCalls += 1
    const content = `普通回答 ${chatRunCalls}`
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: text.delta\ndata: ${JSON.stringify({ delta: content })}\n\nevent: message.completed\ndata: ${JSON.stringify({ content })}\n\n`,
    })
  })
  await selectAnswerMode(page, "普通对话")
  await page.getByPlaceholder("输入问题，Enter 发送…").fill("这是普通问题")
  await page.getByRole("button", { name: "发送" }).click()
  await expect(page.getByText("普通回答 1", { exact: true })).toBeVisible()
  await expect(page.getByRole("region", { name: /Research Run/ })).toHaveCount(0)

  await page.getByRole("button", { name: "重新生成一个分支" }).click()
  await expect(page.getByText("普通回答 2", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "分叉", exact: true }).last().click()
  await page.getByPlaceholder("输入新分支中的下一条问题…").fill("继续普通分支")
  await page.getByRole("button", { name: "创建分支" }).click()
  await expect(page.getByText("普通回答 3", { exact: true })).toBeVisible()
  expect(routeCalls).toBe(2)
  expect(chatRunCalls).toBe(3)
})

test("keeps Paper Chat outside the Research route", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "Paper Chat regression runs once on desktop")
  await register(page)
  let researchRouteCalls = 0
  await page.route("**/api/chat/route", async (route) => {
    researchRouteCalls += 1
    await route.fulfill({ status: 500, body: "Paper Chat must not route here" })
  })
  await page.route("**/api/papers/101", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
    id: 101, source: "arxiv", source_id: "2501.00001", source_url: "https://arxiv.org/abs/2501.00001",
    title: "Paper Chat Fixture", authors: ["Ada Lovelace"], abstract: "Fixture abstract", categories: ["cs.CL"], primary_category: "cs.CL", published_at: "2025-01-01", processing_status: "processed", is_favorite: false,
    pdf: { available: false, cached: false, view_url: null, download_url: null }, upload: null, wiki: [], concepts: [], notes: [], summaries: [],
    document: { parser_name: "docling", parser_version: "fixture", source_hash: "a".repeat(64), content_markdown: "# Paper\n\nGrounded full text.", token_count: 8, status: "completed", parsed_at: now },
  }) }))
  await page.route("**/api/papers/101/chunks**", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) }))
  await page.route("**/api/papers/101/chat/threads", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: "paper-thread", paper_id: 101, title: "论文对话", message_token_limit: 12000, archived: false, created_at: now, updated_at: now }] }) }))
  await page.route("**/api/chat/threads/paper-thread/messages", async (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ messages: [] }) }))
  await page.route("**/api/chat/runs", async (route) => {
    const content = "论文正文回答"
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: `event: text.delta\ndata: ${JSON.stringify({ delta: content })}\n\nevent: message.completed\ndata: ${JSON.stringify({ content })}\n\n` })
  })
  await page.goto("/papers/101")
  await expect(page.getByPlaceholder("针对这篇论文提问…")).toBeVisible()
  await expect(page.getByLabel("回答模式")).toHaveCount(0)
  await page.getByPlaceholder("针对这篇论文提问…").fill("解释方法")
  await page.getByRole("button", { name: "发送" }).click()
  await expect(page.getByText("论文正文回答", { exact: true })).toBeVisible()
  expect(researchRouteCalls).toBe(0)
  await expect(page.getByRole("region", { name: /Research Run/ })).toHaveCount(0)
})
