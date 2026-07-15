# Agent Handoff

最后更新：2026-07-15，iter07 closeout。

## Current Status

- 当前分支：`codex/general-chat-foundation`，基于已快进到 iter06 的 `codex/develop`。
- 前端主入口 `/` 已改为基于 assistant-ui 的通用 Chat；一级导航只保留 Chat、论文库和我的资料库。
- 仪表盘、知识图谱、学习管理和旧智能问答页面已删除；`/qa`、`/graph`、`/learning` 兼容重定向到 `/`。相关后端 Agent、图谱和学习数据能力没有删除。
- 通用线程使用 `chat_threads.paper_id IS NULL`，支持服务端创建、列表、消息树持久化和 SSE 流式回答。
- 通用 Chat 发给模型的内容仅包含通用 system prompt 与当前消息树分支的用户/助手历史；不注入论文、资料库、文件、联网搜索或 Agent 工具上下文。
- 单篇论文 Chat 与通用 Chat 共用 assistant-ui 运行时和消息组件；单篇论文仍注入完整解析正文。
- assistant-ui 界面现在明确展示“编辑并分叉”“重新生成一个分支”“分叉”和分支选择器；切换分支后会更新服务端 active head。
- append/edit/regenerate 请求契约由后端校验；regenerate 复用原用户消息，不再重复插入该消息。
- API Key 只从 `LLM_API_KEY` 环境变量读取；默认配置为 `https://api.deepseek.com` / `deepseek-v4-flash`。
- 数据库仍使用 schema version 2；论文唯一身份、AssetStore、Docling、Chunk/FTS5 与 QA Agent 能力保持 iter06 状态。

## Chat Flow

```text
assistant-ui current branch
    -> POST /api/chat/runs
    -> chat_messages parent tree + chat_runs
    -> rebuild selected lineage
    -> DeepSeek-compatible streaming API
    -> SSE deltas + persisted assistant message + active_leaf_id
```

通用 Chat 与单篇论文 Chat 的主要差别只在模型上下文：前者使用纯对话 system prompt，后者额外加入当前论文的完整解析正文。两者共用相同的消息树、流式响应和 Fork UI。

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-iter07-full -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy
npm run build
$env:RUN_REAL_LLM_TESTS="true"
.\.venv\Scripts\python.exe scripts\real_chat_smoke.py
git diff --check -- . ':!UIPrototype/**'
```

结果：59 个后端测试通过；mypy 通过；前端生产构建通过；本地浏览器验收覆盖自动建会话、精简导航、普通发送失败态和显式 Fork 入口；真实 `deepseek-v4-flash` Chat smoke 返回预期标记。Vite 仍提示主包约 909 kB，属于现有代码分割 follow-up。

## Known Risks

- 前端尚无自动化 Playwright 回归；本轮使用本地浏览器做了人工语义/交互验收。
- 通用会话目前只有创建、列表和切换，没有重命名、删除、归档和自动标题生成。
- assistant-ui LocalRuntime 与后端共同维护消息树；后续升级 assistant-ui 时应重点回归 message ID、parent ID、regenerate 和 active head。
- 通用 Chat 当前刻意不接入论文/资料库/联网/工具；下一阶段 Agent 上下文必须设计显式、可见、可撤销的授权边界。
- 前端主 bundle 仍超过 Vite 500 kB 建议阈值，后续可按路由和 assistant-ui 组件拆包。
- Docling 解析与远程 PDF 下载仍是同步长任务；大批量使用需要任务队列。
- deterministic embedding 只用于本地重排，真实检索质量仍需 gold set 评估。

## Next Candidates

1. 设计 Agent 原生会话内状态：显式 Context/Tool 状态、步骤/运行记录和可撤销授权，不默认读取论文或资料库。
2. 为通用线程补充重命名、删除/归档、自动标题和可扩展的线程列表 runtime。
3. 增加 Playwright smoke，覆盖通用聊天持久化、编辑分叉、重新生成、显式 Fork 和刷新后 head 恢复。
4. 对前端做路由级代码分割，降低 assistant-ui 首屏 bundle。
5. 建立真实论文 QA/retrieval gold set，并把现有后端 Agent 作为后续可选工具接回 Chat。

## Git Notes

- 本轮实现记录：`docs/iterations/iteration_iter07_general-chat-foundation.md`。
- 功能分支：`codex/general-chat-foundation`；基线分支：`codex/develop`。
- 本轮不 push；后续推送前先 fetch/rebase，保留远端用户改动。
