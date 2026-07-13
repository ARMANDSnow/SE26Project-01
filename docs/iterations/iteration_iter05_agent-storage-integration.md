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

## Closeout

待 `iter-finish` 填写。
