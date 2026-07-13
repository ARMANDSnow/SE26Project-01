# Iteration iter05 - 远端 Agent 能力与论文存储整合

## Context

远端 `main` 在旧论文身份、PDF 路径和 mock/offline 数据模型上完成了 iter02–04，新增正文 chunks、FTS5 检索和跨论文 QA Agent。当前功能分支已经将论文获取与存储重构为 `source + source_id`、内容寻址 AssetStore、统一 PDF 服务和 Docling PaperDocument。本轮需要以本地新存储为唯一基础，移植远端 Agent 能力，并删除旧存储与全部 mock 路径。

## Goals

- 合并 `origin/main` 的团队提交与课程交付物，保留远端历史。
- 以 `PaperCandidate`、`PaperRecord`、AssetStore 和 PaperDocument 作为唯一论文数据链路。
- 将可追溯 chunks、FTS5 和真实跨论文 QA Agent 适配到当前文档存储。
- 删除 seed/mock LLM、前端 mock 和所有静默 metadata/mock fallback。
- 保留 DeepSeek `deepseek-v4-flash` 默认配置，API key 仅从环境变量读取。
- 完成后端、类型检查、前端构建和真实调用边界验证，再通过 PR 交付。

## Scope

- Git：为当前存储重构建立安全提交，merge `origin/main`，语义解决冲突。
- 后端：数据库 schema、文档解析、chunks/FTS、Agent 工具与编排、LLM 客户端、输入与错误处理。
- 前端：新论文契约、Agent execution trace、证据展示，删除自动提问和 mock。
- 测试与脚本：新空库、AssetStore、文档索引、Agent scope/citation、性能 smoke 与显式真实模型 smoke。
- 文档：README、AGENTS、handoff、backlog 和本 iteration closeout。

## Acceptance Criteria

- 新数据库只创建新 schema，不依赖或迁移旧 `arxiv_id/file_path` 数据。
- PDF 通过 AssetStore 管理，Agent 不读取或暴露本地文件路径。
- chunks 由完成的 PaperDocument 生成并绑定当前 `source_hash`；PDF 变化会失效旧索引。
- `search_metadata` 可筛选候选，但最终引用只来自当前文档 chunks。
- `agentic` 与显式 `classic` 均使用真实模型；无 API key 时明确失败。
- 页面加载、默认测试和性能 smoke 不会产生真实模型调用。
- 后端测试、mypy、前端 build、`git diff --check` 通过。
- iteration closeout 与 handoff 记录合并决策、验证结果和遗留风险。

## Plan

1. 建立安全提交并合并远端主分支。
2. 以新存储/schema 解决核心冲突，删除旧存储和 mock。
3. 接入 PaperDocument -> chunks -> FTS，并实现版本失效。
4. 适配真实 Agent、LLM 客户端与前端契约。
5. 合并可靠性修复和测试，修正隐式真实调用。
6. 完整验证、复核、iter-finish、提交、推送并创建 PR。

## Risks And Questions

- 远端 Agent 使用旧 `arxiv_id/arxiv_url` 契约，必须完整适配多来源身份。
- 远端 90 秒 Agent 上限小于单次 120 秒 provider timeout，需要改为剩余时间 deadline。
- 远端 Wiki 没有 `source_hash`；本轮 Agent 引用默认只允许当前文档 chunks。
- 当前工作区包含尚未提交的存储重构，合并前必须先建立可追溯安全提交。

## Progress Notes

- 2026-07-13：已 fetch `origin/main`；远端从共同基点新增 6 个提交。
- 2026-07-13：自动 merge-tree 演练报告 16 个冲突文件；真实工作区未被改动。
- 2026-07-13：用户批准删除 mock、不做数据库兼容迁移，并以本地存储方案覆盖旧存储。
- 2026-07-13：Windows 用户环境已设置 DeepSeek API key、基址和 `deepseek-v4-flash`，未输出密钥。
- 2026-07-13：完成真实 merge，以新存储为基线适配 PaperDocument Chunk、FTS5、Agent 工具/编排和前端 execution trace。
- 2026-07-13：删除根应用 seed/mock 与页面自动提问；真实 smoke 保持显式 opt-in。

## Closeout

### Summary

- 将 `origin/main` 的 6 个团队提交合入当前 feature branch；`UIPrototype/` 交付物原样保留。
- 以 `source + source_id`、AssetStore、PaperDocument 和 `source_hash` 为唯一数据链路，不保留旧 schema 迁移或 metadata 正文 fallback。
- 完成 PaperDocument -> Chunk -> FTS5 -> Agent 工具链路；PDF hash 变化时会失效全部旧派生知识。
- QA 默认真实 agentic，保留显式 classic；删除 mock/seed、自动提问与性能 smoke 中的付费调用。
- LLM 客户端使用环境变量、清洗 provider 错误、瞬时错误重试和 Agent 剩余 wall-clock timeout。

### Validation

- `.\\.venv\\Scripts\\python.exe -m pytest backend\\tests --basetemp=.codex-tmp\\pytest-merge-4 -p no:cacheprovider`：47 passed。
- `.\\.venv\\Scripts\\python.exe -m mypy`：9 个项目配置模块通过。
- 扩展 mypy（config/main/Agent/LLM/search 等 9 个合并核心模块）：通过。
- `npm run build`：TypeScript 检查和 Vite 生产构建通过；仅有已知 bundle size warning。
- `scripts/performance_smoke.py --requests 100 --workers 100 --threshold 3.0`：0 failures，p95 `0.4087s`，max `0.4165s`。
- `git diff --check -- . ':!UIPrototype/**'`：业务代码与文档通过；远端 `UIPrototype/` 原始交付物保留 2 处已存在空白警告，本轮不改写团队交付物。
- `scripts/real_agent_smoke.py`：未运行；该命令需 `RUN_REAL_LLM_TESTS=true` 并会产生真实网络/付费调用。

### Review

- 正确性：回归覆盖当前 hash Chunk、资产变化失效、FTS/Agent scope、引用白名单、元数据无 fallback 和 API 输入限制。
- 安全：Agent 不暴露本地路径；API key 不从文件读取、不写日志、不进 Git；provider 错误不返回 body。
- 集成：后端 Chunk/QA 契约已同步 TypeScript types、API 和 React Query；根应用 mock 文件已删除。
- 运维：默认测试、页面加载和性能 smoke 都不会调用真实模型。无阻断 finding。

### Follow-ups

- 用真实论文 gold set 评估检索/引用质量，而不是将当前确定性 embedding 视为真实语义检索。
- 将 PDF/Docling/Chunk 长任务移入任务队列，并增加 Playwright 工作台/Agent QA 端到端覆盖。
- 真实 provider 的 read-side 连接重置、`Retry-After` 和更完整重试矩阵仍可增强。

提交信息：`merge(iter05): integrate agent QA with paper asset storage`
