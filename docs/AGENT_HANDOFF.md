# Agent Handoff

最后更新：2026-07-15，iter09 closeout。

## Current Status

- 当前分支：`codex/refactor-backend-layers`；本地 `codex/develop` 已 fast-forward 包含 iter07，iter08 与 iter09 在当前分支尚未 commit 或 merge。
- iter08 已建立 `api -> services -> repositories -> db` 外层分层；`main.py` 只负责生命周期、中间件、内存 SessionStore 和 Router 挂载。
- iter09 已加入用户名/密码认证：Argon2id 哈希、内存 Session、HttpOnly SameSite=Lax Cookie，以及注册、登录、登出和当前用户 API。
- 业务 Router 统一通过 `CurrentUser` 解析身份，不再信任 `X-User-ID`；除 health/auth 入口外，35 个业务 API method/path 全部要求登录。
- SQLite schema version 为 3；启动时会把 v2 私有数据迁移到 user 1，并将没有密码的旧占位用户标记为禁用 legacy 账户。
- papers、wiki、concepts、解析正文和概要仍为全局共享知识；资料库/收藏、笔记、阅读历史、订阅、统计和聊天按用户隔离。
- 前端增加登录/注册门、当前用户名和登出入口；普通 API 与 Chat SSE 均使用 `credentials: include` 自动携带 Session Cookie。
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
.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-iter09-final -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy
npm run build
git diff --check -- . ':!UIPrototype/**'
```

结果：67 个后端测试通过；strict mypy 覆盖 43 个源文件并通过；前端生产构建通过；35 个业务 API method/path 全部受 `require_user` 保护；`git diff --check` 通过。Vite 仍提示主包约 912 kB，属于既有代码分割 follow-up。本轮未运行付费真实 LLM smoke。

## Known Risks

- `MemorySessionStore` 不支持跨进程共享，后端重启会清空登录态；生产扩容前需切换 Redis。
- 当前没有登录限流、密码重置、邮箱验证和角色/管理员模型；SameSite=Lax 适合当前同站部署，跨站生产拓扑需重新评估 CSRF/Origin 策略。
- v2 legacy 用户没有可恢复密码，迁移后保持禁用；其历史私有数据需要后续显式认领流程。
- 用户上传论文尚未建模 owner/visibility/provenance/moderation；当前上传仍进入全局 papers 目录，因此不要把它当作私有上传能力。
- 前端认证流程尚无 Playwright 回归，只完成 TypeScript/Vite 构建与后端 API 契约测试。
- 前端主 bundle 仍超过 Vite 500 kB 建议阈值，后续可按路由和 assistant-ui 组件拆包。
- `database.py` 仍作为兼容 facade；`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含历史领域 SQL。
- Docling 解析与远程 PDF 下载仍是同步长任务；大批量使用需要任务队列。

## Next Candidates

1. 设计私有/公共上传：独立记录 owner、visibility、provenance、moderation，公共 papers 身份继续全局去重。
2. 增加登录限流、密码修改/重置和 legacy 数据认领；部署扩容时实现 RedisSessionStore。
3. 增加登录、登出、跨账户切换与私有视图隔离的 Playwright smoke。
4. 设计 Agent 原生会话内 Context/Tool 状态和可撤销授权，不默认读取论文或资料库。
5. 渐进删除 `database.py` facade，并把剩余历史 SQL 提取到 Repository。

## Git Notes

- iter08：`docs/iterations/iteration_iter08_backend-layer-refactor.md`。
- iter09：`docs/iterations/iteration_iter09_session-user-isolation.md`。
- 功能分支：`codex/refactor-backend-layers`；基线：已包含 iter07 的本地 `codex/develop`。
- iter08 与 iter09 尚未 commit/push/merge；用户希望之后一起合入。提交前检查暂存范围，推送前先 fetch/rebase 并保留远端用户改动。
