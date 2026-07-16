# Agent Handoff

最后更新：2026-07-16，iter11 closeout。

## Current Status

- 当前分支：`codex/agentic-research-refactor`；Agentic Research 产品基线和 iter11 均在本分支，尚未 push。
- iter11 建立 schema v5 Research Harness：`research_runs`、`research_steps`、`research_events`、`research_decisions`，数据库是任务状态的唯一真相源。
- FastAPI lifespan 启停单 worker `ResearchExecutor`；60 秒租约、15 秒 heartbeat，工作与心跳分线程，owner + lease generation + expiry CAS 阻止旧 worker 续租或提交。
- Research API 支持创建、列表、快照、安全暂停/继续/取消/重试、Decision 回答和带递增 Event ID/`Last-Event-ID` 的 SSE；非 owner 统一 404。
- 当前 Harness 只执行 normalize/plan/finalize 三个确定性骨架 step，不调用 arXiv、Docling 或模型，不写入论文调研声明。
- 前端新增全局任务中心与 `/runs/:runId`，支持创建骨架、分组查看、恢复步骤和控制请求；Radix Sheet 关闭后恢复焦点，390px 无横向溢出。
- `App.tsx` 已引入路由级懒加载，主入口 chunk 从约 913 kB 降到 412.58 kB；Chat 为独立 427.51 kB chunk。
- iter08 已建立 `api -> services -> repositories -> db` 外层分层；`main.py` 只负责生命周期、中间件、内存 SessionStore 和 Router 挂载。
- iter09 已加入用户名/密码认证：Argon2id 哈希、内存 Session、HttpOnly SameSite=Lax Cookie，以及注册、登录、登出和当前用户 API。
- 业务 Router 统一通过 `CurrentUser` 解析身份，不再信任 `X-User-ID`；除 health/auth 入口外，35 个业务 API method/path 全部要求登录。
- SQLite schema version 为 5；启动时支持 v2→v3→v4→v5 连续前迁，失败 DDL 回滚且伪造/缺表 v5 fail closed。
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

结果：80 个后端测试通过；strict mypy 覆盖 49 个源文件并通过；前端生产构建通过；Playwright 在 desktop Chromium 和 390px Chromium 各 1 条旗舰流程通过；`git diff --check` 通过。主入口 chunk 412.58 kB，低于 Vite 500 kB 建议线。本轮未运行 arXiv 网络或付费真实 LLM smoke。

## Known Risks

- `MemorySessionStore` 不支持跨进程共享，后端重启会清空登录态；生产扩容前需切换 Redis。
- 当前没有登录限流、密码重置、邮箱验证和角色/管理员模型；SameSite=Lax 适合当前同站部署，跨站生产拓扑需重新评估 CSRF/Origin 策略。
- v2 legacy 用户没有可恢复密码，迁移后保持禁用；其历史私有数据需要后续显式认领流程。
- 公开上传目前只记录 `unreviewed/approved/rejected` 状态，没有管理员审核、内容扫描、举报或下架工作流；用户显式 public 后立即对登录用户可见。
- 尚未实现分享链接、团队空间、上传删除和对象存储级 ACL；相同 PDF blob 可物理去重，但逻辑权限仍绑定各自 paper/upload 记录。
- Research SSE 当前每连接 1 秒短读轮询，尚未加入用户级 SSE/Run 创建配额；长任务公开前需补资源限制。
- 当前没有前端 LLM 配置页；真实模型只能在启动后端前通过 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_CHAT_MODEL` 环境变量配置，修改后需重启后端。前端只能读取“是否已配置”和模型名，不得读取或持久化真实 Key。
- 仓库现存默认 `backend/data/arxiv_wiki.sqlite3` 是用户旧 v0 库（116 篇），本轮没有修改或重建；验证全部用独立 `DATABASE_PATH`。如需承接该数据，必须另立 legacy v0 迁移任务。
- `database.py` 仍作为兼容 facade；`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含历史领域 SQL。
- Docling 解析与远程 PDF 下载仍是同步长任务；大批量使用需要任务队列。

## Next Candidates

1. Iter12：为 `chat_messages` 增加 `content_parts_json`，实现 `/api/chat/route` 与原子 Run 卡消息。
2. Iter12：建立单一 Research SSE/React Query 实时桥接，完成 Chat/Workflow 桌面三栏、平板 Drawer 和 390px 全屏交互。
3. 为 Research SSE 和 Run 创建增加用户级连接/速率限制，并扩展 pause/resume/cancel/retry 的慢步骤 Playwright。
4. 增加安全的“模型配置与可用性”管理界面：可配置 provider/base URL/model 并以 write-only 方式提交 Key；后端仅保存到操作系统 Keychain/部署 secret manager，API 永不回传 Key，仅返回 masked/configured 状态。上线前需明确全局管理员配置还是用户自带 Key，并补权限、CSRF、密钥清洗、日志脱敏和 Playwright 测试。
5. 如需使用旧 116 篇本地论文，先设计可审查、不破坏的 v0 legacy 迁移，不要直接 reset。

## Git Notes

- iter08：`docs/iterations/iteration_iter08_backend-layer-refactor.md`。
- iter09：`docs/iterations/iteration_iter09_session-user-isolation.md`。
- iter10：`docs/iterations/iteration_iter10_upload-visibility.md`。
- iter11：`docs/iterations/iteration_iter11_research-run-harness.md`。
- 尚未 push；推送前先 fetch/rebase 并保留远端用户改动。
