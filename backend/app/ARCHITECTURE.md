# Backend Architecture

后端采用外层技术分层，层内文件按业务领域命名：

```text
api/            FastAPI Router、HTTP schema 与请求依赖
auth/           SessionStore、Cookie 会话解析与 CurrentUser
services/       用例编排、业务规则、授权入口与事务边界
repositories/   SQLite 查询和持久化，不依赖 FastAPI
db/             连接、schema/FTS 初始化与 migration runner
```

依赖方向：

```text
Router -> Service -> Repository -> SQLite
                  -> external integrations
```

## Layer Responsibilities

- `main.py` 只创建应用、安装中间件并挂载 Router。
- Router 负责 HTTP 参数、状态码和领域异常映射，不写 SQL，也不直接引用 Repository。
- Service 负责跨 Repository 的用例、提交/回滚和后续用户授权检查。
- Repository 接受显式数据库连接和领域参数；为了兼容 iter08 之前的调用，部分写方法暂时保留 `commit=True`，新 Service 应传入 `commit=False` 并统一提交。
- `auth/` 从 HttpOnly Cookie 读取不透明 Session ID，并在每次请求时确认数据库用户仍然有效；业务 Router 不接受客户端用户 ID 作为身份来源。
- `MemorySessionStore` 只适用于当前单进程部署；多 worker/多实例部署时应保持接口不变并替换为 Redis 实现。
- `db/migrations/runner.py` 提供连续版本迁移和事务回滚；schema v4 已注册 v2→v3 的用户归属迁移和 v3→v4 的上传可见性迁移。

## Transitional Compatibility

`database.py` 是 iter08 的兼容 facade，供旧测试和尚未迁移的 Service 导入。新生产代码应直接使用 `db`、`repositories` 和 `services`。后续迭代在所有旧导入迁完后删除 facade。

LLM、PDF、AssetStore 和论文来源抓取目前仍位于 `services/` 下的历史路径；它们是外部适配器，后续可在不改变业务接口的独立重构中迁入 `integrations/`，本轮不为目录纯度扩大改动范围。

`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含 iter08 之前的领域 SQL。它们是明确记录的渐进迁移例外；新增 HTTP 用例不得继续把 SQL 放入 Router，后续应按功能风险逐个提取 Repository，而不是再次进行大爆炸式搬迁。
