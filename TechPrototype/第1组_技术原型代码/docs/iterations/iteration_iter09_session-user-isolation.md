# Iteration iter09 - Session 登录与跨用户数据隔离

## Context

iter08 已建立 `api -> services -> repositories -> db` 分层和 migration runner。现有资料库与聊天虽然预留 `user_id`，HTTP 层仍信任客户端传入的 `X-User-ID`；notes、reading history 与 subscriptions 尚未记录用户归属，无法形成真实的登录和视图隔离边界。

## Goals

- 使用服务端内存 `SessionStore` 管理登录会话，以随机 HttpOnly Cookie 作为不透明会话标识。
- 使用 Argon2id 保存并验证密码哈希，不单独保存盐或明文密码。
- 提供注册、登录、登出和当前用户 API，并在 FastAPI 依赖中统一解析 `CurrentUser`。
- 删除业务 API 对 `X-User-ID` 的信任，所有私有查询从认证用户获得 `user_id`。
- 将 notes、reading history、subscriptions、library 与 chat 按用户隔离。
- 将 SQLite schema 从 v2 可回滚地迁移到 v3，并保留既有数据的用户 ID。
- 增加最小前端登录/注册入口及 Cookie 凭据支持。

## Scope

- `backend/app/auth/`：Session 生命周期、Cookie 配置和认证依赖。
- `backend/app/repositories/users.py`、`services/auth.py`、`api/routers/auth.py`：用户与登录用例。
- schema v2 -> v3 migration，以及私有表的 `user_id` 约束和索引。
- papers 仍为全局共享；资料库、收藏、笔记、阅读历史、订阅和聊天属于当前用户。
- 前端认证门、登录/注册表单、登出入口和 `credentials: include`。

不包含：上传论文 public/private 可见性、找回密码、邮箱验证、持久化/分布式 Session、角色与管理员权限。

## Acceptance Criteria

- 未登录访问业务 API 返回 401；`/api/health` 与 `/api/auth/*` 的公开入口可用。
- 注册后自动建立 Session；登录轮换 Session ID；登出立即失效并清除 Cookie。
- Session 仅存在进程内存，过期后不可使用；Cookie 为 HttpOnly、SameSite=Lax。
- 客户端提交 `X-User-ID` 不能改变当前用户身份。
- 两个用户的收藏、文件夹、笔记、历史、订阅和聊天互不可见或修改。
- v2 数据库能迁移到 v3；legacy 用户被禁用且不会获得默认密码。
- 后端测试、strict mypy、前端生产构建和 `git diff --check` 通过。

## Plan

1. 增加用户 repository、Argon2 服务、内存 SessionStore 与认证依赖。
2. 注册 auth Router，并把业务 Router 从 Header 身份切换到 `CurrentUser`。
3. 实现 schema v3 与 v2 -> v3 migration，迁移私有数据归属。
4. 贯穿 notes/history/subscriptions/paper detail/stats 的用户过滤。
5. 增加前端认证门、登录/注册/登出和 Cookie 凭据。
6. 增加迁移、Session、认证与跨用户隔离测试，完成全量验证。

## Risks And Questions

- 内存 Session 在进程重启后全部失效，且不能直接支持多 worker；未来扩展时替换 `SessionStore` 为 Redis，HTTP 与业务层无需改变。
- 既有 v2 用户没有密码，迁移后只能保持禁用；不能自动生成或暴露默认密码。
- SQLite 表重建必须保留外键与数据，并确保失败时 migration savepoint 回滚。
- Cookie 认证依赖 SameSite 与 CORS 配置；前端所有请求必须显式携带 credentials。

## Progress Notes

- 2026-07-15：完成 iter-start 盘点；确认 `X-User-ID` 存在于 system/papers/chat/library Router，notes/history/subscriptions 缺少用户归属。
- 2026-07-15：确定使用 `argon2-cffi 25.1.0`、进程内 `MemorySessionStore`、HttpOnly SameSite=Lax Cookie；旧 v2 占位用户迁移为禁用 legacy 用户。
- 2026-07-15：实现注册、登录、登出、当前用户 API 和 FastAPI `CurrentUser` 依赖；35 个业务 API method/path 全部受 Session 保护，`X-User-ID` 不再参与身份解析。
- 2026-07-15：完成 schema v3 和 v2→v3 migration；notes、reading history、subscriptions、library、chat 与用户归属贯通，papers/wiki/concepts 保持全局共享。
- 2026-07-15：前端增加登录/注册门、当前用户名与登出入口，所有普通请求和 Chat SSE 均携带 Cookie credentials。
- 2026-07-15：补充 Session 过期、Argon2、Session 轮换、未登录访问、迁移和多类跨用户隔离回归测试。

## Closeout

### Summary

- 新增线程安全的 `MemorySessionStore`，使用 256-bit 级随机不透明 Session ID、滑动过期和 HttpOnly/SameSite=Lax Cookie；Session 不写数据库。
- 用户密码使用 Argon2id 哈希，盐包含在编码后的哈希中；登录错误不区分用户名不存在、密码错误或禁用状态，成功登录会轮换 Session。
- 新增 `/api/auth/register`、`/login`、`/logout`、`/me`；除 health 与 auth 入口外，35 个业务 API method/path 全部依赖 `CurrentUser`。
- schema 升级到 v3，v2 私有数据归属 legacy user 1，旧占位用户迁移为禁用账户且不生成默认密码。
- 收藏/文件夹、笔记、阅读历史、订阅、统计和聊天均按 Session 用户过滤；伪造 `X-User-ID` 不改变身份。
- 前端增加登录/注册页面、登录态门、登出入口与 Cookie credentials；论文等公共知识数据仍由所有已登录用户共享。

### Validation

- `.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-iter09-final -p no:cacheprovider`：67 passed。
- `.\.venv\Scripts\python.exe -m mypy`：43 个源文件通过 strict 检查。
- `npm run build`：通过；Vite 仍提示约 912 kB 主包警告。
- 认证路由审计：35 个业务 method/path 均包含 `require_user`，无匿名遗漏。
- `git diff --check -- . ':!UIPrototype/**'`：通过。

### Review

主 agent 完成本地只读安全与契约审查；依照仓库规则，用户未授权 subagent，本轮未调用。检查范围包括密码/Session 生命周期、Session fixation、Cookie 属性、客户端身份伪造、私有 Repository 过滤、迁移回滚边界和受保护路由覆盖。未发现阻断问题。

### Follow-ups

- 设计上传论文独立的 owner、visibility、provenance 和 moderation 状态；不要通过 `papers.user_id` 混淆公共论文身份。
- 多 worker/多实例部署前将 `MemorySessionStore` 替换为 Redis，并增加登录限流、密码重置和生产 CSRF/Origin 策略。
- 为登录/注册/登出和跨账户切换增加 Playwright smoke。
- 为迁移后的 legacy 数据提供显式管理员认领或密码重置流程；当前 legacy 账户保持禁用以避免默认密码风险。
