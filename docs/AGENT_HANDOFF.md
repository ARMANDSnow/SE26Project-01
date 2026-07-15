# Agent Handoff

最后更新：2026-07-15，iter10 closeout。

## Current Status

- 当前分支：`codex/develop`；iter07 至 iter10 均已通过 fast-forward 纳入本地 develop，尚未 push。
- iter08 已建立 `api -> services -> repositories -> db` 外层分层；`main.py` 只负责生命周期、中间件、内存 SessionStore 和 Router 挂载。
- iter09 已加入用户名/密码认证：Argon2id 哈希、内存 Session、HttpOnly SameSite=Lax Cookie，以及注册、登录、登出和当前用户 API。
- 业务 Router 统一通过 `CurrentUser` 解析身份，不再信任 `X-User-ID`；除 health/auth 入口外，35 个业务 API method/path 全部要求登录。
- SQLite schema version 为 4；启动时支持 v2→v3→v4 连续迁移。v2 私有数据归到禁用 legacy user 1；v3 历史上传迁移为 legacy public/approved。
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

结果：70 个后端测试通过；strict mypy 覆盖 45 个源文件并通过；前端生产构建通过；`git diff --check` 通过。Vite 仍提示主包约 913 kB，属于既有代码分割 follow-up。本轮未运行付费真实 LLM smoke。

## Known Risks

- `MemorySessionStore` 不支持跨进程共享，后端重启会清空登录态；生产扩容前需切换 Redis。
- 当前没有登录限流、密码重置、邮箱验证和角色/管理员模型；SameSite=Lax 适合当前同站部署，跨站生产拓扑需重新评估 CSRF/Origin 策略。
- v2 legacy 用户没有可恢复密码，迁移后保持禁用；其历史私有数据需要后续显式认领流程。
- 公开上传目前只记录 `unreviewed/approved/rejected` 状态，没有管理员审核、内容扫描、举报或下架工作流；用户显式 public 后立即对登录用户可见。
- 尚未实现分享链接、团队空间、上传删除和对象存储级 ACL；相同 PDF blob 可物理去重，但逻辑权限仍绑定各自 paper/upload 记录。
- 前端认证流程尚无 Playwright 回归，只完成 TypeScript/Vite 构建与后端 API 契约测试。
- 前端主 bundle 仍超过 Vite 500 kB 建议阈值，后续可按路由和 assistant-ui 组件拆包。
- `database.py` 仍作为兼容 facade；`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含历史领域 SQL。
- Docling 解析与远程 PDF 下载仍是同步长任务；大批量使用需要任务队列。

## Next Candidates

1. 增加登录、登出、跨账户切换、私有上传发布/收回与旧视图失效的 Playwright smoke。
2. 设计公开上传审核/举报/下架流程，以及管理员或角色授权模型。
3. 增加登录限流、密码修改/重置和 legacy 数据认领；部署扩容时实现 RedisSessionStore。
4. 设计 Agent 原生会话内 Context/Tool 状态和可撤销授权，不默认读取论文或资料库。
5. 渐进删除 `database.py` facade，并把剩余历史 SQL 提取到 Repository。

## Git Notes

- iter08：`docs/iterations/iteration_iter08_backend-layer-refactor.md`。
- iter09：`docs/iterations/iteration_iter09_session-user-isolation.md`。
- iter10：`docs/iterations/iteration_iter10_upload-visibility.md`。
- `codex/feature-upload-visibility` 已以 `--ff-only` 合入本地 `codex/develop`。
- 尚未 push；推送前先 fetch/rebase 并保留远端用户改动。
