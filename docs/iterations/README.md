# Iterations

Agent 续写入口：

- [Agent Handoff](../AGENT_HANDOFF.md)：当前状态、验证命令、风险和下一轮候选。
- [AGENTS.md](../../AGENTS.md)：agent 进入仓库后的工作流规则。

| Iteration | Title | Status | Notes |
| --- | --- | --- | --- |
| [iter15](iteration_iter15_research-landscape-projects.md) | 可追溯研究脉络、主题簇与项目化资料库 | Complete | schema v9、owner-only 研究项目、项目级版本 Artifact/DAG、七步 Project workflow、主题簇/时间线/图谱、资料库 UI 与 Workflow 降噪；120 tests、mypy、build、9 项 Playwright 通过。 |
| [iter14](iteration_iter14_cited-research-synthesis.md) | 可追溯调研综合与研究报告 | Complete | schema v8、durable Evidence/Citation/model ledger、17 步综合、严格引用验证、版本化报告与响应式引用交互；112 tests、mypy、build、6 项 Playwright 和真实 arXiv/PDF/Docling/模型 smoke 通过。 |
| [iter13](iteration_iter13_topic-research-pipeline.md) | 主题调研数据链路 | Complete | schema v7、版本化 Artifact/Run Paper、Tool Registry、五 Agent、十步 topic workflow、预算 Decision 与真实数据 UI；102 tests、mypy、build、6 项 Playwright 和真实 arXiv smoke 通过。 |
| [iter12](iteration_iter12_chat-run-workflow.md) | Chat 接入 Research Run 与 Workflow UI | Complete | schema v6、原子 Chat 路由、assistant-ui Run data part、实时 Workflow；92 tests、strict mypy、build 和三视口 Playwright 通过。 |
| [iter11](iteration_iter11_research-run-harness.md) | Research Run 与可恢复 Harness | Complete | schema v5、fenced lease 单 worker、SSE 续传、Decision、任务中心与 Run 页；80 tests、strict mypy、build 和 2 Playwright 通过。 |
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
