# Iteration iter06 - PR 评审阻断问题修复

## Context

PR #6 的评审指出五项问题：SIGOPS/PDF 下载存在 SSRF 风险；旧数据库会在新索引创建阶段以 SQL 错误启动失败；标题哈希会把不同来源论文混写；客户端可复用消息 ID 覆盖历史回答；元数据重复同步会把已处理论文重置为 pending。

用户确认本轮不迁移旧数据库数据，论文身份只使用 `(source, source_id)`，标题不参与去重或提示；`chat_threads.paper_id` 允许为空，为后续全库对话保留结构空间，但本轮不实现全库聊天入口。

## Goals

- 所有可控 URL 在首次请求和每次重定向前执行 HTTPS、域名和端口校验。
- 为当前 schema 增加显式版本门禁和可操作的全量重建流程，不做旧数据迁移。
- 论文严格按 `(source, source_id)` 独立保存，元数据刷新保持处理状态。
- PDF asset 变化时事务性失效派生数据，并将论文置为 pending。
- 消息 ID 冲突必须失败且不产生 run，不允许历史回答被覆盖。
- `chat_threads.paper_id` 可空，同时保持当前单篇论文聊天行为不变。

## Scope

- 后端数据库 schema、重建脚本、论文 upsert/asset 失效逻辑。
- SIGOPS proceedings 获取与远程 PDF 下载。
- 对话消息/run 约束和流式更新定位。
- 对应后端回归测试、前端类型、README 与交接文档。

## Acceptance Criteria

- 非白名单 proceedings URL、危险端口和跨域重定向不会发出目标请求。
- 旧 schema 得到包含重建命令的明确错误，而不是 `no such column`。
- 同标题不同 source/source_id 产生独立记录，且来源元数据不混写。
- 重复同步保留 processed 状态和现有文档/chunks。
- asset 变化会清理派生数据并将状态设为 pending。
- 重复 user/assistant message ID 不会创建新 run 或修改旧消息。
- 新 schema 中 `chat_threads.paper_id` 可空，单篇线程删除仍随论文级联删除。
- 后端测试、mypy、前端 build 与 diff check 通过。

## Plan

1. 增加安全 URL 校验与受控重定向打开器，并接入 SIGOPS/PDF。
2. 增加 schema 版本门禁和显式数据库重建脚本。
3. 收紧论文身份、状态保持和 asset 失效事务。
4. 收紧消息/run 唯一性与流式更新范围，调整 nullable paper 类型。
5. 补充回归测试并完成验证、closeout、handoff 与提交。

## Risks And Questions

- 本轮 schema 变更是破坏性的；已有数据库必须显式重建，且不保留数据。
- `paper_id = NULL` 只定义为未来全库范围，不在本轮开放创建或运行入口。
- 官方站点若将 PDF 重定向到新的 CDN，需要显式评审并加入白名单，不能自动放宽。

## Progress Notes

- 2026-07-14：通过 GitHub 连接器确认五项反馈均位于 PR 顶层评论，没有 inline review thread。
- 2026-07-14：完成本地根因审查并确认修复范围。
- 2026-07-14：接入逐跳 HTTPS/官方域名校验，禁止危险端口、URL userinfo 和跨白名单重定向。
- 2026-07-14：完成 schema version 2 门禁、破坏性重建脚本、严格来源身份和状态/asset 一致性修复。
- 2026-07-14：完成消息/run 唯一性、事务回滚、流式写入范围约束和 nullable `paper_id`。

## Closeout

### Summary

- SIGOPS proceedings 和远程 PDF 使用统一安全打开器；首次请求与每次重定向都必须是白名单官方域名的 HTTPS 443 URL。
- 新 schema 移除 `title_hash`，唯一身份只由 `(source, source_id)` 决定；旧 schema 不迁移，启动时给出 `reset_database.py` 重建命令。
- 元数据刷新不再覆盖 `processing_status`；asset 变化在 savepoint 内清理文档、chunks、summary、Wiki、概念，并设置 pending。
- 对话消息改为严格插入；消息 ID 冲突会整体回滚且不创建 run。每个 run 的 output message 唯一，流写入同时校验 run/thread/message。
- `chat_threads.paper_id` 可空；空范围线程明确返回“全库聊天尚未实现”，不会错误加载论文。当前论文详情页入口保持单篇模式。

### Validation

- `.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-iter06-final -p no:cacheprovider`：56 passed。
- 默认 mypy 与本轮 9 个显式模块 mypy：通过。
- `npm run build`：通过；仅保留已有 bundle size warning。
- `scripts/reset_database.py` dry-run、`--apply` 和 schema/papers 校验：version 2、0 papers。
- `scripts/performance_smoke.py --requests 100 --workers 100 --threshold 3.0`：0 failures，p95 `0.4684s`，max `0.4895s`。
- `git diff --check -- . ':!UIPrototype/**'`：通过；仅有 Git 的 LF/CRLF 工作区提示。
- 真实模型 smoke 未运行，本轮没有外部付费调用。

### Review

- 正确性：五项 PR 反馈都有独立回归测试；论文来源、处理状态、派生数据和对话 run 的关键不变量一致。
- 安全：受控 URL 在网络请求前校验；禁止跨域重定向；API key 与密钥文件无改动。
- 契约：nullable `paper_id` 已同步前端类型；本轮未新增全库聊天 API/UI。
- GitHub：PR #6 没有 inline review thread，反馈为顶层评论；本轮未自动回复或标记评论已解决。

### Follow-ups

- 若官方 PDF 改用新 CDN，需显式审查并扩充白名单。
- 后续全库持久聊天可复用现有消息树，在 `paper_id = NULL` 时接入跨论文 QA Agent；本轮只保留 schema 接缝。
- 旧数据库必须由用户确认后执行破坏性重建，不提供数据迁移。
