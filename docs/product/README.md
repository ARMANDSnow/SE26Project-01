# PaperWiki 产品规划

本目录记录 PaperWiki 从“论文功能集合”重构为“Agent 驱动的科研论文工作台”的产品方案。路线图中 Iter11–15 已实现；当前后续重点是 Citation entailment/coverage 评测、ambiguous-call 人工恢复和可取消进程 worker。

## 已确认的产品决策

- `Chat`、`论文库`、`我的资料库`保持三个并列主入口。
- Chat 从普通对话升级为 Agent 指挥中心，但不会吞并论文库和资料库。
- 核心特色是“帮我调研 XX 相关论文”的可视化完整 Workflow。
- Agent 默认自动执行检索、抓取、解析、阅读、抽取、综合与私有沉淀；只有关键歧义、高成本、公开发布或破坏性动作才请求用户确认。
- 界面参考 Claude Code Agent View 的状态分组、摘要行、Peek 详情和“需要输入时再介入”思路，转译为适合 Web 论文研究的执行画布。
- 项目可以稳定联网并使用真实 API Key，因此目标链路按真实模型设计，不保留 mock 产品路径。

## 文档入口

1. [Agentic Research PRD](agentic_research_prd.md)：产品定位、用户任务、课程要求覆盖、功能范围、成功指标和验收标准。
2. [Workflow UX/UI 规格](workflow_ux_ui_spec.md)：信息架构、页面布局、按钮与跳转、状态、响应式和视觉规范。
3. [重构路线图](refactor_roadmap.md)：Harness 架构、数据模型、接口方向、迭代拆分、验证和答辩演示脚本。
4. [高保真 Workflow 原型](../../UIPrototype/AgenticResearchWorkflow/README.md)：可直接打开的 Chat + Workflow 模拟网页及交互说明。

## 术语

- **Research Run / 调研任务**：一次可暂停、恢复、追踪和复查的 Agent 工作流执行。
- **Workflow**：调研任务中有顺序、有状态、有输入输出的步骤集合。
- **Harness**：约束 Agent 如何规划、调用工具、保存状态、重试、等待用户和恢复执行的工程框架。它不是模型本身，而是模型外面的“任务执行系统”。
- **Artifact / 产物**：任务产生的论文集合、阅读卡片、对比矩阵、引用证据、研究脉络图或调研报告。
- **Checkpoint / 检查点**：任务运行中的可恢复状态，用于失败重试、暂停继续和避免重复抓取/解析。
- **Evidence / 证据**：来自具体论文正文位置、可被用户打开核验的引用片段。

## 当前实现与目标实现的边界

仓库当前已具备 Chat Research 路由、持久化 Research Run/Step/Event/Decision/Artifact、17 步 topic workflow、durable Evidence/Citation、跨论文对比与严格验证的版本化研究报告。“我的资料库”已支持 owner-only 研究项目、固定 Run/论文/报告范围、主题簇、时间线、可追溯关系图、Artifact 版本与 stale/inaccessible 投影。当前主要缺口转为：项目分析真实付费 smoke、Citation entailment 评测、可取消跨进程 worker 与多实例 Session/配额。

后续迭代必须在界面和文档中持续区分“已实现”“本轮实现”“规划中”，避免把路线图能力包装成当前能力。

## 参考原则

- Claude Code 官方 Agent View 将后台任务按 `Needs input`、`Working`、`Completed` 等状态组织，并允许从摘要行进入 Peek 或完整会话；PaperWiki 采用相同的信息压缩思路，但使用论文研究步骤、证据和报告作为核心内容：<https://code.claude.com/docs/en/agent-view>
- Claude Code 官方 CLI 将权限模式、工具白名单、最大轮数和结构化输出作为 Agent 执行边界；PaperWiki 对应为默认自动执行、关键动作确认、预算和结构化步骤输出：<https://code.claude.com/docs/en/cli-usage>
- Claude Code Checkpointing 展示了“自动保存、恢复和回退”的会话级安全网；PaperWiki 的 checkpoint 用于恢复调研任务，而不是复制其代码回滚实现：<https://code.claude.com/docs/en/checkpointing>
- MCP 将 AI 应用连接外部数据源、工具和工作流标准化；首版不强制引入 MCP，但 Tool Registry 应保留未来适配层：<https://modelcontextprotocol.io/docs/getting-started/intro>
