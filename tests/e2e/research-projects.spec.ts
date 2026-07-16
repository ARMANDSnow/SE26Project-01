import { expect, test, type Page } from "@playwright/test"

const now = "2026-07-16T10:00:00Z"
const projectId = "project-e2e"

async function register(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "没有账户？创建账户" }).click()
  await page.getByLabel("用户名").fill(`project_${Date.now()}_${Math.floor(Math.random() * 10000)}`)
  await page.getByLabel("密码").fill("playwright-password")
  await page.getByRole("button", { name: "注册并登录" }).click()
  await expect(page.getByRole("button", { name: "打开任务中心" })).toBeVisible()
}

function projectRun(status: "waiting_input" | "completed") {
  const titles = ["校验项目资料", "规划研究脉络", "生成主题簇", "构建研究时间线", "构建关系图", "核验图谱与引用", "完成研究脉络"]
  return {
    id: "project-run", user_id: 1, project_id: projectId, thread_id: null,
    title: "项目研究脉络", goal: "梳理可追溯 RAG 研究", mode: "project", status,
    requested_action: null, state_version: 8, plan_version: 1,
    budget: { kind: "project", max_candidates: 50, max_fulltext_papers: 50, max_model_calls: 3, max_tool_calls: 20, max_wall_clock_seconds: 900 },
    usage: { candidate_papers: 2, fulltext_papers: 2, model_calls: 2, tool_calls: 5, successful_calls: 7, failed_calls: 0, wall_clock_seconds: 21 },
    error_code: null, error_message: null, created_at: now, started_at: now, updated_at: now,
    completed_at: status === "completed" ? now : null, latest_event_id: 8,
    steps: titles.map((title, index) => ({
      id: `project-step-${index}`, run_id: "project-run", step_key: `project-${index}`,
      step_type: `project.${index}`, title, agent_name: "Project Agent",
      status: status === "waiting_input" && index === 0 ? "waiting_input" : status === "waiting_input" ? "queued" : "completed",
      position: index, attempt_count: 1, max_attempts: 2, output: {},
      started_at: now, completed_at: status === "completed" ? now : null,
    })),
    decisions: status === "waiting_input" ? [{
      id: "project-decision", run_id: "project-run", step_id: "project-step-0", status: "pending",
      question: "当前引用覆盖有限，请选择下一步。", recommended_option: "deterministic_timeline",
      options: [
        { id: "add_more_sources", label: "添加更多资料", description: "返回项目继续补充。" },
        { id: "deterministic_timeline", label: "仅生成确定性时间线", description: "不推断影响关系。" },
        { id: "stop", label: "停止", description: "保留当前资料。" },
      ], created_at: now,
    }] : [],
  }
}

function artifact(type: "topic_clusters" | "research_timeline" | "research_graph", version = 2) {
  const stale = version === 1
  const content = type === "topic_clusters" ? {
    clusters: [{ cluster_id: "cluster-grounding", label: "证据约束检索", summary: "当前有效论文共同使用可核验证据约束。", paper_ids: [101, 102], claim_ids: ["claim-1"], citation_keys: ["PC1"], summary_citation_keys: ["PC1"], distinguishing_features: [{ statement_id: "feature-1", text: "在生成前固定证据白名单。", citation_keys: ["PC1"] }], uncertainties: [], schema_version: 1 }],
    unclassified_paper_ids: [], citation_keys: ["PC1"], uncertainties: [], schema_version: 1,
  } : type === "research_timeline" ? {
    events: [
      { event_id: "publication-101", date: "2024-01-01", date_range: null, event_type: "publication", title: "第一篇论文发布", description: "已验证元数据日期。", paper_ids: [101], claim_ids: [], citation_keys: [], confidence: 1 },
      { event_id: "improvement-102", date: "2025-01-01", date_range: null, event_type: "improvement", title: "证据核验得到改进", description: "后续工作扩展了证据核验。", paper_ids: [102], claim_ids: ["claim-1"], citation_keys: ["PC1"], confidence: 0.86 },
    ], periods: [], turning_points: [], unresolved_questions: ["多语言场景仍待验证。"], citation_keys: ["PC1"], schema_version: 1,
  } : {
    nodes: [
      { node_id: `project:${projectId}`, node_type: "project", label: "可追溯 RAG 研究", entity_ref: projectId, status: "valid" },
      { node_id: "paper:101", node_type: "paper", label: "Grounded Retrieval", entity_ref: "paper:101", status: "valid" },
      { node_id: "claim:1", node_type: "synthesis_claim", label: "证据约束提高可追溯性", entity_ref: "claim-1", status: "valid" },
    ],
    edges: [
      { edge_id: "contains-1", source_node_id: `project:${projectId}`, target_node_id: "paper:101", relation_type: "contains", citation_keys: [], status: "valid" },
      { edge_id: "supports-1", source_node_id: "paper:101", target_node_id: "claim:1", relation_type: "supports", citation_keys: ["PC1"], status: "valid" },
    ], citation_keys: ["PC1"], schema_version: 1,
  }
  return {
    id: `${type}-v${version}`, project_id: projectId, run_id: "project-run", artifact_type: type,
    version, status: stale ? "stale" : "completed", dependency_status: stale ? "stale" : "current",
    is_current: !stale, content: stale ? null : content, input_item_ids: ["item-run", "item-paper", "item-report"],
    citation_keys: stale ? [] : ["PC1"], created_at: now, updated_at: now,
  }
}

async function installProjectFixtures(page: Page) {
  const state = { created: false, analysisStatus: "waiting_input" as "waiting_input" | "completed" }
  await page.route("**/api/research/decisions/project-decision/resolve", async (route) => {
    state.analysisStatus = "completed"
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(projectRun("completed")) })
  })
  await page.route("**/api/research/projects**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    const json = (value: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) })
    const project = { id: projectId, owner_user_id: 1, title: "可追溯 RAG 研究", description: "梳理论文、主张和引用之间的有效关系。", status: "active", item_count: 3, current_item_count: 3, stale_item_count: 0, inaccessible_item_count: 0, latest_analysis_run_id: "project-run", latest_analysis_status: state.analysisStatus, created_at: now, updated_at: now }
    if (path === "/api/research/projects" && route.request().method() === "POST") { state.created = true; return json(project, 201) }
    if (path === "/api/research/projects") return json({ items: state.created && url.searchParams.get("status") !== "archived" ? [project] : [] })
    if (path.endsWith("/items")) return json({ items: [
      { id: "item-run", project_id: projectId, item_type: "run", run_id: "topic-run", position: 0, dependency_status: "current", title: "RAG 调研任务", subtitle: "固定研究范围", added_at: now, updated_at: now },
      { id: "item-paper", project_id: projectId, item_type: "paper", paper_id: 101, position: 1, dependency_status: "current", title: "Grounded Retrieval", subtitle: "Ada", added_at: now, updated_at: now },
      { id: "item-report", project_id: projectId, item_type: "research_report", artifact_id: "report-v2", artifact_version: 2, position: 2, dependency_status: "current", title: "可追溯研究报告", subtitle: "固定报告版本", added_at: now, updated_at: now },
    ], project_revision: 3 })
    if (path.endsWith("/coverage")) return json({ status: "ready", total_items: 3, current_items: 3, stale_items: 0, inaccessible_items: 0, paper_count: 2, report_count: 1, valid_citation_count: 1, missing_inputs: [], warnings: [], can_analyze: true, updated_at: now })
    if (path.endsWith("/analysis")) return json({ project_id: projectId, run: projectRun(state.analysisStatus), tool_summaries: [] })
    const artifactView = path.match(/\/artifacts\/(topic-clusters|timeline|graph)(?:\/versions)?$/)?.[1]
    const artifactType = artifactView === "topic-clusters" ? "topic_clusters" : artifactView === "timeline" ? "research_timeline" : artifactView === "graph" ? "research_graph" : undefined
    if (artifactType && path.endsWith("/versions")) return json({ items: [artifact(artifactType, 2), artifact(artifactType, 1)] })
    if (artifactType) return json(artifact(artifactType, Number(url.searchParams.get("version") ?? 2)))
    if (path.endsWith("/entities/edge/supports-1/evidence")) return json({ entity_id: "supports-1", entity_kind: "edge", dependency_status: "current", citations: [{ citation_id: "project-citation-1", citation_label: "PC1", status: "valid", paper_id: 101, paper_title: "Grounded Retrieval", heading: "Method", excerpt: "Evidence fencing improves traceability.", chunk_id: 501, char_start: 0, char_end: 43 }] })
    if (path === `/api/research/projects/${projectId}`) return json(project)
    return route.fallback()
  })
}

async function chooseProjectView(page: Page, label: string, mobile: boolean) {
  if (!mobile) return page.getByRole("tab", { name: label }).click()
  await page.getByRole("combobox", { name: "项目内容" }).click()
  await page.getByRole("option", { name: label }).click()
}

test("creates and restores a traceable project landscape without responsive overflow", async ({ page }, testInfo) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (message) => { if (message.type() === "error" && !message.text().includes("401 (Unauthorized)")) errors.push(message.text()) })
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: testInfo.project.name === "tablet-1024" ? "dark" : "light" })
  await register(page)
  await installProjectFixtures(page)
  await page.goto("/library?view=projects")
  await page.getByLabel("项目名称").fill("可追溯 RAG 研究")
  await page.getByLabel("研究说明").fill("梳理论文、主张和引用之间的有效关系。")
  await page.getByRole("button", { name: "创建项目" }).click()
  await page.getByRole("link", { name: /可追溯 RAG 研究/ }).click()
  await expect(page.getByRole("heading", { name: "可追溯 RAG 研究" })).toBeVisible()
  await expect(page.getByText("RAG 调研任务")).toBeVisible()
  await expect(page.getByText("Grounded Retrieval")).toBeVisible()
  await expect(page.getByText("固定报告版本")).toBeVisible()
  await expect(page.getByText("模型调用")).toBeVisible()
  await page.getByText("查看七步审计记录").click()
  await expect(page.getByText("完成研究脉络")).toBeVisible()
  await page.getByRole("button", { name: /仅生成确定性时间线/ }).click()
  await expect(page.getByText(/已完成 · 7 个可审计步骤/)).toBeVisible()

  await page.reload()
  await expect(page.getByRole("heading", { name: "可追溯 RAG 研究" })).toBeVisible()
  const mobile = testInfo.project.name === "mobile-390"
  await chooseProjectView(page, "主题簇", mobile)
  await expect(page.getByRole("heading", { name: "证据约束检索" })).toBeVisible()
  await chooseProjectView(page, "时间线", mobile)
  await expect(page.getByRole("heading", { name: "证据核验得到改进" })).toBeVisible()
  await chooseProjectView(page, "关系图", mobile)
  await expect(page.getByRole("heading", { name: "研究关系图" })).toBeVisible()
  const semanticEdge = page.getByRole("button", { name: /支持/ }).last()
  await semanticEdge.focus()
  await semanticEdge.click()
  await expect(page.getByRole("heading", { name: "引用与原文证据" })).toBeVisible()
  await expect(page.getByText("Evidence fencing improves traceability.")).toBeVisible()
  await expect(page.getByText("引用 1", { exact: true })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(semanticEdge).toBeFocused()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)).toBe(false)
  if (mobile) {
    await expect(page.getByRole("group", { name: "可交互研究关系图" })).toBeHidden()
    for (const target of await page.getByRole("button").all()) {
      if (await target.isVisible()) expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
  }
  expect(errors).toEqual([])
})
