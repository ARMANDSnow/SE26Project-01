# Iter14 — 可追溯调研综合与研究报告

## Context

Iter13 已完成 schema v7、严格 ResearchBrief/PaperBrief、版本化 Artifact、Run Paper、Tool Registry 与十步 topic workflow。本轮在 dataset finalize 后增加跨论文综合、Citation Registry、严格引用验证和版本化研究报告，同时保留 standalone 三步 Harness 的确定性边界。

开工基线：分支 `codex/agentic-research-refactor`，HEAD `139eaf7`。Python 与 Node 依赖完整，`package-lock.json` 未修改；104 个后端测试、strict mypy、前端生产构建及 Playwright 6 passed / 6 skipped 通过。Playwright 首次因沙箱禁止绑定本地端口失败，按权限流程允许本地测试服务后通过。工作区存在用户同步副本 `test-results 2/`；本轮不修改、删除、暂存或提交任何带“ 2”后缀、`UIPrototype/第1组_*` 或其他用户文件。

## Goals

- schema v8 连续迁移，新增 durable opened Evidence 与 owner-scoped `research_citations`，并扩展版本化 Artifact 类型。
- 实现严格 SynthesisPlan、ComparisonMatrix、SynthesisClaim、Citation Registry、CitationValidationResult 与 ResearchReport 契约。
- 实现 Synthesis、Comparison、Citation Verifier、Report Agent，并复用单请求 strict structured-model 入口。
- 将 topic workflow 扩展为 17 步，保证 lease、预算、Decision、SSE、暂停/恢复/取消/重试和 source-hash fencing。
- 提供 owner-only Citation/Evidence、Matrix、Report versions、指定 Report、验证状态与显式重新生成 API。
- 在现有 Workflow 中提供响应式综合与报告视图、Citation inspector、版本与 stale 状态，不增加主导航。
- 不破坏普通 Chat、Paper Chat、assistant-ui 消息树、`/runs/:runId`、Iter12/13 UI 与 standalone Harness。

## Scope

topic workflow 在原十步后追加：`synthesis planning → comparison matrix → cross-paper claims → citation registry → citation verification → report generation → finalize cited report`。事实性 comparison cell、finding、agreement、disagreement 和 conclusion 必须引用当前 Run 已登记且验证为 valid 的 Citation；无证据内容只能进入 limitation、gap 或 uncertainty。

本轮先建立服务端生成的 durable Evidence ID，再允许 Citation 入库。Citation 写入必须在同一事务中重新检查 Run owner、论文关联、当前 ACL、paper/document/chunk/source hash、heading/offset、quote hash 与 opened whitelist。报告仅使用已验证 claims、matrix 和 registry；模型输出不是数据库真相。

## Acceptance Criteria

- fresh v8、v7→v8、v2→v8 结构一致；迁移失败完整回滚；缺列/FK/index/unique/CHECK 或伪造 v8 fail closed。
- durable Evidence 由 `open_evidence` 服务端登记；不存在、未打开、跨 Run、跨 owner、旧 source hash 或伪造 Evidence 均拒绝。
- `(artifact_id, artifact_version, citation_key)` 唯一；Citation 必须绑定同 Run Artifact/Paper/Chunk/Evidence 与当前 source identity。
- Citation Registry Artifact 与 Citation rows 在同一 active-lease fenced 事务中创建；重放复用同一版本，内容冲突返回 conflict。
- 新 Artifact 同 Run/类型追加版本，旧版本保留；上游 PaperBrief/Evidence/source hash/ACL 变化后下游 matrix/claims/citations/report 动态 `is_current=false` 并标明 stale/inaccessible。
- public upload 收回 private 或 moderation 撤权后，非 owner 不获得 Citation/Evidence 详情；聚合报告事实段与事件投影不泄漏相关论文、claim、heading 或 excerpt。
- Comparison 与 Report 的事实字段在 Pydantic 层强制非空 Citation；repository 层再验证合法 key、覆盖 paper、source hash 与 opened Evidence。
- 每个模型预算槽只调用一次 provider，关闭 JSON response format 仍发送完整 JSON Schema并 strict fail closed；缺少真实 LLM 明确失败。
- Coverage/预算不足时零调用进入 `waiting_input`，Decision option 由后端受控解释；前端不乐观伪恢复。
- 17 步重启、过期 lease、重复执行和手动 retry 不重复 Artifact/Citation；旧 lease 不能提交 Report。
- API 身份仅来自 Session，非 owner 统一 404，不返回 provider body、Authorization/Bearer、Key、绝对路径或未授权证据文本。
- Workflow 顶层维持“过程 / 数据集 / 综合报告”三组；矩阵按维度卡片渲染，390px 无宽表横向滚动，关键触点 ≥44px。
- Citation disclosure 具备 `aria-expanded`、`aria-controls`、键盘支持与焦点返回；验证状态使用礼貌级 `aria-live`；深浅色、reduced-motion 和长文本正确。
- 后端、strict mypy、build、Playwright、必要真实 arXiv smoke 与 `git diff --check` 通过；任何新的真实付费模型 smoke 仅在单独授权后运行。

## Plan

1. 新增 v8 migration、精确兼容校验、durable Evidence/Citation 表与迁移/伪造/回滚测试。
2. 新增严格综合契约、current evidence primitive、原子 registry、动态 ACL/stale 投影与 Citation API。
3. 新增四 Agent 和 11–17 步 cited synthesis pipeline，接入预算、coverage Decision 与 regeneration generation。
4. 同步 TypeScript/API/query hooks/SSE invalidation，完成综合报告、矩阵、Citation 与版本 UI。
5. 补齐后端/Playwright 回归，运行验证与必要真实 arXiv smoke。
6. 四路只读收尾审查，修复后 iter-finish、更新 handoff/README/架构/产品文档并自动 commit，不 push。

## Risks And Questions

- **durable opened Evidence**：Iter13 `ToolContext.search_refs` 只在内存中；v8 必须登记服务器生成 evidence ID，旧 PaperBrief 不能自动证明 Evidence 已打开。
- **source hash 与历史审计**：当前 Chunk replacement 删除旧行；Citation 不能依靠 cascade 丢失审计记录。v8 保存不可变定位/hash 快照，旧引用只能 stale，不能继续返回旧正文。
- **聚合 stale**：无 `paper_id` Artifact 目前 completed 即 current；新类型必须记录 dependency snapshot 并在读取/写入两侧动态复核。
- **事务与 lease**：多条 Citation 与 Registry/Report 不能分事务；最终提交必须再次验证 active lease、ACL 与 source hash。
- **模型崩溃窗口**：provider 成功到 Artifact commit 之间仍需 durable operation identity；不能因自动 retry 产生第二次付费副作用。
- **撤权投影**：Citation 列表可返回安全 tombstone 状态，但详情/Evidence 统一 404；报告中的相关事实文本必须隐藏。
- **Coverage Decision**：有限报告只能基于当前 valid Citation，不能用模型补造覆盖；返回筛选/继续阅读需要明确重新排队边界。
- **UI 信息密度**：Workflow 只有约 380–460px；矩阵按维度/论文卡片展示，报告目录使用分段导航，不能直接复用 nowrap Table。

## Opening Review

### Data model and synthesis gap

- 可复用 v7 Artifact version/idempotency、Run Paper/source hash、strict model、Tool Registry、budget 与 lease 状态机。
- P0：缺 durable opened-evidence ledger；Artifact CHECK 需事务重建；聚合 Artifact 无传递 stale；Citation/Registry 需原子写；固定 v1 checkpoint 不支持显式 regeneration。
- standalone Harness 的三步定义、`scaffold_only` 输出、零外部调用和 `/api/research/runs` 创建入口必须保持不变。

### Citation, transaction, lease, budget and security

- P0：`open_evidence` 未同时比较当前 asset/document hash；成功模型调用后的崩溃可能再次付费；新聚合 Artifact 默认会绕过撤权过滤；旧 Chunk 删除与审计保留冲突。
- 所有 Citation 状态由服务端计算；写前与读时都全量复核。事件/step output 只保存 ID、数量和安全状态，不保存 claim/excerpt/provider detail。
- v8 测试必须覆盖写入点故障注入、旧 generation、重复执行、跨 Run/owner Evidence、quote/offset/heading/hash mismatch 和 public→private。

### Report UI/UX

- P0：需新增严格 Citation/Report/Matrix API 与类型；完成 Run 的缓存也要在页面进入、聚焦和 Evidence 打开时复核；Citation 必须是可操作 disclosure。
- 顶层不扩成大量 Tabs；保持三组信息架构。矩阵使用卡片，不使用通用 nowrap Table；旧 Report 版本可选但始终显示 stale/inaccessible banner。
- Citation 四态使用文字+图标+语义 token，验证摘要用独立 `aria-live`；Playwright 增加容器自身 overflow、44px 触点、焦点返回、深浅色与 reduced-motion 断言。

## Non-goals

- 不实现 topic graph、Librarian/资料库项目化、报告导出、分享/公开发布、外部任务队列、Redis Session、v0 legacy 数据迁移或并行多 Agent。
- 不增加生产 mock、seed、debug API；不把原型模拟数量、计时或进度复制到生产。
- 不修改 Chat/论文库/我的资料库三个主入口，不新增 Workflow 主导航。

## Progress Notes

- 2026-07-16：完整读取 AGENTS、handoff、迭代索引、Iter13、README、后端架构、产品 PRD/Workflow/路线图与 AgenticResearchWorkflow 原型全部文件；确认模拟数据仅作布局参考。
- 2026-07-16：依赖检查通过，锁文件未改；基线为 104 tests、strict mypy、build、Playwright 6 passed / 6 skipped。
- 2026-07-16：三路只读开工审查完成；阻断项归纳为 durable opened Evidence、原子 Citation Registry、聚合 stale/ACL、模型崩溃窗口和响应式 Citation/Report 交互。
- 2026-07-16：完成 schema v8、durable Evidence/Citation/model-operation ledger、17 步 topic workflow、四个新 Agent、owner-only API 和综合报告 UI；standalone Harness 保持三步。
- 2026-07-16：四路只读收尾审查发现并修复报告 regeneration attempt 卡死、coverage checkpoint 冲突、预算/ledger 非原子、真实输入 hash、跨论文引用、撤权投影、Evidence quote/document 校验、报告自由事实文本和 UI loading/Registry 交互问题。
- 2026-07-16：获得单独付费授权后，以 `gpt-5.5-medium`、关闭 provider JSON response format 的真实配置完成浏览器端 17 步 topic Run。真实运行暴露并修复 arXiv 查询过窄/过宽、截断 PDF 复用、缺失 `filelock`、Report Agent 改写已验证事实、首次严格失败后 regeneration 入口隐藏，以及已展开 Evidence 缓存覆盖 stale Registry 状态等问题。

## Closeout

### Summary

- schema 从 v7 连续升级为 v8：扩展 Artifact allowlist，新增 `research_model_calls`、`research_evidence`、`research_citations`，fresh、v7→v8、v2→v8 与迁移回滚保持同构。
- `open_evidence` 现在在 active lease 下登记服务器生成的 Evidence ID 与 quote hash；PaperBrief、Citation 和 Evidence API 均重新校验 Run paper、当前 ACL、asset/document/chunk/source hash、document relation、heading、offset 与内容 hash。
- topic Run 从十步扩展到 17 步，新增 Synthesis Plan、Comparison Matrix、cross-paper Claims、原子 Citation Registry、严格验证、版本化 Report 与 finalization。模型预算预占和 durable operation 创建在同一事务，真实 canonical input hash 防止错误复用，结果写 ledger 前经过中央安全拒绝。
- 新增报告版本/Citation/Evidence/Matrix/重新生成 owner-only API；同 Run/类型只追加版本，旧报告保留审计但明确 stale。显式 regeneration 会安全增加 attempt allowance，并生成新 Artifact/Citation/Report 版本。
- Workflow 保持三个产品主入口与“过程 / 数据集 / 综合报告”信息架构；提供卡片矩阵、Claims、完整 Citation Registry、四状态、报告目录、版本选择、stale banner、重新生成与 Evidence 定位链接。1024px 使用 Drawer，390px 无宽表。
- 真实运行加固了外部输入边界：arXiv discovery 保留一次网络请求，同时要求核心 RAG 短语并 OR 扩展其余查询词；远程 PDF 下载/缓存会校验 `Content-Length` 与 EOF，截断文件删除并明确失败。Report Agent 只能逐字选择已验证 statement/key 对，不能改写、合并或补造事实。
- 普通 Chat、Paper Chat、assistant-ui 分支/刷新、Run data card、Iter13 Brief/Paper/PaperBrief 和三步 Harness 未改变语义。

### Validation

- `.venv/bin/python -m pytest backend/tests`：112 passed。
- `.venv/bin/python -m mypy`：strict，通过，54 个 source files。
- `npm run build`：通过；主入口 467.11 kB，Chat 432.87 kB，均低于 Vite 500 kB 建议线。
- `npm run test:e2e`：6 passed、6 skipped。旗舰路径覆盖 1440/1024/390、Brief/PaperBrief/Matrix/Claims/Registry/Report、Citation 键盘展开与焦点返回、四状态、报告版本/stale、重新生成入口、Task Center、深浅色、reduced-motion、44px 与无横向溢出；桌面继续覆盖 Decision、控制、普通 Chat 和 Paper Chat 回归。
- `git diff --check`、敏感信息/路径扫描与暂存范围检查在提交前执行。

### Review

- 正确性审查确认 Registry Artifact + Citation rows 与 lease fencing 为同一事务；修复 regeneration/coverage 无法再次 claim、extraction 固定 key、并发 regeneration TOCTOU 和模型预算/ledger 分离提交。
- 契约审查后强制 Matrix paper/Citation/Evidence 一致、Claim ID/覆盖论文/引用唯一、limitation/gap 不参与事实 claim 验证、Report factual statement 必须精确来自已验证 Claim/Matrix 文本与 key。
- 安全审查后补齐 model result 入库前安全检查、真实 input hash、Registry content hash/Pydantic 重验、Chunk document/source hash、PaperBrief quote hash、Evidence 单快照读取和撤权后的 Matrix/Claims/Report 动态过滤。
- UI 审查后加入 query loading/error 的非事实投影、可见 Registry、Matrix/Claim 可点击 Citation、局部 aria-live、报告目录和 current-version 跟随。
- 真实浏览器复核后补齐“首次报告 strict fail、尚无 Report Artifact”时的 regeneration 入口，并禁止关闭或重新校验中的 Citation 使用旧 Evidence query cache 覆盖最新 stale Registry 投影。
- 最终四路审查后，Report 后验校验改为精确 `(text, citation_keys)` pair；Registry Artifact 用 `claim_ids` 保存共享 Citation 的完整多对多审计关系；显式人工 retry 旋转操作代次；聚合 Artifact current 投影重验内容 hash/Pydantic、Registry/Validation 完整性和 Report 上游版本 DAG。owner-only GET 增加 `private, no-store`，新 API 跨 owner 404、截断 PDF、错误脱敏和 exact pair 均有直接回归。
- UI 最终审查后，历史 Report 同步选择其 recorded plan/matrix/claims/registry 版本，避免历史 Citation 注入当前综合；Citation/Report/Evidence 5 秒主动复核动态 ACL；论文页消费 chunk locator，自动打开解析文本并聚焦高亮对应 Chunk。

### Real Service Smoke

- 用户单独授权后，从主页 Chat 以真实兼容 provider、`gpt-5.5-medium`、`LLM_JSON_RESPONSE_FORMAT=false` 完成 17/17 步 topic Run；密钥只从桌面用户文件解析到后端进程环境，未写入命令参数、仓库、文档、日志或 fixture。
- 真实 arXiv 检索选中并导入 `2607.09349`（Deceptive Grounding）与 `2607.08269`（PolyUQuest），完成两份 PDF 下载、完整性校验、Docling/Chunk、PaperBrief、Matrix、Claims、Citation Registry、严格验证和中文 Research Report。
- 第一次 Report provider 输出因改写已验证 statement 被 `report_statement_unverified` 严格拒绝，未写入 Report Artifact；修复后通过可见 UI regeneration 重跑步骤 11–17。随后再次从 UI 生成 v2，确认 v1 Report/Citation stale、v2 current/valid 和版本切换。
- 最终 Run 为 17/17 completed，预算使用 17/40 model calls、21/100 tool calls；两次 regeneration 各恰好新增四次 provider 调用，前十步、PDF 与 Docling 未重复。最终 Registry 有 4 条 valid Citation，历史两个 Registry version 各 4 条 stale Citation；Report v1 stale、v2 completed。
- 浏览器实测 Citation C1 重新校验为 valid，并定位到论文 66、Chunk 93、`1 Introduction`、字符 3103–4295；关闭 disclosure 后焦点返回触发按钮。显式 URL 刷新恢复同一 Run，新的干净浏览器标签页无 console/page error。

### Citation Integrity

- durable Evidence 只能来自同一步检索白名单内实际打开的 Chunk；未打开/伪造 ID、跨 Run/owner、错误 paper、heading/offset、quote、document 或 source hash 均 fail closed。
- Citation Registry 从服务器端 Evidence ledger补齐 locator，不信任模型提交的原文或 hash；Artifact 与 Citation rows 原子追加，key 在 Artifact version 内唯一。
- Citation Verifier 同时检查 Registry row、claim、covered paper、Evidence 与四态；Report 仅接受验证后的原句/key，unsupported 内容只能留在 limitation/gap。
- public upload 撤权或 source hash/Brief/Evidence 变化会使下游持久化 stale；inaccessible Citation 只返回安全 tombstone，详情/Evidence 404，报告相关事实段隐藏。

### Risks

- 当前单进程 SQLite executor 和内存 SessionStore 仍不适合多实例；Docling/远程 PDF 是不可抢占的同步长任务。
- `research_model_calls` 的 `started/ambiguous` 状态选择阻止自动重复付费；目前需要运维/后续受控 Decision 才能显式处理，不会自动再发请求。
- 报告的事实语句采用严格“已验证 Claim/Matrix 原句”白名单，安全性优先于自由改写；更丰富的语义蕴含校验需后续 evaluation/gold set。
- 当前真实 smoke 只覆盖单用户、两篇论文和单进程 executor；更大候选集、多用户并发、进程重启中的真实 provider ambiguous-call 恢复仍需要专门集成环境。

### Iter15 Candidates

1. 研究脉络/主题簇/时间线 Artifact 与资料库项目化，Run、论文、报告、图谱反向链接。
2. Citation entailment gold set、覆盖率/支持度评分和可审计人工复核队列。
3. 可取消进程 worker/任务队列、Redis Session、用户级 Run/SSE/模型配额与 ambiguous-call Decision。
4. 报告导出与分享仅在当前 Citation 再验证通过后开放。
