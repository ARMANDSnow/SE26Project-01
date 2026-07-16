# Iter15：可追溯研究脉络、主题簇与项目化资料库

## Context

Iter14 已提供可追溯 Research Report、durable Evidence/Citation Registry、严格引用验证与版本化 Artifact。Iter15 在不改变三步 standalone Harness 和十七步 topic Run 语义的前提下，增加 owner-only 研究项目、项目级分析工作流，以及主题簇、时间线和关系图。

开工基线：`codex/agentic-research-refactor` @ `7f50dd7`，schema v8；112 个后端测试、strict mypy、前端 build 通过。Playwright 基线因本机既有 Iter14 服务占用 8000 端口而待使用隔离端口复跑，既有服务不得停止。

## Goals

- 在“我的资料库”中创建、维护、归档和恢复研究项目，并加入当前 Session 可访问的 Run、论文和固定 Report version。
- 以项目级追加版本 Artifact 生成 ResearchLandscapePlan、TopicCluster、ResearchTimeline、ResearchGraph 和 ProjectAnalysisValidation。
- 所有事实性 Cluster、Timeline Event 和语义 Graph Edge 均追溯到当前有效 Citation、PaperBrief Evidence 或经验证的论文元数据。
- 项目输入、Artifact 版本、Citation/Evidence、ACL 或 source hash 改变时，动态投影 stale/inaccessible，保留安全历史审计。
- 在 Run、论文、报告、项目和图谱之间提供双向链接，并简化现有 17 步和报告 UI。

## Scope And Acceptance Criteria

- schema v9 支持 fresh、v8→v9、v2→v9 连续迁移和 fail-closed 兼容门。
- 项目 owner-only；非 owner 统一 404；归档只读；删除项目不删除源研究数据。
- 项目 item 使用严格 one-of 约束和逻辑唯一性；Report 固定 Artifact version，不静默漂移。
- 项目分析使用独立 `project` Run mode 和七个 `project.*` step，复用 lease、heartbeat、Decision、SSE、幂等键、预算和 durable model operation。
- current 项目 Artifact 必须完整重验依赖 DAG；旧 completed 不得在最新版本失效时回退为 current。
- 前端仅保留 Chat、论文库、我的资料库三个顶级入口；项目图谱在 390px 提供等价列表操作。
- topic 的十七个后端步骤聚合为七个用户阶段；Harness 继续清晰显示真实三步。

## Plan

1. 迁移 schema v9，新增项目、项目成员、Artifact dependency 和项目 Citation reference，并扩展 Run/Artifact 版本作用域。
2. 增加严格项目分析契约、项目仓储/API、七步 Project pipeline 和确定性图谱/引用验证。
3. 增加项目资料库 UI、加入项目与反向链接、Cluster/Timeline/Graph、版本和 Decision 体验。
4. 收敛现有 Workflow/Report/术语/模式选择器 UI，并覆盖响应式与无障碍。
5. 补齐迁移、ACL、DAG、lease、预算、契约、API 和 Playwright 回归，执行四路只读收尾审查。

## Risks And Questions

- `research_runs` 和 `research_artifacts` 均需扩展 CHECK/版本作用域，迁移必须保持现有外键和 v8 数据完整。
- 跨 Run 的 `C1` 和 `claim-1` 会碰撞；项目分析必须使用服务器生成的 scoped reference。
- 现有 checkpoint 与 latest Artifact fallback 不足以证明项目 DAG current；项目写入和 replay 需要专用 fenced 校验。
- inaccessible tombstone 不得复用会泄漏 Citation key、论文标题或 heading 的旧投影。
- 当前没有可信 bibliography 数据，因此 Iter15 不根据标题相似度生成 `cites` 或思想影响关系。
- 首次新的真实付费模型调用前必须单独取得用户授权。

## Non-goals

- Citation entailment 自由改写或语义评分模型。
- 报告导出、公开分享、多人协作、RBAC、Redis 或分布式任务队列。
- v0 旧 116 篇论文迁移、独立 Workflow 顶级导航、生产 seed/mock/debug API。

## Protected User Files

- 不修改、删除、暂存或提交 `test-results 2/`、任何带“ 2”后缀的同步副本、`UIPrototype/第1组_*` 或其他用户文件。
- 不读取、打印、提交或记录桌面 Key 文件；API Key 仅从环境变量读取。
- 不无故修改依赖锁文件，不使用 `git add -A`。

## Progress Notes

- 2026-07-16：完成仓库 Grounding、三路开工只读审查、pytest/mypy/build 基线；开始 schema、后端和前端并行实现。
- 2026-07-16：完成 schema v9、项目仓储/API/七步工作流、项目 Artifact DAG、资料库项目视图、报告与 Workflow 降噪。
- 2026-07-16：四路收尾只读审查后修复项目 revision/lease fencing、写入事务内依赖复验、最新版本 stale 传播、项目 DAG 删除边界、Citation tombstone、历史报告事实隐藏、Timeline 自由文本和图谱白名单等问题。
- 2026-07-16：用户另行授权桌面凭据的真实付费验证；凭据仅在隔离后端进程中读取，未打印或写入仓库。真实 `gpt-5.5-medium` 项目分析暴露并修复 Run 派生论文 metadata dependency hash、手动 retry operation identity、Cluster/Timeline prompt 约束、报告反向链接及真实大数据量下的 UI 降噪问题。

## Closeout

### Summary

- schema 从 v8 连续升级至 v9，新增 owner-only `research_projects` / `research_project_items`、`mode='project'` Run、项目 Artifact 版本作用域、规范化 dependency ledger 和项目 Citation reference。fresh v9、v8→v9、v2→v9 结构一致，伪造 v9 缺索引会 fail closed。
- 新增严格 `ResearchLandscapePlan`、`TopicClusters`、`ResearchTimeline`、`ResearchGraph`、`ProjectAnalysisValidation` 契约和七步 `project.*` 工作流。三个结构化 Agent 各最多一次 provider 请求，图谱构造/验证为确定性服务；Harness 三步和 topic 十七步语义未改。
- 项目可加入当前可访问 Run、论文和固定 Report version，支持排序、归档/恢复、Coverage Decision、分析控制、版本切换和反向链接。项目变更会在同一事务内 fence 活跃分析；旧 lease 无法写 Artifact/Citation/current 状态。
- Artifact current 始终取项目类型的最高版本并递归复验依赖；新上游版本、item 变化、Citation/Evidence/ACL/source hash 变化均使旧下游 stale/inaccessible，不回退旧 completed。失效事实正文和 Citation key 不再通过历史报告或 tombstone 泄漏。
- “我的资料库”新增论文/研究项目/报告二级视图；项目页提供 Coverage、主题簇、时间线、关系图、版本、Decision 和 Evidence Inspector。topic 的 17 个后端 step 聚合为 7 个用户阶段，完整报告改为独立分节页，`C1` 等技术标识默认不暴露。Chat 模式选择器改为 44px、`rounded-xl` 的 Radix Select。
- 图谱使用 SVG 边 + HTML button 节点，390px 使用可操作列表和节点详情；语义边键盘可打开 Citation→Evidence，关闭后恢复焦点。停止分析和删除项目均有确认边界。

### Validation

- `.venv/bin/python -m pytest backend/tests`：**122 passed**。
- `.venv/bin/python -m mypy`：**Success，57 个源文件**。
- `npm run build`：通过。
- 隔离端口 `18216/15276` 与 `/tmp` DB/upload 执行 `npm run test:e2e`：**9 passed、6 skipped**；1440px、1024px、390px 均通过项目旗舰路径、topic 17→7 展示、完整报告、Citation→Evidence、键盘/焦点、reduced-motion、无横向溢出与 44px 触点。
- `git diff --check`：通过。
- 真实服务 smoke 使用隔离数据库副本、隔离上传目录和 `gpt-5.5-medium`；兼容 base URL 在进程内补为 `/v1`，`LLM_JSON_RESPONSE_FORMAT=false`。成功项目 Run 以 **3 次预算预占对应 3 次 provider 请求**完成 7/7 步并生成五类 Artifact；另完成一次普通 Chat 和一次约 22k token 全文输入的 Paper Chat。未重复执行 arXiv/PDF/Docling 网络获取，复用 Iter14 已验证的真实双论文数据。
- 首次诊断 Run 保留为失败审计记录：一次手动 retry 在修复前重复了 Planner 调用，随后 Cluster 输出因 claim/Citation 配对不合法被严格拒绝；没有把无效模型关系写成数据库真相。新 Run 在修复后一次性完成 Planner、Cluster、Timeline 各一次调用。
- 完整性查询确认：3 个 Cluster 摘要、6 条区分特征、1 条语义 Timeline Event、22 条语义 Graph Edge 均有有效 Citation；30 条 publication Event 和 33 条确定性 Graph Edge 不伪造语义引用；49 节点、55 边全部 valid，stale/inaccessible dependency、外键违规和重复 model identity 均为 0。

### Review

- 开工三路审查覆盖 v8 数据模型/Artifact DAG，ACL/Citation/Evidence/source hash/事务/lease/预算，以及项目 UI/响应式/无障碍。
- 收尾四路只读审查覆盖正确性与幂等、API/Schema/DAG/测试、ACL/泄漏/SSRF/缓存、UI/响应式/无障碍。审查未发现新 SSRF、API Key、Authorization、provider body 或绝对路径泄漏。
- 根据审查修复：项目修改前置 fencing、Artifact 写事务内逐依赖校验、项目 DAG 显式删除、model outcome+预算结算原子性、Run+Report 去重/派生节点、Timeline publication 服务端归一化与 Period Citation 强制、Evidence 精确 locator、图谱独立白名单、Citation tombstone、owner-only GET no-store、移动图谱等价操作、正向链接与破坏性确认。
- 真实验证进一步修复：Run-derived paper dependency 使用 canonical metadata hash；manual retry 去除随机 suffix 后再计算 durable operation identity；Cluster/Timeline prompt 明示同事件/同 Cluster claim-Citation 配对；报告加入固定版本项目反向链接；Topic feature 类型与 React key 对齐；时间线和图谱默认聚焦重点、完整审计显式展开；Chat 模式辅助文案跟随选择变化。

### Follow-ups

- Iter16 候选：建立 Cluster/Timeline/Graph Citation entailment 与 coverage gold set；增加 ambiguous provider operation 人工 Decision；扩展项目编辑的批量筛选/搜索与更大图谱可用性测试，并覆盖真实 provider 首次严格输出失败后的受控新版本体验。
- 多实例 Session、分布式任务队列、多人项目和报告分享仍为非目标。
