# Iteration iter08 - 后端分层与迁移基础重构

## Context

iter07 已完成通用持久化 Chat，并快进合入 `codex/develop`。当前 FastAPI 路由、Pydantic 请求模型和部分业务异常映射集中在 `backend/app/main.py`；`backend/app/database.py` 同时负责连接、schema、Repository 查询、事务提交和部分业务规则。下一轮将引入服务端 Session、用户数据隔离和 schema migration，因此需要先建立清晰、可测试的 HTTP、Service、Repository 与数据库基础设施边界。

## Goals

- 将 FastAPI 应用装配与业务 Router 分离，`main.py` 只负责生命周期、中间件和挂载。
- 将请求/响应 schema 从 Router 中抽离。
- 将数据库连接、schema 初始化和领域 Repository 从单体 `database.py` 中拆分。
- 明确 Router、Service、Repository、Integration 的依赖方向和事务职责。
- 保持现有 API 契约、schema version 2、前后端行为和真实 LLM 边界不变。

## Scope

- `backend/app/api/`：Router、HTTP schema 和后续认证依赖的入口结构。
- `backend/app/db/`：SQLite 连接、schema 初始化和后续 migration runner 的基础结构。
- `backend/app/repositories/`：论文、资料库、学习数据和对话持久化入口。
- 现有 Service 的导入和事务边界整理。
- 后端回归测试、mypy、前端构建和文档更新。

不包含：用户登录、密码哈希、SessionStore、删除 `X-User-ID`、私有上传权限、schema v3 或任何用户数据迁移。

## Acceptance Criteria

- `backend.app.main:app` 启动入口保持不变。
- 现有 API 路径、请求体、响应体和状态码保持兼容。
- `main.py` 不再承载领域路由实现。
- SQLite schema version 仍为 2，现有数据库兼容门禁不变。
- Repository 不依赖 FastAPI；Router 不直接承载领域 SQL。
- 后端测试、mypy、前端生产构建和 `git diff --check` 通过。

## Plan

1. 拆分 Pydantic schema 与按领域 APIRouter，保持路由契约不变。
2. 提取 SQLite 连接/schema 基础设施，并将数据库访问按领域迁移到 Repository。
3. 整理 Service 与 Repository 的调用方向和事务职责，保留必要兼容导出。
4. 运行完整回归并修复重构引入的问题。
5. 完成 closeout、handoff 和后续 Session/隔离迭代建议。

## Risks And Questions

- `database.py` 被测试和多个 Service 直接引用，拆分必须保留清晰的兼容路径，避免一次性破坏过多导入。
- Chat SSE 在准备运行和流式执行阶段使用不同数据库连接，不能因事务整理改变已持久化的运行状态。
- 当前部分 GET 路径会写入阅读历史或惰性初始化资料库；本轮记录问题但不改变 API 行为。
- 结构重构不能夹带 schema 或认证语义变化，否则难以判定回归来源。

## Progress Notes

- 2026-07-15：fetch 后确认 `codex/general-chat-foundation` 相对 `codex/develop` 为 0/1 纯快进关系；已使用 `--ff-only` 合入 develop，并创建 `codex/refactor-backend-layers`。
- 2026-07-15：确认采用外层 `api/services/repositories/db/integrations` 分层，文件在各层内按业务命名。
- 2026-07-15：将 `main.py` 缩减为应用装配入口，按 system/ingest/papers/chat/knowledge/library 拆分 Router，并集中 Pydantic schema。
- 2026-07-15：将 SQLite 连接、schema/FTS、论文、资料库、学习数据和统计查询拆入 `db/` 与 `repositories/`；`database.py` 保留为迁移期兼容 facade。
- 2026-07-15：Router 已不再直接写 SQL 或引用 Repository；抓取、论文、资料库、知识与系统用例通过 Service 编排。
- 2026-07-15：增加独立 migration runner 及连续版本检查测试，当前 schema v2 启动行为保持不变。

## Closeout

### Summary

- `backend.app.main:app` 启动入口保持不变，`main.py` 只负责生命周期、CORS 和 Router 挂载。
- 新增 `api/routers` 与集中 HTTP schema，按 system、ingest、papers、chat、knowledge、library 拆分 35 个 API method/path 组合。
- 将 SQLite 连接与 schema/FTS 初始化拆入 `db/`，将论文、资料库、学习数据和统计查询拆入 `repositories/`。
- papers、library、knowledge、system 和 ingest Router 通过 Service 调用 Repository；HTTP 层不再写 SQL 或直接依赖 Repository。
- `database.py` 缩减为兼容 facade，保留旧测试和 smoke 脚本导入；新生产代码使用分层模块。
- 增加独立 migration runner、连续版本校验和回滚基础，当前 schema version 仍为 2，启动兼容门禁未改变。
- 增加后端架构文档并扩大 strict mypy 覆盖，从原 9 个文件增加到 34 个源文件。

### Validation

- `.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-iter08-final -p no:cacheprovider`：61 passed。
- `.\.venv\Scripts\python.exe -m mypy`：34 个源文件通过 strict 检查。
- `npm run build`：通过；保留既有约 909 kB bundle 警告。
- API route smoke：35 个 method/path 组合，无重复路由。
- `git diff --check -- . ':!UIPrototype/**'`：通过。
- 密钥/密码模式差异检查：未发现新增密钥、密码或私钥内容。

### Review

主 agent 完成本地只读差异、依赖方向、路由重复、schema 版本、事务和密钥检查。依照仓库规则，本轮未在用户未授权 subagent 的情况下调用 subagent。未发现阻断问题；schema v2、API 路径和前端契约保持不变。

### Follow-ups

- iter09 实现内存 `SessionStore`、用户名/密码登录、`CurrentUser` 依赖和用户数据隔离，并注册 schema v3 migration。
- 将测试与 smoke 脚本迁离 `database.py` 兼容 facade 后删除该 facade。
- 渐进提取 `conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 中的历史领域 SQL。
- 视后续收益将 LLM、AssetStore、PDF 和来源抓取适配器迁入 `integrations/`。
