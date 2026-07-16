# Agent Handoff

最后更新：2026-07-16，iter13 closeout。

## Current Status

- 当前分支：`codex/agentic-research-refactor`；Agentic Research 产品基线和 iter11 均在本分支，尚未 push。
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
- SQLite schema version 为 7；启动时支持 v2→v3→v4→v5→v6→v7 连续前迁，失败 DDL 回滚且伪造/缺约束 v7 fail closed。
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

结果：104 个后端测试通过；strict mypy 覆盖 52 个源文件并通过；前端生产构建和 `git diff --check` 通过。Playwright 为 6 passed、6 skipped：1440px、1024px、390px topic flagship/刷新/真实数据/Task Center/深浅色/长文本通过，桌面额外覆盖 Budget Decision、暂停/继续/停止/重试、普通 Chat 分支和 Paper Chat 路由隔离。主入口约 450.38 kB、Chat 432.87 kB，低于 Vite 500 kB 建议线。真实 arXiv smoke 返回 `2607.14046`；经用户单独授权，`gpt-5.5-medium` 的最小 Chat smoke 与严格 ResearchBrief smoke 均通过。

## Known Risks

- `MemorySessionStore` 不支持跨进程共享，后端重启会清空登录态；生产扩容前需切换 Redis。
- 当前没有登录限流、密码重置、邮箱验证和角色/管理员模型；SameSite=Lax 适合当前同站部署，跨站生产拓扑需重新评估 CSRF/Origin 策略。
- v2 legacy 用户没有可恢复密码，迁移后保持禁用；其历史私有数据需要后续显式认领流程。
- 公开上传目前只记录 `unreviewed/approved/rejected` 状态，没有管理员审核、内容扫描、举报或下架工作流；用户显式 public 后立即对登录用户可见。
- 尚未实现分享链接、团队空间、上传删除和对象存储级 ACL；相同 PDF blob 可物理去重，但逻辑权限仍绑定各自 paper/upload 记录。
- Research SSE 当前每连接 1 秒短读轮询，尚未加入用户级 SSE/Run 创建配额；长任务公开前需补资源限制。
- Playwright 的 topic 数据、慢步骤、Decision 和错误态使用测试网络 fixture；生产没有 seed/debug API。真实 PDF/Docling 的浏览器长任务仍需专门的集成环境。
- auto 模式的模型分类器与普通 Chat 都依赖真实 LLM 配置；本轮真实验证了普通 Chat 与 Coordinator ResearchBrief，分类器及完整十步 topic Run 仍主要由依赖注入覆盖。
- 当前没有前端 LLM 配置页；真实模型只能在启动后端前通过 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_CHAT_MODEL` 和必要时的 `LLM_JSON_RESPONSE_FORMAT` 环境变量配置，修改后需重启后端。兼容服务的 `LLM_BASE_URL` 必须是 API 前缀（通常含 `/v1`）。topic Run 可能使用多次付费调用，运行 smoke 前必须单独确认。前端不得读取或持久化真实 Key。
- 当前验证的兼容网关/模型拒绝 `response_format=json_object`（脱敏 `provider_http_400`）；使用该组合需显式配置 `LLM_JSON_RESPONSE_FORMAT=false`。结构化调用仍注入完整 JSON Schema 并做严格 Pydantic 校验；模型层不隐藏重试，保证一次预算预占对应一次 provider 请求。
- 仓库现存默认 `backend/data/arxiv_wiki.sqlite3` 是用户旧 v0 库（116 篇），本轮没有修改或重建；验证全部用独立 `DATABASE_PATH`。如需承接该数据，必须另立 legacy v0 迁移任务。
- `database.py` 仍作为兼容 facade；`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含历史领域 SQL。
- Docling 解析与远程 PDF 下载仍是同步长任务；最终提交已有 lease/source-hash CAS，失去 lease 后不会成为数据库真相，但 Python 线程不能抢占正在运行的 CPU 解析。大批量使用需要可取消进程 worker/任务队列。

## Next Candidates

1. Iter14：基于版本化 PaperBrief 实现 Synthesis Agent、对比矩阵、研究报告和 Run 级 Evidence/Citation Registry，并继续严格校验 source hash。
2. 引入可取消进程 worker/任务队列，为 arXiv/PDF/Docling/模型调用提供跨进程 lease、超时和资源配额。
3. 为 Research SSE、Run 创建和模型调用增加用户级连接/速率限制；SessionStore 迁移 Redis。
4. 如需使用旧 116 篇本地论文，先设计可审查、不破坏的 v0 legacy 迁移，不要直接 reset。

## Git Notes

- iter08：`docs/iterations/iteration_iter08_backend-layer-refactor.md`。
- iter09：`docs/iterations/iteration_iter09_session-user-isolation.md`。
- iter10：`docs/iterations/iteration_iter10_upload-visibility.md`。
- iter11：`docs/iterations/iteration_iter11_research-run-harness.md`。
- iter12：`docs/iterations/iteration_iter12_chat-run-workflow.md`。
- iter13：`docs/iterations/iteration_iter13_topic-research-pipeline.md`。
- 尚未 push；推送前先 fetch/rebase 并保留远端用户改动。
