# Iterations

Agent 续写入口：

- [Agent Handoff](../AGENT_HANDOFF.md)：当前状态、验证命令、风险和下一轮候选。
- [AGENTS.md](../../AGENTS.md)：agent 进入仓库后的工作流规则。

| Iteration | Title | Status | Notes |
| --- | --- | --- | --- |
| [iter10](iteration_iter10_upload-visibility.md) | 用户上传归属与可见性 | Complete | schema v4、默认私有/显式公开上传、全读取链路访问控制；70 tests、strict mypy 和前端 build 通过。 |
| [iter09](iteration_iter09_session-user-isolation.md) | Session 登录与跨用户数据隔离 | Complete | 内存 SessionStore、Argon2 登录、CurrentUser、schema v3 migration 与跨用户隔离；67 tests、strict mypy 和前端 build 通过。 |
| [iter08](iteration_iter08_backend-layer-refactor.md) | 后端分层与迁移基础重构 | Complete | Router/Service/Repository/db 分层、兼容 facade 与 migration runner；61 tests、strict mypy 和前端 build 通过。 |
| [iter07](iteration_iter07_general-chat-foundation.md) | 通用持久化 Chat 基础 | Complete | 通用线程、真实模型多轮对话、assistant-ui 首页与显式 Fork；59 tests 与真实 DeepSeek smoke 通过。 |
| [iter06](iteration_iter06_pr-review-hardening.md) | PR 评审阻断问题修复 | Complete | 修复 SSRF、schema 重建门禁、严格来源身份、状态一致性和消息 ID 冲突；56 tests 与 100 并发 smoke 通过。 |
| [iter05](iteration_iter05_agent-storage-integration.md) | Agent 与新存储架构合并 | Complete | 以内容寻址 PDF/Docling 文档为唯一正文源，适配 Chunk、FTS5 与真实 Agent；47 tests 与 100 并发 smoke 通过。 |
| [iter04](iteration_iter04_agentic-cross-paper-qa.md) | Agent 驱动的跨论文知识库探索 | Complete | 只读论文库工具、多轮 tool calling、引用白名单、真实模型可观测性、可靠性修复与 gpt-5.5-medium 真实 smoke 已完成。 |
| [iter03](iteration_iter03_fts5-chunk-retrieval.md) | FTS5 Chunk 检索性能优化 | Complete | FTS5 trigram chunk prefilter、旧库 backfill、同步写入/fallback、scoped QA/search 和测试覆盖已完成。 |
| [iter02](iteration_iter02_traceable-fulltext-chunks.md) | 正文解析与可追溯 Chunk 知识链路 | Complete | 正文/metadata chunks、chunk-first 检索问答、chunks API、详情页片段展示和安全限制已完成。 |
| [iter01](iteration_iter01_core-reliability.md) | 可信知识链路与稳定性修复 | Complete | 核心契约、mock 策略、SQLite 并发可靠性、订阅入口与测试基线已完成。 |
