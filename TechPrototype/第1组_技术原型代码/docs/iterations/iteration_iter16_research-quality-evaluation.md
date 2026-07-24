# Iter16：可复现研究质量评测与验收证据

## Context

Iter15 已完成 schema v9、owner-only 研究项目、主题簇、时间线、研究关系图和真实网页审计。本轮不改变生产 schema/API/UI，转而建立固定 Citation entailment/coverage gold set、离线评测器、认证性能 smoke 和可复现答辩验收证据。

开工基线：`codex/agentic-research-refactor` @ `5c5fa37`，工作树干净且与远端 0 ahead / 0 behind。122 个后端测试、strict mypy 和前端生产构建通过。`docs/AGENT_HANDOFF.md` 中“尚未 push”为过时说明，closeout 时修正。

## Goals

- 建立 2023 年以来 RAG 检索优化主题的版本化 Citation entailment gold set，覆盖报告、矩阵、主题簇、时间线和语义图谱边。
- 提供 fail-closed 的 dataset 校验、prediction 评分和显式付费 LLM judge CLI，生成规范化 JSON/Markdown 报告。
- 分开报告语义支持度、Citation coverage 和确定性关系，不使用模糊“准确率”替代分项指标。
- 修复性能 smoke 的 Session 认证，以隔离 v9 数据库验证 120+ 论文和 100 并发非 LLM API。
- 补强恢复、SSE 和连续演示路径回归，保持现有产品契约不变。

## Scope And Acceptance Criteria

- gold set 至少包含 5 篇公开论文和 60 个 adjudicated 案例；标签固定为 `supported / contradicted / insufficient`，五类 Artifact 均有覆盖。
- 每条案例包含稳定 ID、公开论文身份、事实文本、短 Evidence、章节 locator、Evidence SHA-256、预期标签和标注说明；不含本地数据库 ID 或私有数据。
- prediction 必须与 dataset case ID 完全一一对应；缺失、重复、未知 ID/标签或 hash tamper 直接失败。
- 报告包含 dataset/evaluator/prompt hash、模型标识、混淆矩阵、macro-F1、supported precision、false-accept rate、coverage、分 Artifact 指标和失败案例。
- 未运行真实 judge 或未达阈值时明确标记 `not_evaluated` / `below_threshold`，不得声明 >90%。
- 性能 smoke 使用登录 Cookie，覆盖论文、Wiki、Graph、历史、Run 和项目列表；100 requests / 100 workers 零错误且 p95/max <3s，并验证 Run 创建 <500ms。
- 生产 schema 保持 v9；不新增生产 seed/debug API，不接入 Citation Validator，不放宽报告 exact-statement 白名单。

## Plan

1. 定义严格评测契约、gold set 与数据校验/评分/报告生成。
2. 增加 prediction 与单请求 strict LLM judge 模式，补齐安全和错误回归。
3. 修复认证性能 smoke，增加隔离 fixture、恢复/SSE 和连续 Playwright 演示回归。
4. 运行全量验证，完成评测/性能报告和 iter-finish 文档更新。

## Risks And Questions

- 结构有效 Citation 不等价于语义支持；本轮必须分开报告，不把现有 locator validator 包装成 entailment verifier。
- gold set 的受控反例用于评测分类边界，不能作为论文事实展示给产品用户。
- LLM judge 是评测工具而非生产授权器；真实运行需要单独付费授权，并且一次案例只允许一次 provider 请求。
- 性能 fixture 只能进入隔离临时数据库，不能污染默认旧 v0 数据库。

## Non-goals

- schema v10 人工复核队列、报告导出门禁、自由改写、ambiguous-call Decision、Redis/跨进程任务队列、v0 迁移或多人协作。
- 未经单独授权运行真实付费模型，或把未达标结果写成已通过。

## Progress Notes

- 2026-07-17：完成规定文档、原型、论文库/资料库/Run/Artifact/Citation/Evidence/报告 UI 与后端链路的完整 grounding；确认当前缺口是可复现质量证据而非新的研究脉络 UI。
- 2026-07-17：开工基线验证为 122 tests、strict mypy、前端 build 通过；工作树干净且分支已与远端同步。
- 2026-07-17：建立 `rag-citation-entailment-v1`：RAGAS、Self-RAG、CRAG、RAPTOR、RAGChecker 五篇公开论文，60 个 adjudicated 案例，三标签各 20 条；五类 Artifact 分布为 10/10/10/15/15，50 个语义 Citation 单位与 10 个 publication/确定性关系分开计数。
- 2026-07-17：新增 strict `EntailmentJudgment`、dataset/prediction 校验、混淆矩阵与分项指标、规范化 JSON/Markdown、单请求 OpenAI-compatible judge。prediction 文件即使指标达到阈值也只能显示“未验证”；只有本次真实 judge 且达阈值才能显示“已达标”。
- 2026-07-17：修复 performance smoke 的 Session Cookie，增加只允许 `/tmp` 的 v9/120-paper fixture。100 requests / 100 workers 覆盖论文、Wiki、Graph、历史、Run、项目列表，零错误，p95 `0.3129s`、max `0.3160s`；Run 创建 `0.0058s`。
- 2026-07-17：增加 executor 重启接管过期 lease、旧 worker fencing 与事件顺序集成回归；既有 owner-only `Last-Event-ID` SSE 续传回归继续通过。
- 2026-07-17：扩展连续 Playwright 路径为 Chat → topic Run → 固定报告 → Citation Evidence → 论文 Chunk 定位 → 研究项目 → Graph Evidence；1440/1024/390 均覆盖键盘焦点、reduced-motion 和无横向溢出。
- 2026-07-17：经用户授权，以隔离 v9 数据库和桌面凭据完成真实普通 Chat 浏览器验证。验证发现并修复空 provider 文本被误记为成功的问题：SSE 支持分段 content/兼容非流式 JSON，无文本严格失败；另提供显式 `LLM_STREAMING=false` 单请求兼容模式。桌面配置中的模型别名不在 Key 的 `/models` 列表，且 base URL 缺少 `/v1`；改用可用的 `gpt-5.5` 与正确 API 前缀后，1440/1024/390 UI 均显示“真实链路成功”，无横向溢出，键盘焦点和 reduced-motion 正常。

## Closeout

### Summary

- 新增 `evaluation/` 版本化 gold set、数据来源/指标说明和 validation-only 报告；报告固定记录 dataset/evaluator/prompt hash、模式和脱敏 judge 配置。
- 新增离线 CLI：支持仅校验、严格 prediction 文件评分和经单独授权的 `--use-llm`；配置缺失、schema/case ID 错误、provider 失败、敏感输出和未知/缺失 prediction 均 fail closed。
- 性能、恢复和演示验收均使用隔离 fixture，不访问或修改默认 116 篇旧 v0 数据库，也未增加生产 seed/debug API。
- 生产 SQLite schema、HTTP API、前端类型和主界面保持 v9 不变；当前 Citation Validator 与报告 exact-statement 白名单未放宽。

### Validation

- `.venv/bin/python -m pytest backend/tests`：144 passed。
- `.venv/bin/mypy`：58 个源文件 strict 检查通过。
- `npm run build`：通过。
- `npx playwright test`：9 passed、6 skipped；连续旗舰路径在 desktop-1440、tablet-1024、mobile-390 全部通过。
- 隔离认证性能 smoke：120 papers，100 requests / 100 workers，0 failures，p95 `0.3129s`，max `0.3160s`，Run create `0.0058s`，均低于 3s/500ms 门槛；服务运行后已关闭。
- validation-only evaluator：dataset hash `dc9f7f74c4680175c2ba3ca9e5de6baf33eb832f5381f71ae34afec6803bd20a`，60/60 schema/hash/distribution 通过；真实 judge 未运行，macro-F1、supported precision 和 false-accept 均明确为未验证。
- 经授权的真实普通 Chat 前端 smoke：隔离数据库、`gpt-5.5`、正确 `/v1` API 前缀、`LLM_STREAMING=false`；浏览器得到非空回答“真实链路成功”。1440/1024/390 截图保存在 `output/playwright/iter16-real-frontend/`，390/1024 横向溢出均为 false，reduced-motion 为 true，提交后焦点仍在 textarea。控制台仅有登录前预期的 `/api/auth/me` 401，无成功请求新增错误。
- `git diff --check`：通过。

### Review

- 主 agent 完成本地契约/安全审查；本轮没有自动迭代授权，因此未调用 subagent、未自动 commit 或 push。
- 固定 60-case judge 的付费边界保持关闭，validation report 的 model 仍为 `not-run`。用户仅授权真实前端验证；桌面 Key 只注入隔离后端进程，未写入仓库或报告，未运行真实 judge、arXiv、PDF 或 Docling。
- Playwright 技能约束用于真实 Chromium 三视口回归；首次沙箱启动失败后在批准的浏览器权限下复验通过。

### Follow-ups

- 真实固定 gold set judge 需用户另行授权付费执行；未执行前不得把课程 `>90%` 写成已达成。
- schema v10 人工复核队列、报告导出门禁/自由改写、provider ambiguous-call Decision、可取消跨进程 worker、Redis Session/配额与 v0 迁移继续顺延。
