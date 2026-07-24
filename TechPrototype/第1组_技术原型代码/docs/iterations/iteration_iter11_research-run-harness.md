# Iter11 — Research Run 与可恢复 Harness

## Context

PaperWiki 已有可分支 Chat、论文导入与 Docling 解析、Chunk/FTS5 检索、证据白名单、Session 隔离和资料库。本轮在不改写这些契约的前提下，建立数据库驱动、可恢复的 Research Harness 骨架。

## Goals

- schema v5 新增 Run、Step、Event 和 Decision，完整保存运行状态。
- FastAPI lifespan 管理单进程、单 worker 的 `ResearchExecutor`，支持租约回收与幂等 step 领取。
- 提供 owner-only 创建、列表、快照、暂停、继续、取消、重试、Decision 回答与 SSE 续传 API。
- 运行明确标记为 Harness 骨架的确定性三步流程，不生成论文调研结论。
- 前端引入路由级懒加载、最小 Run 详情和全局任务中心。

## Scope

- 本轮不调用 arXiv、Docling 或付费模型，不伪造调研产物。
- 保持 `/api/chat/runs` 和 assistant-ui 消息树契约不变。
- 不复制高保真原型的独立 CSS、模拟计时器或假进度。

## Acceptance Criteria

- v4 可连续迁移到 v5，新库和迁移库结构一致；非法 v5 伪结构 fail closed。
- Step 原子领取携带 lease generation/fencing；heartbeat 和完成只能由当前 owner+generation 写入。
- 租约为 60 秒，heartbeat 为 15 秒；过期 `running` step 启动时可回收。
- pause/cancel 只写 `requested_action`，executor 在安全边界转换终态，旧 worker 不能覆盖新 attempt。
- SSE Event ID 单调递增，支持 `Last-Event-ID`，非 owner 对 Run/Decision 统一得到 404。
- 任务中心按等待确认、执行中、完成、失败分组，关键状态可见且可键盘操作。
- 后端测试、strict mypy、前端 build、相关 Playwright 和 `git diff --check` 通过。

## Plan

1. 完成 schema v5 迁移、结构校验和迁移测试。
2. 实现 Research repository、状态机、确定性 Harness 和租约 executor。
3. 接入 lifespan 和 owner-only REST/SSE API，完成中断恢复与权限测试。
4. 实现前端类型、API/query、懒加载 Run 页和任务中心。
5. 执行验证、收尾只读审查、修复、iter-finish 和独立 commit。

## Risks And Questions

- SQLite 写锁：所有 claim、checkpoint 和 event 只用短事务，绝不跨网络/解析持有写事务。
- 租约脑裂：每次 claim 递增 `lease_generation`，所有后续写带 owner+generation CAS。
- 安全停止：pause/cancel 是请求而不是客户端自行判定的终态。
- 隐私隔离：Run 与所有子对象查询都从 Session user_id 连回 `research_runs`，非 owner 返回 404。
- CORS 现有任意 localhost 端口正则会放大 cookie 写 API 的本机 CSRF 面，本轮收紧到明确开发端口。

## Progress Notes

- 2026-07-16：从 `main@b4d9dcc` 创建 `codex/agentic-research-refactor`；恢复 npm/Python 依赖。
- 2026-07-16：基线验证为 70 tests、strict mypy 通过、前端 build 通过（首包 912.91 kB，作为 Iter16 拆包基线）。
- 2026-07-16：已独立提交产品文档、UI/UX 架构和 Agentic Research 原型基线，commit `e4dc021`。
- 功能差距、质量风险和 UI/UX 三路开工审查已启动。已吸收：lease fencing、SQLite 短事务、owner JOIN、单一 SSE/cache 来源、路由懒加载、避免重复侧栏和移动端双滚动。
- 2026-07-16：完成 schema v5、Research repository/state machine、lifespan executor、owner-only REST/SSE 和确定性三步 Harness。
- 2026-07-16：完成前端路由懒加载、任务中心、Run 详情/控制和 Playwright 基础设施；主入口 chunk 降至 412.58 kB。
- 2026-07-16：真实点击发现并修复 Radix Sheet 关闭不返回焦点，desktop/390px 均验证通过。
- 2026-07-16：收尾审查修复过期 lease 仍可提交、Decision 恢复卡死、waiting_input 错误暂停、cancel 遗留 Decision、手动 retry 无新 attempt、executor 异常退出、内部 lease 字段暴露和错误文本敏感信息落库等问题。

## Closeout

### Summary

完成可恢复 Research Harness 的首轮生产骨架。数据库保存 Run/Step/Event/Decision，executor 用短事务领取任务并以 owner + generation + expiry 提交；暂停/取消在安全边界生效。产品界面可创建、分组查看和恢复 Harness，且明确不把骨架输出伪装为论文调研。

### Validation

- `.venv/bin/python -m pytest backend/tests -q`：80 passed。
- `.venv/bin/python -m mypy`：49 个源文件 strict 检查通过。
- `npm run build`：通过；主入口 412.58 kB，Run chunk 4.84 kB，Chat chunk 427.51 kB。
- `npm run test:e2e`：desktop Chromium 与 390px Chromium 共 2 passed。
- `git diff --check`：通过。
- 未运行真实 arXiv 网络或付费模型 smoke；本轮 Harness 不需要外部依赖。

### Review

- 开工只读审查：功能差距、后端质量/安全、UI/UX 三路完成，结论已转化为代码与验收条件。
- 收尾只读审查：正确性、安全/契约、UI/UX 均无剩余 P0/P1。
- UI 审查直接促成任务 Drawer 导航自动关闭、失败态反馈、中文状态和焦点返回修复。

### Follow-ups

- Iter12 建立 `content_parts_json`、`/api/chat/route`、Research Run data part 与 Workflow UI。
- 将任务中心与 Run 页的轮询收敛为用户级单 SSE/React Query 桥接，并加入连接/Run 创建限额。
- 若需延续现有 116 篇 v0 本地数据，另立可审查 legacy 迁移；不重建、不修改该用户数据库。
