# Project Memory And Backlog

最后更新：2026-07-13，iter05 closeout。

本文档是 PaperMate 的长期 Memory/TODO 单一入口。iteration 文档只记录当轮范围；完成或新发现事项必须回写本文件，并在 `docs/AGENT_HANDOFF.md` 留下续写链接。

## Product Direction Memory

- 推荐定位：**Agentic Paper Reading Assistant** 或 **Mini Research Agent**。
- 核心差异：不是删除 RAG，而是把关键词、元数据、全文/FTS、未来向量检索作为 Agent 可调用工具，让模型自主决定何时搜索、搜索什么、打开哪条证据、是否继续追查。
- 当前不应直接称为完整 AutoResearch：尚不具备自主提出 Idea、判断 novelty、复现代码和评估研究结果。
- 完整 Agent 经验应覆盖 Tool Calling、Planning、Retrieval、Review、Reflection、Memory、Evaluation 和闭环；当前课程 MVP 需要诚实区分“已实现”与“规划中”。
- 人机分工目标：模型执行探索与草稿，人负责 Review；失败案例和偏好应进入 Memory，影响后续输出，但不得未经确认自动扩张权限。

## Completed

| Priority | Item | Source | Status | Acceptance | Target |
| --- | --- | --- | --- | --- | --- |
| P0 | Agent 驱动的跨论文问答 | 助教建议 / iter04 | Complete | 模型多轮调用 search/open 工具，引用只来自已打开证据，支持 mock 与真实模型 trace | iter04 |
| P0 | 真实模型可验证路径 | 质量审查 / iter04 | Complete | 真实执行可观测，不以静默 fallback 冒充成功；opt-in smoke 不泄密 | iter04 |
| P0 | 修复已复现可靠性 bug | 质量审查 / iter04 | Complete | stale concepts/edges、FTS 误关、空白/宽松输入均有回归测试 | iter04 |
| P0 | Agent 适配内容寻址论文存储 | iter05 | Complete | Chunk 绑定当前 PaperDocument hash，引用只来自已打开正文证据 | iter05 |
| P0 | 删除 mock/seed 双路径 | 用户决策 / iter05 | Complete | 无 mock LLM、无默认 seed、无 metadata 正文 fallback，无 key 明确失败 | iter05 |
| P1 | Agent 严格 wall-clock deadline | iter04 安全复核 / iter05 | Complete | 真实 provider 每次 timeout 被限制为 Agent 剩余预算 | iter05 |

## Next

| Priority | Item | Source | Status | Acceptance | Target |
| --- | --- | --- | --- | --- | --- |
| P1 | 用户 Review + Memory 闭环 | 助教建议 | Planned | 用户能评价/修订回答；记录偏好与失败案例；后续回答可审计地引用 memory | Future |
| P1 | 真实 arXiv QA/retrieval gold set | iter03 follow-up / 助教 Evaluation | Planned | 覆盖检索恢复、跨论文引用准确率、工具步数、延迟与成本 | Future |
| P1 | 结构化章节与附录导航 | iter02/03 follow-up | Planned | HTML/PDF 解析保留章节层级，可按 Method/Appendix 打开证据 | Future |
| P1 | 表格、图注、公式与 citation 对齐 | iter02/03 follow-up | Planned | 解析结果保留多模态/引用锚点并可追溯 | Future |
| P1 | 真实 embedding 或混合语义检索 | 质量审查 | Planned | 明确迁移、缓存、维度/成本策略；在 gold set 上证明增益 | Future |
| P2 | 前端 Playwright smoke | iter02/03 follow-up | Planned | 覆盖论文库、处理、chunk、Agent QA、学习管理 | Future |
| P2 | 定时 arXiv ingestion 与订阅推荐 | handoff 候选 | Planned | 订阅主题可驱动增量抓取、去重和推荐 | Future |
| P2 | 并发写路径与任务队列 | 质量审查 | Planned | process/ingest/note/favorite 并发 smoke；长任务不阻塞请求 | Future |
| P2 | Provider read-side 瞬态错误与重试矩阵 | iter04 最终复核 | Planned | 清洗/重试 IncompleteRead、连接重置，覆盖耗尽、401、5xx、Retry-After 与 backoff | Future |

## Out Of Scope Until Reconsidered

- 旧 `arxiv_id/file_path` 数据库的兼容迁移；当前无真实数据，本轮按用户决策直接采用新 schema。

- 自主提出研究 Idea。
- 自主判断 Idea novelty。
- 自动下载并复现论文代码。
- 自动运行实验并判断研究结果是否成立。

这些能力可以作为长期研究方向，但在真实验收和安全边界建立前，不写入当前产品能力声明。
