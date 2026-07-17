# 2026-07-17 全功能网页巡检与 Bugfix

## Context

本轮不创建新的 iter-start。目标是在隔离数据库和真实 OpenAI 兼容模型配置下启动前后端，从网页端连续操作当前全部主要能力，寻找功能错误、视觉问题、反直觉交互与无障碍缺陷；确认问题后修复、回归、形成 closeout，并只 commit、不 push。

开工前工作树包含已完成但未提交的 Iter16 变更。为建立可回退基线，先完成密钥扫描、验证和独立提交：

- `38a5dcc feat(iter16): add reproducible research quality evaluation`

真实 Key 仅从桌面 `key.rtf` 动态读取后注入隔离后端进程，没有打印、复制进仓库或写入 `.env`。隔离数据位于 `/tmp`。

## Goals

- 覆盖登录、普通 Chat、论文检索/导入/解析/总结/问答/笔记/收藏、资料库、目录推荐、研究项目、深度研究、固定报告、Citation Evidence 和论文定位。
- 在桌面与 390px 移动视口检查溢出、触控尺寸、信息层级与可访问名称。
- 使用真实模型、真实 arXiv PDF 和 Docling 验证生产链路。
- 修复本轮确认的问题，补自动测试并形成可审计 closeout。

## Scope

### 真实网页验证

- 注册隔离账户并导入 8 篇真实 arXiv 论文。
- 普通 Chat 获得准确非空回复。
- SmartRAG 完成真实 PDF/Docling 解析，共 13,970 tokens。
- 使用真实模型生成 SmartRAG 全文概要，并完成基于全文的单篇论文问答。
- 保存笔记、收藏论文、创建自定义资料库目录，真实模型目录推荐后由用户动作确认移动。
- 创建研究项目并加入 SmartRAG。
- 从 Chat 启动完整 17 步 topic 深度研究：17/17 步、7/7 用户阶段完成，30 个候选、1 篇全文、8 次模型调用、12 次工具调用、3 条有效 Citation；随后检查固定报告、Citation Evidence inspector 和论文 Chunk 定位。
- 检查 1280px 桌面与 390×844 移动布局；修复后再次进行视觉与语义 DOM 回归。

### 不在范围

- 未修改或提交桌面 Key。
- 未访问或重建默认旧论文数据库。
- 未 push。
- 修复检索后没有再次消耗一轮完整 17 步真实模型任务；使用首次真实模型生成的原查询计划做确定性复现，并由单元测试覆盖。

## Findings

### P1：论文正文与模型概要的 Markdown 被当作纯文本

旧 `MarkdownBlock` 仅识别一级标题、简单无序列表和数字前缀。真实输出中的二/三级标题、粗体、代码、表格、分隔线和嵌套列表均显示为字面量，例如 `## 1. 总体架构`、`**大模型难以直接上端**`，严重破坏长文阅读层级。

### P1：深度研究漏掉本地已存在的显式命名论文

真实任务明确要求比较 SmartRAG，但最终数据集只有 SVD-RAG。根因有两层：

- Search Agent 把概念名写入 `categories`，而本地检索把它当作精确 arXiv category 过滤，导致 0 条本地结果。
- metadata search 只接受整段连续子串；真实查询 `SmartRAG structured retrieval augmented generation mobile arXiv` 无法命中标题中的 `SmartRAG`。

流水线按证据不足 fail-safe 收口，没有伪造比较结论，但召回行为不符合用户意图。

### P2：资料库根目录计数与实际聚合视图矛盾

根目录视图会展示所有后代目录中的论文，但 badge 只统计根目录直接项，出现“根目录 0、页面内却有 1 篇论文”的反直觉状态。

### P2：移动触控与无障碍细节

- 论文工作台布局按钮、Tabs、PDF/解析文本切换、Paper Chat selector/新建按钮小于项目 44px 目标。
- 论文详情收藏按钮始终叫“收藏”，已收藏时没有动态名称和 `aria-pressed`。
- 论文卡片/表格收藏控件缺少 `aria-pressed`。
- 研究项目页面把内部 UUID 作为无上下文的 sr-only 文本暴露给屏幕阅读器。

## Fixes

- 使用 `react-markdown` + `remark-gfm` 重建安全 Markdown renderer；支持标题、粗体、列表、引用、代码、表格、链接和分隔线，并对模型常见 loose Markdown 做轻量规范化。
- metadata search 增加多词召回与相关性排序，完整短语仍具有最高优先级；显式命名词可以从长查询中召回。
- topic pipeline 只把合法 arXiv code 传给本地/arXiv category filter；Search Agent prompt 明确命名论文与 category code 契约。
- 根目录 badge 改为整个资料库聚合项总数，子目录继续显示直接项数量。
- 统一 Tabs 和论文工作台相关控件的最小触控高度为 44px。
- 收藏控件补动态可访问名称与 pressed 状态。
- 移除项目视图中无语义的 UUID sr-only 输出。
- 新增命名论文长查询召回、合法 category 过滤、根目录跨子目录计数回归测试。

## Acceptance Criteria

- [x] 主要功能通过真实网页连续操作。
- [x] 普通 Chat、全文总结、Paper Chat、目录推荐和 17 步深度研究完成真实模型调用。
- [x] 论文 Markdown 呈现真实 heading/list/strong/code 等语义节点。
- [x] 首次真实运行生成的 SmartRAG 长查询可在修复后召回本地 SmartRAG。
- [x] 资料库根目录计数与聚合内容一致。
- [x] 收藏状态具备动态名称与 pressed 语义。
- [x] 桌面/移动端无新增溢出或 console error。
- [x] 后端全量测试、strict mypy、前端构建、三视口 Playwright 通过。
- [x] 仓库未包含 Key、`.env`、测试数据库或构建产物。
- [x] 只 commit，不 push。

## Validation

- `.venv/bin/python -m pytest backend/tests`：146 passed。
- `.venv/bin/python -m mypy`：通过。
- `npm run build`：通过。
- Playwright（1440 / 1024 / 390）：9 passed，6 skipped（按测试设计仅桌面执行的场景）。
- `git diff --check`：通过。
- 真实网页回归：
  - Markdown 的 `# / ## / ###`、strong、list、inline code、separator 均呈现为结构化 DOM。
  - 资料库根目录和自定义目录均显示 1，聚合内容一致。
  - 已收藏按钮显示“取消收藏”并具有 pressed 状态。
  - 项目页面语义 DOM 不再包含内部 UUID。
  - 浏览器 console error 为 0。

首次 Playwright 运行因 macOS 沙箱拒绝 Chromium Mach port 而在浏览器启动前失败；按工程规则在沙箱外重跑后通过，未将环境失败计为产品失败。

## Review

- 真实深度研究在修复前仅纳入 1 篇论文，但报告明确披露数据集限制与 SmartRAG 证据缺口，没有生成无证据比较，fail-safe 行为正确。
- 检索修复保持权限条件、category 精确过滤和结果上限不变，只放宽 metadata query 的长查询召回方式。
- Markdown 默认不解析原始 HTML；外部链接使用新窗口和 `rel=noreferrer`，表格/代码块限制在水平滚动容器中。
- 测试数据、上传文件和真实模型配置均位于 `/tmp` 或桌面原文件，不进入 Git。

## Follow-ups

1. 如需付费级最终确认，可用同一“SmartRAG + related method”目标再跑一次完整 topic Run，预期本地候选阶段直接包含 SmartRAG。
2. 为 `MarkdownBlock` 增加前端组件级测试，固定 loose Markdown 与复杂表格的渲染契约。
3. 后续可将通用 metadata token ranking 提升为 SQLite FTS/BM25，减少宽查询中常见词带来的噪声。
