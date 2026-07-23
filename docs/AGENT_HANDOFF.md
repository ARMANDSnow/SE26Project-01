# Agent Handoff

最后更新：2026-07-21，Iter17 去 Agent 化与异步论文加工基建 closeout。

## Current Status

- 2026-07-21 完成 Iter17：schema v10 新增持久化论文加工任务、租约/心跳/generation fencing、有界重试与失败隔离。arXiv/USENIX/SIGOPS 仍由用户手动触发来源抓取，元数据入库和 PDF 上传后自动异步下载、独立子进程 Docling、分块与 FTS；下载有总时限，上传请求不解析 PDF，关键写入重验用户/ACL/source hash。固定流程组件完成职责型去 Agent 化，`agent_name` 仅兼容保留。验证为 158 tests、strict mypy、build；三路收尾复核无阻断项。详见 `docs/iterations/iteration_iter17_async-paper-processing.md`。
- 2026-07-17 完成全功能真实网页巡检与 Bugfix：真实导入/Docling/概要/Paper Chat/目录推荐/项目/17 步 topic Run/Citation 定位均从网页完成。修复长文 Markdown 失真、显式命名论文被本地检索漏掉、根目录聚合计数矛盾、移动触控尺寸和收藏/项目无障碍问题。验证为 146 tests、strict mypy、build、9 Playwright passed / 6 skipped，真实浏览器 console error 为 0；详见 `docs/iterations/bugfix_2026-07-17_full-web-ui-audit.md`。
- 2026-07-17 完成 Iter16：新增 5 篇公开 RAG 论文/60 adjudicated 案例的 Citation entailment/coverage gold set、strict prediction scorer 与可选单请求 LLM judge、规范化 JSON/Markdown 报告、认证 v9/120 论文/100 并发 smoke、executor 重启恢复和连续三视口答辩路径。另经用户授权完成隔离真实普通 Chat 前端 smoke，并修复空 provider 文本被误记成功及非流式兼容问题；固定 60-case 真实 judge 仍未授权运行，质量报告明确为 `not_evaluated`，不得声明 `>90%` 已达成。详见 `docs/iterations/iteration_iter16_research-quality-evaluation.md` 和 `evaluation/README.md`。
- 2026-07-17 完成 fresh v9 与 iter15 真实数据副本的三视口网页走查；真实普通 Chat 和 7,406-token 全文 Paper Chat 成功。修复 UTC 时间误显示、全文就绪仍标待处理、Select 32px 触点、时间线乱序/英文类型、论文内部 ID 暴露和 30 篇候选一次铺满，并约束后续 Timeline Agent 使用中文叙述。验证为 122 tests、strict mypy、build、9 Playwright passed / 6 skipped；详见 `docs/iterations/iteration_frontend-audit-2026-07-17.md`。

- 当前分支：`codex/iter17-async-paper-processing`。本轮从 `main` @ `5026606` 开始；工作树原有的 `package-lock.json` 用户改动未纳入 Iter17 提交。
- iter15 已在隔离数据库副本上完成真实 `gpt-5.5-medium` 项目分析：成功 Run 为 7/7 步、3/3 provider 调用，五类项目 Artifact 全部完成；另完成普通 Chat 和约 22k token 全文 Paper Chat。桌面凭据只注入隔离进程，未打印或写入仓库。
- 真实验证修复了 Run-derived metadata dependency hash 与 manual retry durable identity；修复后同一成功 Run 的 Planner/Cluster/Timeline 各恰好一次调用。严格 Cluster claim/Citation 校验曾拒绝一份不合法模型输出，证明语义关系 fail closed。
- iter15 将 schema 升至 v9：新增 owner-only 研究项目/项目成员、`mode='project'` 七步 Run、项目级追加版本 Artifact、dependency ledger 和项目 Citation reference。fresh、v8→v9、v2→v9、失败回滚与伪造 v9 fail-closed 已覆盖。
- “我的资料库”现可建立/编辑/归档/恢复项目，加入当前可访问的 Run、论文和固定 Report version，生成主题簇、时间线、可追溯关系图和验证结果。项目关系不扩大底层资源权限。
- 项目 Artifact 写入事务内重验 project revision/fingerprint、active lease 与每条 dependency；读取时递归验证 DAG。新上游版本、item/Citation/Evidence/ACL/source hash 变化会 stale/inaccessible，不回退旧 completed；项目变更会在同一事务内 fence 活跃分析。
- `LandscapePlannerAgent`、`TopicClusteringAgent`、`TimelineAgent` 只接收服务端 Paper/Claim/Citation 白名单；Graph construction/validation 为确定性服务。Cluster 事实、Timeline 语义事件和 Graph 语义边必须有当前有效 Citation。
- topic 仍为真实 17 步，UI 默认聚合为 7 个用户阶段；standalone Harness 仍是真实三步。完整报告使用固定版本独立路由与分节视图，历史/stale 报告事实文本不再展示。
- iter14 将 schema 升至 v8，新增 durable `research_model_calls`、`research_evidence`、`research_citations`；fresh、v7→v8、v2→v8、失败回滚与伪造 v8 fail-closed 已覆盖。
- topic Run 现为 17 步：Iter13 十步 dataset 后追加 Synthesis Plan、Comparison Matrix、cross-paper Claims、Citation Registry、Citation Verification、Research Report 和 finalize。standalone Harness 仍为三步确定性流程，未伪装成完整调研。
- `open_evidence` 在 active lease 下登记服务器生成 Evidence ID 与 quote hash；PaperBrief/Citation/报告写入和读取均重新校验 Run Paper、ACL、asset/document/chunk/source hash、document relation、heading、offset 与内容 hash。
- 新增 Synthesis/Comparison/Citation Verifier/Report Agent。事实 Matrix/Claim/Report 必须绑定已验证 Citation；Report 的事实文本只能来自已验证 Claim/Matrix 原句，limitation/gap 才允许无引用。
- 模型预算预占与 durable operation 创建为单一事务，canonical input hash 防止错误复用，provider 返回内容在写 ledger 前经过安全检查；`started/ambiguous` fail closed，不自动产生第二次付费请求。
- Research API 新增 Citation Registry/详情/Evidence、Matrix、Report versions/指定版本和显式 regeneration；非 owner 统一 404，inaccessible 只返回安全 tombstone。
- Workflow 新增“综合报告”视图：卡片矩阵、Claims、Citation Registry 四态、报告目录/版本/stale、Evidence 定位和 regeneration；1440/1024/390、键盘/焦点、reduced-motion 与 44px 已覆盖。
- 已用真实 `gpt-5.5-medium`、真实 arXiv/PDF/Docling 从 Chat 完成 17/17 步双论文 topic Run，并从 UI 两次执行步骤 11–17 regeneration。最终 Report v2 current、v1 stale，当前 4 条 Citation valid，两个历史 Registry version 各 4 条 stale；17/40 模型调用、21/100 工具调用。
- 真实运行补强了 arXiv 核心短语查询、远程 PDF `Content-Length`/EOF 完整性、Report exact-statement 白名单、首次 strict failure regeneration 入口与 Citation stale cache 投影。兼容 provider 仍必须使用含 `/v1` 的 API 前缀并显式 `LLM_JSON_RESPONSE_FORMAT=false`。
- iter13 将 schema 升至 v7：新增版本化 `research_artifacts` 与 owner-scoped `research_run_papers`；fresh、v6→v7、v2→v7、失败回滚和伪造 v7 fail-closed 已覆盖。
- Chat 深度研究现创建十步 `mode='topic'` Run：ResearchBrief、query planning、本地/arXiv 检索、去重导入、筛选、全文获取/Docling、证据阅读、PaperBrief 抽取和 dataset finalize；standalone `/api/research/runs` 继续保留三步确定性 Harness。
- 新增 Coordinator/Search/Screening/Reader/Extraction Agent 的严格版本化 Pydantic 契约；真实模型输出只有通过论文 identity、当前 ACL、PDF asset/document/chunks source hash 与 evidence 白名单校验后才能落库。缺少 `LLM_API_KEY` 明确失败为 `llm_configuration_unavailable`。
- Tool Registry 首批注册本地论文检索、arXiv、去重导入、PDF、Docling、Chunk 和 Evidence；声明输入/输出、owner scope、幂等、timeout/retry、外部调用、安全摘要和错误码。副作用工具单次执行，导入/Run 关联、PDF 绑定与 Docling commit 均有 lease/source-hash fencing。
- topic 默认预算为 50 候选、12 全文、40 模型调用、100 工具调用和 1800 秒；调用前后原子更新，越界前进入 `waiting_input` 并创建继续/缩小/停止 Decision。
- Research API 新增 owner-only Artifact 列表/指定版本、Run Paper 阶段列表和 PaperBrief；撤回 public upload 后，Run Paper、聚合 Artifact、Step evidence 与 SSE event payload 都按当前 ACL 动态隐藏。
- Workflow 现展示真实 ResearchBrief、候选/入选/排除、全文阶段、筛选理由、预算、工具摘要和 PaperBrief；三档响应式、Task Center Peek、Decision、控制、深浅色、reduced-motion 与长文本溢出已有 Playwright fixture 回归。
- iter12 将 schema 升至 v6：`chat_messages.content_parts_json` 保存受控 text / `research-run` data part；旧 `content` 保留为模型上下文与兼容投影，v5 旧消息用 Python JSON 安全回填。
- 新增 `/api/chat/route`：显式普通/深度模式不调用分类模型，auto 先走保守中英文规则，仅模糊输入调用依赖注入的真实结构化分类器；分类不可用时零写入并返回 `routing_unavailable`。
- Chat Research 创建在短 `BEGIN IMMEDIATE` 中原子写入用户消息、Run、三步/created event、assistant Run 卡和 thread head；稳定消息 ID 支持一致重放，不一致碰撞 409，executor 只在 commit 后唤醒。
- assistant-ui 历史直接恢复原生 `{type:"data", name:"research-run", data:{run_id}}`；卡片只持久化 Run ID，实时状态从 owner-only Run API 获取，Run 卡隐藏重新生成操作。
- 主页正式采用全局侧栏 / Chat / Workflow 三栏；1024px 使用右侧 Drawer，390px 使用 `100vw × 100dvh` Workflow，mini 状态条位于 composer 上方。Workflow、Step、Decision、Controls 由 Chat、任务中心 Peek 和独立 Run 页复用。
- 当前可见 Run 使用一条 SSE 作为失效信号，150ms 合并快照刷新、Event ID 去重并以 `state_version` 拒绝旧数据；历史任务只使用轻量列表查询。
- iter11 建立 schema v5 Research Harness：`research_runs`、`research_steps`、`research_events`、`research_decisions`，数据库是任务状态的唯一真相源。
- FastAPI lifespan 启停单 worker `ResearchExecutor`；60 秒租约、15 秒 heartbeat，工作与心跳分线程，owner + lease generation + expiry CAS 阻止旧 worker 续租或提交。
- Research API 支持创建、列表、快照、安全暂停/继续/取消/重试、Decision 回答和带递增 Event ID/`Last-Event-ID` 的 SSE；非 owner 统一 404。
- 当前 Harness 只执行 normalize/plan/finalize 三个确定性骨架 step，不调用 arXiv、Docling 或模型，不写入论文调研声明。
- 前端全局任务中心与 `/runs/:runId` 支持分组查看、原地 Peek、恢复步骤和控制请求；Harness 创建入口已收敛到 Chat Research 路由。
- `App.tsx` 已引入路由级懒加载，主入口 chunk 从约 913 kB 降到 412.58 kB；Chat 为独立 427.51 kB chunk。
- iter08 已建立 `api -> services -> repositories -> db` 外层分层；`main.py` 只负责生命周期、中间件、内存 SessionStore 和 Router 挂载。
- iter09 已加入用户名/密码认证：Argon2id 哈希、内存 Session、HttpOnly SameSite=Lax Cookie，以及注册、登录、登出和当前用户 API。
- 业务 Router 统一通过 `CurrentUser` 解析身份，不再信任 `X-User-ID`；除 health/auth 入口外，35 个业务 API method/path 全部要求登录。
- SQLite schema version 为 10；启动时支持 v2→v3→v4→v5→v6→v7→v8→v9→v10 连续前迁，失败 DDL 回滚且伪造/缺约束 v10 fail closed。
- arXiv/USENIX/SIGOPS 等论文继续全局共享；用户上传通过独立 `paper_uploads` 记录 owner、visibility、provenance、moderation status 与原始文件名，新上传默认 private。
- 私有上传访问控制覆盖目录、详情、PDF、Chunk、处理/解析/概要、资料库、历史、论文 Chat、Wiki/FTS/Graph、classic/agentic QA 与只读论文工具；缺失授权元数据的 upload 默认不可见。
- 资料库/收藏、笔记、阅读历史、订阅、统计和聊天继续按用户隔离；公开上传收回为 private 后，其他用户遗留关联数据保留但立即从读取视图隐藏。
- 前端增加登录/注册门、当前用户名和登出入口；普通 API 与 Chat SSE 均使用 `credentials: include` 自动携带 Session Cookie。
- 当前用户校验失败时前端立即退回认证页；重新登录前会清除旧用户的 React Query 私有数据缓存，避免 Session 失效后的跨账号视图残留。
- `database.py` 暂时保留为旧测试和 smoke 脚本的兼容 facade；新生产调用使用分层模块。
- 主页通用 Chat 与单篇论文 Chat 继续共用 assistant-ui 消息树和 SSE 流式响应；通用 Chat 不自动读取论文、资料库或 Agent 工具。

## Authentication Flow

```text
register/login
    -> Argon2id users.password_hash in SQLite
    -> random opaque session id in MemorySessionStore
    -> HttpOnly SameSite=Lax cookie
    -> CurrentUser dependency
    -> user-scoped service/repository query
```

Session 只存在当前 Python 进程内存；进程重启会要求重新登录。多 worker 或多实例部署前必须替换为 Redis 等共享 `SessionStore`。

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
.\.venv\Scripts\python.exe -m mypy
npm run build
git diff --check
```

结果：146 个后端测试通过；strict mypy 通过；前端生产构建通过。隔离端口 Playwright 为 9 passed、6 skipped：1440px、1024px、390px 的连续路径覆盖 Chat → topic Run → 固定报告 → Citation Evidence → 论文 Chunk 定位 → 研究项目 → Graph Evidence，并保留 Coverage/Decision、版本、键盘/焦点、reduced-motion、无溢出、44px、Harness、Chat/Paper Chat 回归。认证性能 smoke 使用隔离 v9/120-paper fixture：100 requests / 100 workers、0 failures、p95 0.3129s、max 0.3160s、Run create 0.0058s。经用户授权的全功能真实网页巡检使用隔离 v9 库、正确 `/v1` API 前缀、可用真实模型与 `LLM_STREAMING=false`，完成普通 Chat、8 篇真实 arXiv 导入、13,970-token SmartRAG Docling、概要、Paper Chat、目录推荐、项目、17/17 步 topic Run、报告和 Citation Evidence 定位；修复后桌面/移动视觉及语义 DOM 复核无新增 console error。离线 dataset validation 为 60/60 通过，固定 60-case 真实 judge 未运行，macro-F1/supported precision/false-accept 明确未验证。默认旧库未修改。

## Known Risks

- `MemorySessionStore` 不支持跨进程共享，后端重启会清空登录态；生产扩容前需切换 Redis。
- 当前没有登录限流、密码重置、邮箱验证和角色/管理员模型；SameSite=Lax 适合当前同站部署，跨站生产拓扑需重新评估 CSRF/Origin 策略。
- v2 legacy 用户没有可恢复密码，迁移后保持禁用；其历史私有数据需要后续显式认领流程。
- 公开上传目前只记录 `unreviewed/approved/rejected` 状态，没有管理员审核、内容扫描、举报或下架工作流；用户显式 public 后立即对登录用户可见。
- 尚未实现分享链接、团队空间、上传删除和对象存储级 ACL；相同 PDF blob 可物理去重，但逻辑权限仍绑定各自 paper/upload 记录。
- Research SSE 当前每连接 1 秒短读轮询，尚未加入用户级 SSE/Run 创建配额；长任务公开前需补资源限制。
- Playwright 的 topic 数据、慢步骤、Decision 和错误态使用测试网络 fixture；生产没有 seed/debug API。真实 PDF/Docling 的浏览器长任务仍需专门的集成环境。
- metadata search 现用轻量 token overlap 召回长查询中的显式命名论文；权限、category 和上限仍严格，但大规模语料后宜迁移到 FTS/BM25。修复后使用首次真实模型查询计划做了确定性复现，尚未再次付费跑完整 17 步 topic Run。
- auto 模式的模型分类器与普通 Chat 都依赖真实 LLM 配置；17 步 topic Run 已完成一次两篇论文的真实付费 smoke，但更大规模、多用户并发、进程中断和真实 provider ambiguous-call 恢复仍主要由依赖注入覆盖。
- durable model operation 的 `started/ambiguous` 状态会阻止自动重发；后续应增加受控人工 Decision/运维恢复，而不是静默 retry。
- 报告事实文本仍使用已验证 Claim/Matrix 原句白名单。Iter16 的 Citation entailment gold set/scorer 是离线验收工具，尚未接入生产 Validator；真实 judge 和人工复核/导出门禁完成前不能放宽自由改写。
- 当前没有前端 LLM 配置页；真实模型只能在启动后端前通过 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_CHAT_MODEL`、必要时的 `LLM_JSON_RESPONSE_FORMAT` 和 `LLM_STREAMING` 环境变量配置，修改后需重启后端。兼容服务的 `LLM_BASE_URL` 必须是 API 前缀（通常含 `/v1`），模型名应先与该 Key 的 `/models` 列表核对；仅支持非流式 Chat Completions 时设置 `LLM_STREAMING=false`。topic Run 可能使用多次付费调用，运行 smoke 前必须单独确认。前端不得读取或持久化真实 Key。
- 当前验证的兼容网关/模型拒绝 `response_format=json_object`（脱敏 `provider_http_400`）；使用该组合需显式配置 `LLM_JSON_RESPONSE_FORMAT=false`。结构化调用仍注入完整 JSON Schema 并做严格 Pydantic 校验；模型层不隐藏重试，保证一次预算预占对应一次 provider 请求。
- 仓库现存默认 `backend/data/arxiv_wiki.sqlite3` 是用户旧 v0 库（116 篇），本轮没有修改或重建；验证全部用独立 `DATABASE_PATH`。如需承接该数据，必须另立 legacy v0 迁移任务。
- `database.py` 仍作为兼容 facade；`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含历史领域 SQL。
- 普通导入/上传后的 PDF 下载与 Docling 已异步化并可超时终止，但 topic DeepResearch 动态发现论文仍通过 `research_tools.py` 同步等待全文；它尚未复用 v10 加工任务，也没有“非关键论文失败后继续”的步骤策略，不能宣称原 17 步阻塞问题完全解决。
- 论文加工执行器当前仍是 FastAPI 进程内的 SQLite 单机单槽监督器；可跨重启恢复，但多实例扩容前应抽为独立服务/专用队列。极端超大正文的预计算阶段只有写前延长租约保护，后续可增加循环级心跳。

## Next Candidates

1. 下一轮按已确认范围一起处理库内搜索工具、文件夹范围语义、DeepResearch 作为 Chat 能力接入，以及唯一工具型 Agent/`qa_agent.py` 的兼容迁移；不要重新把固定步骤命名为 Agent。
2. 让 topic DeepResearch 复用 v10 持久化加工任务：等待已有任务、对单篇 fetch/parse 失败做可审计的跳过/降级、保留足够论文时继续，必要时稍后续跑而不是整条 Run 卡死。
3. 在上述统一执行入口上增加 Context Engineering：明确保留研究目标、已确认事实、论文原始定位与引用链，分层压缩过程信息，并确保摘要可回到原文 Chunk/Evidence。
4. 经用户单独付费授权后，在固定 60-case gold set 上运行真实 judge；若未达到阈值，保留失败案例并迭代 prompt/evaluator，不得更新产品文案为已达标。
5. 多实例部署前引入独立任务执行服务/专用队列、Redis Session 与用户级 Run/SSE/模型配额；如需旧 116 篇本地论文，另做可审查的 v0 legacy 迁移。

## Git Notes

- iter08：`docs/iterations/iteration_iter08_backend-layer-refactor.md`。
- iter09：`docs/iterations/iteration_iter09_session-user-isolation.md`。
- iter10：`docs/iterations/iteration_iter10_upload-visibility.md`。
- iter11：`docs/iterations/iteration_iter11_research-run-harness.md`。
- iter12：`docs/iterations/iteration_iter12_chat-run-workflow.md`。
- iter13：`docs/iterations/iteration_iter13_topic-research-pipeline.md`。
- iter14：`docs/iterations/iteration_iter14_cited-research-synthesis.md`。
- iter15：`docs/iterations/iteration_iter15_research-landscape-projects.md`。
- iter16：`docs/iterations/iteration_iter16_research-quality-evaluation.md`。
- iter17：`docs/iterations/iteration_iter17_async-paper-processing.md`。
- 全功能网页巡检：`docs/iterations/bugfix_2026-07-17_full-web-ui-audit.md`。
- Iter17 按完整迭代规范 commit、不 push；push 前仍需 fetch/rebase 并保留远端及本地用户改动。
## Iter18 Workspace Chat Context

- 2026-07-23: Added owner-only Workspaces backed by one research project or library folder, Workspace CRUD, and persisted general-Chat context. Workspace binding now lives in the composer beside route mode and is allowed only before the first message; the backend enforces the same lock. Paper Chat cannot bind a Workspace. Validation completed before the upstream rebase: `backend/tests/test_core.py` (101 passed), frontend build, and `git diff --check`.
- Migration note: upstream Iter17 now occupies schema v10 for async paper processing. Workspace schema changes therefore continue as schema v11 (`v10 -> v11`) after rebase; do not reuse migration version 10.
