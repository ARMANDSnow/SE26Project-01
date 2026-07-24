# Iter13 — 主题调研数据链路

## Context

Iter12 已将数据库驱动的三步 Research Harness 原子接入 Chat 消息树，并完成可恢复 Workflow、Decision、SSE 与响应式 UI。本轮在保留 standalone Harness 的前提下，让 Chat 深度研究创建真实 `topic` Run，跑通搜索、筛选、导入、正文准备与 Paper Brief 数据链路；Iter14 的报告、对比矩阵和完整引用闭环不在本轮伪装实现。

开工基线：分支 `codex/agentic-research-refactor`，HEAD `4f6bfec`。依赖恢复后 `package-lock.json` 哈希未变化；92 个后端测试、strict mypy、前端生产构建及 Playwright 4 passed / 2 skipped 通过。工作区只有 5 个已知带“ 2”后缀的未跟踪同步副本，本轮不修改、删除、暂存或提交它们，也不修改 `UIPrototype/第1组_*` 用户文件。

## Goals

- schema v7 新增版本化 `research_artifacts` 与 owner-scoped `research_run_papers`，并保证 fresh、v6→v7、v2→v7 一致、失败回滚及伪造 v7 fail closed。
- 建立具有双向 Pydantic schema、owner 权限、幂等、timeout/retry、外部调用声明、安全摘要与稳定错误码的统一 Tool Registry。
- 实现严格版本化 `ResearchBrief`、`PaperBrief` 与 Coordinator/Search/Screening/Reader/Extraction Agent 契约。
- Chat topic Run 执行十步真实数据链路；数据库是步骤、论文、Artifact、预算、Decision 与恢复状态的唯一真相。
- 每个 topic Run 默认持久化 50 候选、12 全文、40 模型、100 工具、30 分钟预算；越界前进入真实 `waiting_input` Decision。
- 补充 owner-only Artifact/Run Paper/PaperBrief API，并在现有 Workflow 中展示真实 Brief、论文阶段/理由、预算、工具摘要和 Paper Brief。
- 不破坏普通 Chat、Paper Chat、消息树编辑/重生成/Fork/分支、论文导入/解析、FTS5、证据白名单、登录隔离、资料库及 standalone Harness。

## Scope

本轮实现线性十步最小链路：`brief → query planning → local search → arXiv search → dedup/import → screening → fulltext acquisition → reading → extraction → finalize research dataset`。每一步仍使用 Iter11 的 dependency、idempotency key、attempt、lease owner/generation/expiry、heartbeat、pause/resume/cancel/retry、Decision、event ID/SSE 与 requested_action 边界。

本轮不实现 Synthesis Agent、Citation Validator、Librarian、research report、comparison matrix、topic graph、报告页面、资料库项目化、Run 级 Evidence Registry、并行多 Agent、外部任务队列、v0 legacy 迁移、生产 mock/seed/debug API。Paper Brief 只保存经数据库重新校验的稳定 Chunk 引用；完整报告引用闭环留待 Iter14。

## Acceptance Criteria

- `research_artifacts` 同 Run/类型按版本追加，成功旧版本不覆盖；相同 checkpoint 幂等复用；source hash 改变后旧 PaperBrief 明确失效。
- `research_run_papers` 同 Run/论文和同 Run/source identity 均不重复，阶段只合法前进，rank/score/入选排除理由可追溯。
- Artifact、Run Paper、PaperBrief、Decision 与事件均从 Session owner 解析身份；非 owner 和撤权私有上传统一不泄漏并返回 404。
- Tool Registry 首批接入本地论文检索、arXiv、source identity 去重导入、PDF 获取、Docling、Chunk 检索、Evidence 打开；不得绕过现有 ACL、SSRF 或证据白名单。
- 所有 Agent 输出通过 `extra='forbid'` 的版本化 Pydantic schema，再做 paper identity、访问权限、source hash 和 Chunk 引用校验后落库。
- 外部调用前原子预占预算，调用后原子结算；即将越界时零调用、唯一 pending Decision，继续/缩小/停止均由后端受控语义处理。
- lease 丢失或 requested_action 后旧 generation 不能写入 Artifact、Run Paper、usage、事件或步骤真相；重启、过期 lease、重复执行和手动 retry 复用已有 paper/asset/document/chunks/source hash。
- 缺少真实 LLM 配置时 topic 产品路径明确失败为稳定 configuration unavailable 状态，不生成伪 Brief/PaperBrief。
- Research REST、SSE、步骤输出、Artifact、事件和用户可见日志不包含 provider body、Authorization/Bearer、API Key、本地绝对路径或未清洗异常。
- 1440px、1024px、390px 显示真实 ResearchBrief、候选/入选/排除、全文阶段、预算、工具摘要和 PaperBrief；无横向溢出，移动触点 ≥44px，focus、aria-expanded/controls、aria-live、焦点返回、dark/light 与 reduced-motion 正确。
- 后端、strict mypy、build、Playwright、真实 arXiv smoke 和 `git diff --check` 通过；真实付费模型 smoke 仅在再次取得用户授权后运行。

## Plan

1. 完成 schema v7、精确兼容校验及 migration/fresh/rollback/forged tests。
2. 新增严格 Research contracts、Artifact/Run Paper repository、stage/source hash 校验、fenced budget/Decision 原子入口。
3. 建立 Tool Registry 与真实能力 adapters，集中 owner 校验、幂等、timeout/retry 和研究状态脱敏。
4. 实现五个 Agent 与可注入 structured-model contract，完成 topic 十步 dispatcher/checkpoint；保留三步 Harness。
5. 将 Chat 深度研究改为原子创建 topic Run，补充 owner-only Research data API。
6. 同步 TypeScript/API/query hooks/SSE invalidation，完成真实数据驱动的 Workflow UI。
7. 补齐后端与 Playwright 测试，运行真实 arXiv smoke 和完整验证。
8. 四路只读收尾审查，修复后 iter-finish、更新 handoff/README/架构文档并自动 commit，不 push。

## Risks And Questions

- **副作用 fencing**：现有 generation 只保护 `finish_step/fail_step`；topic handler 的导入、下载、Docling、Artifact 与预算写入必须在每次调用前后重新验证 lease。Python thread timeout不能真正停止 Docling，不能制造“已取消但后台仍写库”的假象。
- **崩溃窗口**：外部副作用和 step finish 分属短事务；每个步骤入口必须从 durable Artifact/Run Paper/asset/document/chunks 检测已完成 checkpoint，而不是依赖内存。
- **预算 Decision**：当前 Decision resolve 无业务语义；topic budget option 必须由服务端映射为受控扩容、缩小范围或停止，客户端只提交 option ID。
- **撤权隔离**：Run owner 不等于 paper access。paper-linked Artifact/Run Paper/PaperBrief 每次读取都需重查当前上传可见性。
- **source identity**：arXiv ID 要规范化并去版本；`source_hash` 统一使用 PDF asset 的裸 SHA-256 digest。fulltext_ready/read/extracted 必须同时匹配当前 paper asset、document 与 chunks。
- **脱敏**：现有 step/event 接受任意 dict；topic 路径只允许 typed allowlist output，未知异常默认稳定安全摘要，不能把 Pydantic input、Docling/remote PDF 原始异常复制进 Research 状态。
- **UI 刷新**：Iter12 SSE 事件列表固定；Artifact、论文阶段、预算和工具事件必须驱动 Run/Artifacts/Run Papers 一起失效。Task Center 仍保持轻量，不为历史 Run 制造 N+1 查询。

## Progress Notes

- 2026-07-16：完整读取 AGENTS、handoff、iteration 索引、Iter12、README、产品/Workflow 设计和 AgenticResearchWorkflow 原型；确认原型数字与计时只作布局参考。
- 2026-07-16：恢复 Python/Node 依赖，锁文件哈希保持 `206bd9dc293372a6d62758928ac6a20037b5ab3e`；基线为 92 tests、strict mypy、build、Playwright 4 passed / 2 skipped。
- 2026-07-16：三路只读开工审查完成。架构审查要求保留 standalone Harness、Chat 改 topic 十步并分离 data repository/contracts/tools/agents；质量审查将副作用 fencing、预算原子预占、source hash 复用、撤权隔离与中央脱敏列为 P0；UI 审查要求严格 types/query/SSE、结构化三视图及 Harness/topic 条件文案。
- 2026-07-16：完成 schema v7、Artifact/Run Paper repository、严格 Research contracts、七工具 Registry、五 Agent 与十步 TopicResearchPipeline；Chat 深度研究改为原子创建 topic Run，standalone Harness 保持不变。
- 2026-07-16：完成 Workflow 的 Brief/论文/阅读卡三视图、真实预算和工具摘要，以及 1440/1024/390 响应式、焦点、ARIA、长文本与 reduced-motion 回归。
- 2026-07-16：四路只读收尾审查发现并修复 evidence identity、当前 asset hash、撤权聚合泄漏、筛选理由先写后验、Registry owner 声明未执行、导入/下载/Docling fencing、抽取 checkpoint 崩溃窗口、阶段筛选与 loading 误报等问题。

## Closeout

### Summary

- schema 升至 v7，新增版本化 `research_artifacts` 与 `research_run_papers`，支持 source identity 去重、阶段、排名/评分/理由、source hash 失效和动态论文 ACL。
- 建立统一 Tool Registry，接入本地检索、arXiv、去重导入、PDF、Docling、Chunk 与 Evidence；每个工具提供严格双向 schema、owner scope、幂等/重试/timeout 元数据、安全摘要和稳定错误码。
- 实现 Coordinator、Search、Screening、Reader、Extraction Agent 与十步真实 topic workflow；缺少 `LLM_API_KEY` 明确失败，不增加生产 mock/seed/debug API。
- 数据库持久化 50 候选、12 全文、40 模型、100 工具、1800 秒默认预算；越界前创建真实 Budget Decision，继续/缩小/停止由服务端解释。
- 新增 owner-only Artifact/Run Paper/PaperBrief API，并把 Chat Workflow 扩展为真实 Brief、论文阶段/理由、预算、工具摘要、PaperBrief、Decision 和 Task Center Peek。
- 关闭关键恢复/安全窗口：论文导入与 Run 关联同事务、PDF 绑定和 Docling commit 受 lease/source-hash CAS 保护、PaperBrief/evidence/asset/document/chunks 一致性校验、撤权私有上传动态过滤。

### Validation

- `.venv/bin/python -m pytest backend/tests`：104 passed。
- `.venv/bin/python -m mypy`：52 个源文件 strict 检查通过。
- `npm run build`：通过；主入口约 450.38 kB，Chat chunk 约 432.87 kB。
- `npm run test:e2e`：6 passed、6 skipped。三档旗舰页均通过；桌面额外覆盖 Budget Decision、暂停/继续/停止/重试、普通 Chat 分支回归和 Paper Chat 不进入 Research Route。
- `git diff --check`：通过。

### Review

- 正确性/事务审查：修复不可取消线程用于副作用工具、Docling 旧 hash 覆盖、抽取 Artifact/阶段崩溃窗口、候选/全文虚假预算和重复 paper.updated 噪声；只允许 arXiv 只读调用使用线程 timeout/retry，副作用 adapter 单次执行并使用内部边界。
- API/Schema/测试审查：补强 v7 CHECK fail-closed、PaperBrief relational paper/source hash 强制约束、evidence paper/hash/heading 校验和 asset stale 窗口测试。
- 安全审查：补聚合 Artifact、Step evidence 与 SSE event 的动态 ACL 投影；筛选理由落库前统一脱敏；Registry 中央校验 Run owner；arXiv 新导入 URL 由服务端规范化。
- UI/UX 审查：修正阶段集合筛选、loading/error/empty 语义、ARIA instance ID/pressed/focus 样式、旧 Harness 文案和长标题实际溢出测试；补 Task Center Peek 与 Paper Chat E2E。
- 真实模型兼容复核：API/预算审查拦截了“一次预算槽内自动发出第二次 provider 请求”的初版 400 fallback；最终改为显式 `LLM_JSON_RESPONSE_FORMAT` 能力配置并固定 `max_attempts=1`。复核确认预算一一对应且无密钥、Authorization 或原始 provider body 泄漏。

### Real Service Smoke

- 真实 arXiv 网络 smoke 已运行并通过：`cs.AI` + `retrieval augmented generation` 返回 `2607.14046`。
- 用户单独授权后运行真实付费模型 smoke：`gpt-5.5-medium` 的最小 Chat smoke 通过；Coordinator 的严格 ResearchBrief smoke 通过并产出 schema v1、6 个研究问题。Key 仅通过剪贴板注入临时进程环境，未写入命令参数、仓库、文档或日志。
- 该兼容网关/模型拒绝 `response_format=json_object`（仅记录脱敏 `provider_http_400`）。实现已把目标 Pydantic JSON Schema 注入系统提示；该 provider 需显式设置 `LLM_JSON_RESPONSE_FORMAT=false`，返回值仍需通过 strict Pydantic 校验，不能把自由文本写入数据库。模型层不做隐藏 provider retry，保证一次预算预占只对应一次真实调用；对应单测覆盖 schema 注入、配置选择和 400 不暗中重试。
- 未运行真实付费的完整十步 topic Run，以避免未经再次扩展确认的多次模型、PDF 和 Docling 成本；完整链路继续由依赖注入替身覆盖，并验证第二次复用同一论文/document/chunks。生产路径没有 mock 分支。

### Follow-ups

1. Iter14：在当前 PaperBrief 数据集上实现 Synthesis Agent、对比矩阵、研究报告和 Run 级 Evidence/Citation Registry，不回退为自由文本数据库真相。
2. 为长 Docling/批量 Run 引入可取消外部任务队列或进程 worker；当前单进程 adapter 通过 lease/source-hash CAS 保证最终真相，但无法抢占正在进行的 CPU 解析。
3. 将 SessionStore 迁至 Redis，并增加登录、Run 创建、SSE 连接和真实模型调用的用户级限流/配额。
4. 增加更接近历史生产库的 v2/v6 migration fixture 与完整真实付费十步 topic smoke；v0 旧库仍需独立、可审查的迁移项目。
