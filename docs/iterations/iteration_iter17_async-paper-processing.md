# Iter17：去 Agent 化与异步论文加工基建

## Context

Iter16 已完成研究质量评测与验收证据，但当前固定研究流程将多个单次模型调用或确定性服务命名为 Agent，责任边界不清。同时，arXiv/USENIX/SIGOPS 手动导入只写入论文元数据，PDF 下载与 Docling 解析仍由详情页或 DeepResearch 同步触发；单篇 PDF 卡死可阻塞整条长任务。

本轮先完成后续 Chat/DeepResearch 融合所需的基建：用户仍手动选择和导入论文，论文落库后由系统自动、异步、可恢复地完成 PDF 下载、解析、分块与索引。库内搜索工具收口、文件夹范围语义和唯一 Chat Agent 改造明确留到下一轮。

开工基线：`main` @ `5026606`；工作树存在用户所有的 `package-lock.json` 改动，本轮不覆盖、不纳入提交。

## Goals

- 将固定工作流中的伪 Agent 重命名为模型生成器、校验服务、检索服务或工作流组件，保留下一轮要并入 Chat 的工具型 QA Agent。
- 将论文“发现/选择/入库”与“PDF 下载/Docling 解析/分块索引”解耦。
- 建立 SQLite 持久化论文加工任务、租约、心跳、有界重试、失败隔离和进程级硬超时。
- arXiv/USENIX/SIGOPS 导入及 PDF 上传成功后自动排队，HTTP 请求不等待 Docling。

## Scope

- schema v10 论文加工任务表与 v9→v10 迁移。
- 任务 Repository/Service/Executor，FastAPI lifespan 启停与导入后唤醒。
- 导入、上传、论文列表/详情状态和必要的前端提示。
- 固定研究流程和论文加工中的组件重命名；保留旧 `research_steps.agent_name` API/DB 字段作为兼容执行标签，但新值与 UI 不再将每步称为 Agent。
- 后端单元/集成测试、strict mypy、前端 build 和必要的并发/恢复 smoke。

## Non-goals

- 不将 DeepResearch 改写为 ReAct，不改其 17 步键、Artifact 或 Citation 契约。
- 不将库内搜索接入普通 Chat，不新增文件夹范围语义。
- 不重写 `qa_agent.py` 及其 `classic/agentic` 兼容 API；该部分与唯一 Chat Agent 在下一轮合并。
- 不引入 Kafka/Redis 外部服务，不调用真实 arXiv、Docling 或付费模型做验收。

## Acceptance Criteria

- 用户手动导入返回新增/重复/已排队计数，不在 HTTP 请求内下载或解析 PDF。
- 同一论文重复导入不会创建重复活跃任务；已有当前完整文档时直接复用。
- Docling 由独立子进程执行；超时可终止，并按固定上限退避重试。
- 一篇论文下载或解析失败只标记该论文任务，不阻塞队列中其他论文。
- 工作进程丢失租约后不得提交文档或任务成功；过期租约可恢复，尝试次数不越界。
- 新建工作流步骤的执行标签不含“Agent”，技术详情显示“执行组件”。
- schema fresh、v9→v10、失败回滚、外键/索引校验、后端测试、strict mypy、前端 build 和 `git diff --check` 全部通过。

## Plan

1. 完成命名、导入链路、SQLite 并发与安全的只读开工审查。
2. 实现 schema v10 任务表、幂等入队、租约领取/心跳/结算/恢复。
3. 实现可终止工作进程与 FastAPI 生命周期，将导入/上传路由改为自动排队。
4. 将固定流程中的伪 Agent 类、成员和新建步骤标签改为职责型组件。
5. 同步 API/前端类型与状态提示，增加队列、重试、超时、失败隔离和迁移测试。
6. 运行全量验证、只读收尾审查，修复后完成 iter-finish 和提交。

## Risks And Questions

- Docling 无法在 Python 线程中安全中止；必须由独立进程承载，父执行器负责硬超时和租约心跳。
- SQLite 只适合当前单机部署；任务仓储契约需与执行器分离，以便后续替换 Redis/专用队列。
- 论文元数据全局共享、用户上传可见性隔离；任务请求者必须持久化并在执行前重验访问权。
- 现有 `processing_status` 同时承担旧 Wiki 生成和文档就绪语义；本轮以当前 `paper_documents` 为正文真相，避免自动触发付费 LLM 摘要。
- 现有 `package-lock.json` 改动与本轮无关，验证和提交必须保留且排除。

## Progress Notes

- 2026-07-21：完成 AGENTS、handoff、迭代索引、Iter16、README、后端架构与 git 状态 grounding；按 `iter-start` Skill 建立本记录。
- 2026-07-21：三路只读开工审查启动：功能/导入链路、并发/安全风险、命名与兼容边界。
- 2026-07-21：完成 schema v10 与持久化论文加工任务；导入/上传在同一事务中幂等入队，FastAPI 生命周期启动单槽监督器。
- 2026-07-21：Docling 移至可终止子进程，父进程负责租约心跳、硬超时和有界重试；PDF 在完整性校验后才发布到共享内容寻址存储。
- 2026-07-21：论文列表/详情增加加工状态和主动轮询，PDF GET 改为只读缓存；固定流程类和新建步骤执行标签完成职责型重命名，保留 `agent_name` 兼容字段与 `qa_agent.py`。
- 2026-07-21：主验证阶段达到 158 tests、strict mypy 和前端生产 build 通过；三路只读收尾审查与修复复核完成。

## Closeout

### Summary

- 固定流程不再把每次模型调用或确定性步骤包装成 Agent：类名、成员名和新建步骤执行标签已改为规划、生成、检索、抽取、校验等职责；`research_steps.agent_name` 仅作为兼容字段保留，界面改称“执行组件”。真正多轮工具调用的 `qa_agent.py` 留待下一轮与 Chat 合并。
- schema 升至 v10，新增每篇论文唯一的持久化加工任务，包含阶段、请求用户、尝试上限、退避时间、租约、心跳、generation fencing 与安全错误摘要。重复导入幂等复用任务，活跃用户可接管尚未运行的旧请求。
- arXiv/USENIX/SIGOPS 来源抓取仍由用户手动触发；元数据导入和上传 PDF 会在同一事务中自动入队。上传请求只做限量内容寻址保存，不再在 HTTP worker 中解析不可信 PDF。
- 内嵌监督器异步完成远程 PDF 下载、Docling 解析、Chunk 和 FTS。远程下载有 60 秒总时限、单次 socket timeout、租约心跳和完整性校验；Docling 在可终止子进程中运行；关键写入重验租约、用户状态、论文访问权与 source hash。
- 列表/详情暴露独立 `preparation` 状态并在活动阶段轮询；PDF GET 只服务已缓存文件，解析入口仅排队/重试，不再同步运行 Docling，也不暴露内部任务行。

### Validation

- `\.venv\Scripts\python.exe -m pytest backend\tests -q`：158 passed。
- `\.venv\Scripts\python.exe -m mypy`：strict，61 source files，无问题。
- `npm run build`：TypeScript 与 Vite 生产构建通过，2584 modules transformed。
- `git diff --check`：通过；仅有工作区换行提示，无 whitespace error。
- 新增定向覆盖：fresh/v9→v10/伪造 v10 fail closed、幂等入队、requester 接管、租约 generation fencing、重试上限、失败隔离、下载总超时、权限撤回、Docling 硬超时及超时后继续下一任务。

### Review

- 并发/正确性审查最初发现慢速下载可无限占槽、索引前计算位于长写事务、停用首位请求用户会卡住队列；已增加总时限/下载心跳、事务外 embedding 与最终写前延长租约、queued requester 安全接管。复核无阻断项。
- 安全审查最初发现上传请求线程解析不可信 PDF、排队 API 泄露完整任务行、执行中撤权未在关键写入重验；均已修复，并将解析结果放入独占临时目录、限制 128 MB 且写盘前检查。复核无阻断项。
- 前端审查发现 ready 状态“重新加工”为空操作、后台完成后 Chunk 空缓存不刷新；已隐藏无 force 语义的按钮，并在 preparation ready 时启用 Chunk 查询。复核无阻断项。

### Follow-ups

- 本轮只完成论文库入库后的异步加工基建。topic DeepResearch 动态发现论文时仍通过旧 `research_tools.py` 同步等待全文；因此不能宣称用户最初遇到的 17 步中途卡死已经完全解决。下一轮应让研究流程复用持久化加工任务，并支持等待、跳过非关键失败或稍后续跑。
- 下一轮按用户已确认的范围一起处理：库内搜索工具收口、文件夹范围语义、DeepResearch 作为 Chat 能力接入，以及唯一工具型 Agent/现有 `qa_agent.py` 的兼容迁移。
- SQLite 单机单槽适合当前课程项目；多实例部署前仍需把执行器抽为独立服务/专用队列，并补用户级资源配额。极端超大正文的预计算只有写前 300 秒租约保护，后续可增加循环级心跳。
