# 前端真实网页走查与 Bug 修复报告（2026-07-17）

## Context

本轮不创建 iter-start。目标是在隔离数据库与真实网页中覆盖 Chat、论文库、论文阅读、资料库、研究项目、Research Workflow、完整报告、Citation→Evidence、主题簇、时间线和关系图，并使用桌面凭据完成真实模型验证。修改前两次检查工作树，`/tmp/arxiv-pre-frontend-audit.patch` 与 `/tmp/arxiv-pre-fix.patch` 均为 0 字节，确认没有用户未提交差异需要保护。

## Scope

- 视口：1280×720、1024×768、390×844，并用项目既有 Playwright 套件覆盖 1440、1024、390。
- 数据：先使用 fresh schema v9 验证注册、普通 Chat、项目创建/归档/恢复和空状态；再复制 iter15 真实模型隔离数据库，覆盖 79 篇论文、成功 17 步 topic Run、完整报告、4 条有效 Citation、成功 7 步 project Run 和 49 节点/55 边关系图。
- 真模型：桌面 RTF 凭据只注入隔离后端进程，未打印、写入仓库或提交。普通 Chat 与 7,406-token 全文 Paper Chat 均从网页成功返回真实回答。

## Findings And Fixes

1. SQLite UTC 时间没有时区后缀，项目卡会把刚创建的记录显示成“昨天”。新增统一 UTC 解析与本地时间格式化，覆盖项目卡、项目版本、收藏时间和概要时间。
2. Research pipeline 已生成完整文档时，论文详情仍根据旧 `processing_status=pending` 显示“待处理”。详情页现在以当前文档完成状态为准显示“已解析”。
3. Select 组件的 `data-size` 高度覆盖页面声明，手机筛选下拉实际只有 32px。默认与紧凑 Select 触点统一为 44px。
4. 时间线预览把后追加的 7 月 9–10 日语义事件排在 7 月 14–15 日之后，并直接显示 `publication` / `improvement`。现在按事件日期倒序显示，并使用中文类型标签。
5. 主题簇与时间线把数据库论文 ID 当作主要按钮文本，未分类区一次铺出 28 个 ID。现在使用“查看论文”序号与数量摘要，内部 ID 只保留在路由中。
6. Workflow 的“全部 30”一次渲染所有候选卡片，右侧窄面板过长。现在默认显示前 8 篇，可显式展开剩余条目，切换筛选时恢复精简状态。
7. 真实项目的历史 Timeline Artifact 含英文叙述，与中文项目界面不一致。历史 Artifact 保持不可变；Timeline Agent 新增“用户可见叙述使用简体中文”的生成约束，保留论文标题、专名、指标和必要技术术语。

## Web Validation

- 注册、登录、登出入口可用；新建研究与模式选择可用。
- 普通 Chat 真实模型调用成功；消息编辑入口、复制/分叉/重新生成入口可达。
- 论文库筛选、来源切换、上传入口、收藏筛选和空状态可达；一次 arXiv 实时同步收到上游 502，页面恢复可操作，没有控制台错误。
- 项目创建、编辑、归档、恢复、Coverage、资料范围、版本、主题簇、时间线、关系图和移动端等价列表可用。
- 成功 topic Run 显示 17/17 后端步骤并聚合为 7/7 阶段；数据集、阅读卡、综合报告和固定报告版本可达。
- 完整报告的报告/对比/主张/引用导航可达；Citation 弹窗展示当前校验状态、原文摘录和论文定位链接。
- 论文详情在真实全文下完成 Paper Chat；修复后状态显示“已解析 · 全文 7,406 tokens”。
- 修复后手机端上传可见性、分类和来源下拉均实测 44px；页面无横向溢出。

## Automated Validation

- `.venv/bin/python -m pytest backend/tests`：122 passed。
- `.venv/bin/python -m mypy`：Success，57 个源文件。
- `npm run build`：通过。
- 隔离端口执行 `npm run test:e2e`：9 passed，6 skipped；desktop-1440、tablet-1024、mobile-390 均通过适用用例。
- `git diff --check`：通过。

## Residual Risks

- 一次 fresh 数据库的 arXiv 同步收到上游 502；这是外部同步链路的可用性风险，未用伪数据掩盖。页面能恢复按钮状态并继续操作，但后续可考虑加入更明确的短时上游故障提示和重试建议。
- 已落库的历史 Timeline Artifact 可能继续保留英文原文；本轮遵守版本不可变设计，只约束后续新版本使用中文。
- 关系图在大数据量下仍是信息密集型工具；当前默认聚焦语义网络并提供 8 项列表折叠，完整 49/55 审计需要用户显式展开。
