# Iterations

Agent 续写入口：

- [Agent Handoff](../AGENT_HANDOFF.md)：当前状态、验证命令、风险和下一轮候选。
- [AGENTS.md](../../AGENTS.md)：agent 进入仓库后的工作流规则。

| Iteration | Title | Status | Notes |
| --- | --- | --- | --- |
| [iter05](iteration_iter05_agent-storage-integration.md) | Agent 与新存储架构合并 | Complete | 以内容寻址 PDF/Docling 文档为唯一正文源，适配 Chunk、FTS5 与真实 Agent；47 tests 与 100 并发 smoke 通过。 |
| [iter04](iteration_iter04_agentic-cross-paper-qa.md) | Agent 驱动的跨论文知识库探索 | Complete | 只读论文库工具、多轮 tool calling、引用白名单、真实模型可观测性、可靠性修复与 gpt-5.5-medium 真实 smoke 已完成。 |
| [iter03](iteration_iter03_fts5-chunk-retrieval.md) | FTS5 Chunk 检索性能优化 | Complete | FTS5 trigram chunk prefilter、旧库 backfill、同步写入/fallback、scoped QA/search 和测试覆盖已完成。 |
| [iter02](iteration_iter02_traceable-fulltext-chunks.md) | 正文解析与可追溯 Chunk 知识链路 | Complete | 正文/metadata chunks、chunk-first 检索问答、chunks API、详情页片段展示和安全限制已完成。 |
| [iter01](iteration_iter01_core-reliability.md) | 可信知识链路与稳定性修复 | Complete | 核心契约、mock 策略、SQLite 并发可靠性、订阅入口与测试基线已完成。 |
