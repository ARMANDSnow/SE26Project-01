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
- `db/migrations/runner.py` 提供连续版本迁移和事务回滚；当前 schema v7 支持 v2→v7 连续前迁并对关键列、FK、索引、唯一约束和 CHECK fail closed。

## Topic Research Data Pipeline

- Chat 深度研究创建 `mode='topic'` 的十步 Run；standalone Harness 保留三步确定性骨架，两者共享 lease、heartbeat、Decision、SSE 和控制状态机。
- `research_artifacts` 按 Run/type/version 追加严格 Pydantic 产物，checkpoint 使用幂等键；`paper_brief` 必须关联论文并同时匹配当前 PDF asset、Docling document、Chunk 引用与 source hash。
- `research_run_papers` 保存 Run 内论文当前阶段、排名、评分与筛选理由；读取时重新检查论文当前 ACL，公开上传收回 private 后聚合 Artifact、Run Paper、Step evidence 投影与事件 payload 同步隐藏。
- `research_tools.py` 是统一 Tool Registry，声明输入/输出、owner scope、幂等性、timeout/retry、外部调用和安全摘要。导入与 Run 关联在同一 fenced 事务中；PDF 绑定和 Docling 最终提交在 lease/source-hash CAS 下完成。
- 模型输出不能直接成为数据库真相：Coordinator/Search/Screening/Extraction 先通过 `extra='forbid'` 的版本化 schema，再经过身份、权限、source hash、证据白名单和脱敏检查。
- 结构化模型调用把目标 Pydantic JSON Schema 写入系统提示；默认请求 provider JSON mode。不支持 `response_format` 的兼容 provider 必须显式配置 `LLM_JSON_RESPONSE_FORMAT=false`，返回值仍使用同一 strict schema fail closed。模型层不做隐藏 provider retry，确保每个持久化预算槽只对应一次真实调用。
- topic budget 在数据库中持久化；模型/工具调用原子预占和结算，候选/全文按实际唯一 Run Paper 计数。越界前转为 `waiting_input` 并创建服务端受控 Decision。

## Transitional Compatibility

`database.py` 是 iter08 的兼容 facade，供旧测试和尚未迁移的 Service 导入。新生产代码应直接使用 `db`、`repositories` 和 `services`。后续迭代在所有旧导入迁完后删除 facade。

LLM、PDF、AssetStore 和论文来源抓取目前仍位于 `services/` 下的历史路径；它们是外部适配器，后续可在不改变业务接口的独立重构中迁入 `integrations/`，本轮不为目录纯度扩大改动范围。

`conversations.py`、`documents.py`、`search.py` 和 `paper_tools.py` 仍包含 iter08 之前的领域 SQL。它们是明确记录的渐进迁移例外；新增 HTTP 用例不得继续把 SQL 放入 Router，后续应按功能风险逐个提取 Repository，而不是再次进行大爆炸式搬迁。
