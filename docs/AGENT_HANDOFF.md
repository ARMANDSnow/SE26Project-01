# Agent Handoff

最后更新：2026-07-13，iter04 closeout 后。

## Current Status

- 项目：arXiv 智能论文阅读工具。
- 当前主分支：`main`，最近完成迭代：iter04 Agent 驱动的跨论文知识库探索。
- 当前能力：论文库、arXiv 同步、结构化 Wiki、可追溯 chunks、FTS5 trigram 预过滤、Agentic 跨论文问答、概念图谱、学习管理、关注主题、mock/real LLM 双路径。
- 默认运行方式：后端 FastAPI + SQLite，前端 Vite dev server；默认 `ENABLE_MOCK_LLM=true`、`ENABLE_FULLTEXT_FETCH=auto`、前端默认 `VITE_USE_MOCK=false`。
- 交接锚点：本文件 + `docs/iterations/README.md` + 最新 iteration 文档。

## Capability Map

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| Web 客户端 | 已具备 | Vite + React + TypeScript，包含仪表盘、论文库、论文详情、问答、图谱、学习管理。 |
| 论文抓取与管理 | 已具备基础 | `/api/ingest/arxiv` 支持 arXiv 拉取、去重统计、分类和链接入库。 |
| 论文结构化解析 | 已增强 | `process_paper` 生成可追溯 chunks、Wiki 分区和概念；非 mock 模式调用 `LLMClient.complete` 生成结构化 JSON。 |
| 正文/Chunk 索引 | 已具备基础 | `paper_chunks` 存储 source、URL、offset、token 估算和 embedding；mock/offline 使用 metadata chunks，真实路径可尝试 arXiv HTML/PDF。 |
| Wiki/Chunk 检索 | 已增强 | 可选 FTS5 trigram chunk prefilter + 关键词/deterministic embedding rerank；FTS 不可用时 fallback 到旧路径。 |
| 智能问答 | 已增强 | QA Agent 可自主调用元数据搜索、论文片段搜索和证据打开工具；支持多轮 tool calling、paper scope、执行 trace、预算/停止条件和 citation allowlist；模型在元数据阶段提前收尾时会为已处理候选自动补全可引用证据。 |
| 学习管理 | 已具备基础 | 收藏、笔记、历史、对比阅读、关注主题。 |
| 知识图谱 | 已具备基础 | 概念-论文 SVG 图谱；无匹配主题返回空图。 |
| 性能基线 | 已建立 | 100 requests / 100 workers smoke，包含 chunks/search/QA，iter03 closeout p95 `0.9062s`。 |
| 准确率基线 | 初步建立 | seed 数据上 citation/grounding 自动断言 `>= 90%`；真实 `gpt-5.5-medium` smoke 已验证两篇 HTML 论文、10 次工具调用和双论文引用。 |
| 项目 Memory/TODO | 已建立 | `docs/PROJECT_BACKLOG.md` 持久化助教建议、产品定位、已完成与待实现事项。 |

## Iteration Workflow Learned From iter01

这次 iter01 的可复用流程：

1. 先做只读 grounding：README、核心后端、前端 API、测试、性能脚本、git 状态。
2. 用户明确授权后分工 subagents：一个看功能差距，一个看 bug/质量风险；主 agent 同步跑本地验证。
3. 在 Plan Mode 输出 decision-complete 计划，包含接口、测试、假设和 scope 边界。
4. Default Mode 实施：先建 iteration record，再修后端契约，再接前端 UI，最后验证。
5. 验证顺序：后端测试 -> 前端 build -> 启动后端 -> 性能 smoke -> 关闭服务 -> diff/status 检查。
6. iter-finish：更新 closeout、记录验证和 follow-ups，最后commit；只有用户明确要求时才push。

建议后续保持这个节奏；不要把 subagent 审查结果只留在聊天里，必须写进 iteration 或 handoff。

## Automatic Iteration Protocol

触发条件：用户明确说“启动自动迭代”“起一轮迭代”“按完整迭代流执行”或给出同等授权。

触发后，本轮默认授权 agent 使用以下闭环：

1. 先调用只读 subagents 跟踪当前进度、功能不足、bug 和测试缺口。
2. 主 agent 写入本轮 iteration 文件，并同步 `docs/iterations/README.md`。
3. 主 agent 实现代码和文档改动。
4. 跑后端测试、前端构建和必要 smoke。
5. 调用 iter-finish skill 的工作流做收尾准备，但在最终 closeout 前必须完成审查。
6. 调用只读 subagents 审核本轮 diff：代码正确性、契约/测试、安全/密钥，前端相关任务加 UI/UX。
7. 主 agent 修复审查 findings，并把审查结果、修复结果、验证命令回填到 iteration closeout 和本 handoff。
8. 再次运行必要验证和 `git diff --check`。
9. 自动 commit 本轮意图内文件。
10. 只有用户明确要求 push 时才 push。

推荐实现顺序是“审查 -> 修复 -> iter-finish closeout -> commit”。如果先运行 iter-finish，再审查并修代码，必须二次更新 closeout，避免文档和最终代码脱节。

## Validation Commands

```bash
.venv/bin/python -m pytest backend/tests
npm run build
DATABASE_PATH=/tmp/arxiv_iter.sqlite3 .venv/bin/python -m uvicorn backend.app.main:app --port 8000
.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0
git diff --check
```

说明：

- `performance_smoke.py` 需要后端已启动。
- 如果验证时使用项目默认数据库，可能改写 `backend/data/arxiv_wiki.sqlite3`，该文件应保持 ignored。
- `npm run build` 会写 `dist/`，该目录应保持 ignored。

## Known Risks

- 已实现基础 PDF/HTML 文本抽取与 metadata fallback，但尚未做版面结构、表格、公式、图片或章节层级还原。
- SQLite 适合课程 MVP 和本地演示；更大数据量或多用户并发需要进一步拆分存储与任务队列。
- LLM JSON 输出只做最小解析和校验；复杂论文抽取需要更严格 schema、重试和 citation 对齐。
- Chunk 检索已使用 SQLite FTS5 trigram 作为可选候选预筛；更大数据量仍需要真实语料基准、索引质量评估和可能的任务队列/专用检索服务。
- 当前准确率基线来自 seed 数据，不能代表真实 arXiv 数据集。
- Agent 已有轮数、工具数、字符和软时间预算，但 provider 单次 120 秒超时与重试尚未绑定严格剩余 wall-clock deadline。
- Provider response read-side 的 IncompleteRead/连接重置尚未纳入完整瞬态重试矩阵；embedding 真实路径仍未启用。

## Next Candidates

1. iter05：用户 Review + Memory 闭环，记录偏好/失败案例并可审计地影响后续回答。
2. iter05：真实 QA/retrieval gold set，覆盖真实 arXiv 论文并评估 Agent 搜索恢复与引用准确。
3. iter05：更真实的 PDF/HTML 章节、附录、表格/图注/公式和 citation 对齐。
4. iter05：前端 Playwright 自动化，覆盖 Agent QA、论文详情和学习管理路径。
5. 后续：严格 wall-clock deadline、provider 重试矩阵、SQLite schema migration、定时 ingestion/订阅推荐。

## Git And Collaboration Notes

- 默认不 push，除非用户明确要求；如用户要求 commit+push，先确认远端状态。
- 远端 main 可能有同伴提交 README 开发者名单；push 前应 `git fetch origin main`，必要时 rebase 并保留远端内容。
- 课程 GitHub Flow 文档在 `docs/github-flow-report-wang-huiyin.md`，团队协作任务优先走 feature branch + PR；用户明确要求直推时才推 `main`。

## Phase Status

### iter01 - 可信知识链路与稳定性修复（Complete）

- 文档：`docs/iterations/iteration_iter01_core-reliability.md`
- 验证：15 backend tests passed；frontend build passed；100 并发 smoke passed，p95 `1.255s`。
- 提交：`a0a218e feat(iter01): harden core reliability and close iteration`
- 主要 follow-up：全文解析、检索升级、订阅推荐、真实评测集。

### iter02 - 正文解析与可追溯 Chunk 知识链路（Complete）

- 文档：`docs/iterations/iteration_iter02_traceable-fulltext-chunks.md`
- 验证：22 backend tests passed；frontend build passed；100 并发 smoke passed，p95 `1.2061s`。
- 提交：`feat(iter02): add traceable fulltext chunks`
- 主要 follow-up：FTS5/query-aware chunk 检索、真实 PDF/HTML 结构解析、真实 QA/retrieval gold set、Playwright smoke。

### iter03 - FTS5 Chunk 检索性能优化（Complete）

- 文档：`docs/iterations/iteration_iter03_fts5-chunk-retrieval.md`
- 验证：33 backend tests passed；frontend build passed；100 并发 smoke passed，p95 `0.9062s`。
- 提交：`feat(iter03): add FTS5 chunk retrieval`
- 主要 follow-up：真实 arXiv QA/retrieval gold set、PDF/HTML 结构解析、Playwright smoke、显式 schema migration/version 记录。

### iter04 - Agent 驱动的跨论文知识库探索（Complete）

- 文档：`docs/iterations/iteration_iter04_agentic-cross-paper-qa.md`
- 验证：54 backend tests passed；frontend build passed；100 并发 smoke passed，p95 `0.9707s`；真实 `gpt-5.5-medium` smoke passed（10 tool calls、2 cited papers、HTML full text）；真实前端复验完成双论文问答（7 tool calls、3 HTML evidence、86% evidence support）。
- 主要能力：只读论文库工具、多轮 tool calling、引用白名单、执行 trace、mock/real 双路径、真实 provider 可观测错误和安全兼容。
- 主要 follow-up：Review + Memory、真实 gold set、结构化章节/附录、Playwright 自动化、严格 deadline 与重试矩阵。
