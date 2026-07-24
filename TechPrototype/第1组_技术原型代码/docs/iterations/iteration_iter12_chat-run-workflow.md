# Iter12 — Chat 接入 Research Run 与 Workflow UI

## Context

Iter11 已建立数据库驱动、可恢复的三步 Research Harness。本轮把 Harness 作为 assistant-ui 原生 data part 接入现有 Chat 消息树，并在不破坏普通 Chat 多轮、编辑、重生成和分支契约的前提下完成可恢复 Workflow 体验。

## Goals

- schema v6 为 `chat_messages` 增加版本化 content parts，并兼容全部旧文本消息。
- 新增 `/api/chat/route`，支持自动、普通和深度调研三种模式。
- 原子写入用户消息、Research Run、三步 Harness、Run 卡片和 thread head。
- 用单一当前 Run SSE/React Query 桥接驱动 Chat、Workflow、任务中心和 Run 页。
- 按产品原型完成正式 React/shadcn/Tailwind 三栏、Drawer 和 390px 全屏 Workflow。

## Scope

- 只运行真实的 normalize/plan/finalize 三步 Harness，不调用 arXiv、Docling 或付费模型完成论文调研。
- 原型中的十步流程、论文计数、工具调用数和计时均为设计参考，不进入产品数据路径。
- 不增加生产 seed/debug API，不修改 `UIPrototype/第1组_*` 等用户文件。

## Acceptance Criteria

- v2→v6 连续迁移、v5→v6 回填、失败回滚和伪造 v6 fail closed 全部通过。
- 普通消息的 `content` 与 `content_parts_json` 在创建和流式更新中保持同步。
- 显式模式不调用分类器；自动模式只在模糊输入调用依赖注入的真实分类器。
- Chat Research 创建具备事务原子性、幂等重放和 owner-only 404 隔离。
- 刷新后 Run data card、当前分支和 Workflow 状态均可恢复，不重复创建 Run。
- ≥1200px 为侧栏/Chat/Workflow 三栏，1024px 为 Drawer，390px 为全屏 Workflow 且无溢出。
- 后端测试、strict mypy、前端 build、Playwright 和 `git diff --check` 通过。

## Plan

1. 恢复依赖并确认 Iter11 基线。
2. 完成 schema v6、content part codec、Chat 路由和原子 Research 创建。
3. 完成 assistant-ui data renderer、共享 Workflow、SSE bridge、任务中心和响应式布局。
4. 执行验证、只读收尾审查、修复、iter-finish 和独立 commit。

## Risks And Questions

- 事务边界：分类器和外部调用必须在 SQLite 写事务之外；executor 只能在 commit 后唤醒。
- 双真相：所有普通文本写入集中通过统一 part codec，避免刷新 UI 与模型上下文不一致。
- 消息树兼容：Research 卡禁用重新生成，普通 assistant 消息保留原有 edit/reload/fork 行为。
- SSE 一致性：事件只作为失效信号；完整快照仍由 owner-only REST 获取，并按 `state_version` 防旧覆盖。
- 密钥安全：分类和 Chat 失败只保存稳定错误码/安全文案，不保存 provider body 或原始异常。

## Progress Notes

- 2026-07-16：复用三路只读开工审查。功能审查确认 schema v6、part codec 和共同事务边界是首要缺口；质量审查确认异常脱敏、幂等重放和 SSE 快照一致性风险；UI/UX 审查确认当前双侧栏若直接叠加 Workflow 会形成错误四栏。
- 2026-07-16：执行 `.venv/bin/python -m pip install -r backend/requirements.txt` 与 `npm ci`；`@assistant-ui/react@0.14.26`、core/store 依赖树恢复正常。
- 2026-07-16：依赖恢复后基线为 80 个后端测试、strict mypy 和前端 build 通过；工作区干净。
- 2026-07-16：完成 schema v6、受控 content part codec、分类前 owner/replay 预检、原子 Chat Research 创建、普通 Chat 异常脱敏和 standalone thread 约束。
- 2026-07-16：完成 assistant-ui 原生 Run data renderer、全局三栏、共享 Workflow/Decision/Controls、按 Run 去重 SSE bridge、任务中心 Peek、1024px Drawer 与 390px 全屏体验。
- 2026-07-16：三路只读收尾审查发现自动重放重复分类、Paper Chat 误接 Research、摘要覆盖步骤快照、移动 accordion/44px 等问题；均已修复并由审查代理定向复核关闭。

## Closeout

### Summary

- schema v6 支持 v2→v6 连续迁移，旧消息安全回填 text part，fresh/migrated `chat_messages` 结构一致，伪造缺列或错误约束 fail closed。
- `/api/chat/route` 支持 auto/normal/deep_research；分类前统一校验 general thread owner 并恢复完整幂等重放，模糊分类使用单次、10 秒上限的真实模型调用。
- Chat Research 在单个短事务中写入用户消息、Run、三步、created event、assistant data card 与 thread head；executor 仅在 commit 后唤醒。
- 普通与论文 Chat 保留原 `/api/chat/runs` 契约；流式 content/parts 双轨同步，provider 异常只保存稳定错误码并返回安全文案。
- 前端完成全局侧栏/Chat/Workflow 三栏、平板 Drawer、390px 全屏 Workflow、composer 上方 mini bar、共享单选步骤、Decision、二次确认停止和任务中心 Peek。
- 每个当前可见 Run 通过共享 ref-counted EventSource 接收失效事件；按 Event ID 去重、150ms 合并刷新，并以 `state_version` 防止旧快照覆盖。

### Validation

- `.venv/bin/python -m pytest backend/tests`：92 passed。
- `.venv/bin/python -m mypy`：50 个源文件通过。
- `npm run build`：通过；主入口 428.37 kB、Chat 432.60 kB，均低于 Vite 500 kB 建议线。
- `npm run test:e2e`：4 passed、2 skipped；Research flagship 在 1440px、1024px、390px 全部通过，桌面普通 Chat 流式/重新生成/Fork 回归通过，另外两个 viewport 按设计跳过重复普通 Chat 用例。
- `git diff --check`：通过。
- 本轮未运行真实 arXiv 网络或付费模型 smoke。

### Review

- 正确性/事务：分类前 owner/replay 预检、事务内并发复检、fresh/migrated v6 一致性与 executor commit 后唤醒均通过复核，无剩余阻断项。
- 契约/安全：Paper Chat 保持全文流式路径；Run card/Task Peek 由去重 live/list bridge 推进；assistant-ui data part、异常脱敏和 owner-only 404 通过复核。
- UI/UX：新 Run 自动进入桌面第三栏，390px 单选 accordion、全屏尺寸、焦点返回、reduced-motion 基线和移动关键触点已修复；三步 Harness 始终明确不代表论文调研完成。

### Follow-ups

- waiting_input、Decision、慢步骤暂停边界与失败重试的浏览器错误注入仍需用测试依赖 fixture 扩展，不能增加生产 seed/debug API。
- Iter13 开始接入真实检索/论文数据链路；首次真实付费模型 smoke 前必须再次询问授权。
- Research SSE/Run 创建的用户级连接数与速率限制留待长任务公开前补齐。
