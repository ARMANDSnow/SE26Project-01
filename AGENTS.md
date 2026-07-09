# AGENTS.md - Agent 工作流入口

> 任何 AI agent 进入本仓库时，先读完本文件，再读 `docs/AGENT_HANDOFF.md` 和最新 iteration 记录。

## 项目定位

本项目是面向科研论文学习场景的 arXiv 智能论文阅读工具。目标是自动抓取 arXiv 论文，调用大模型阅读与抽取概念，以 Wiki/知识图谱/问答/学习管理的形式沉淀论文知识。

当前技术栈：

- 前端：Vite + React + TypeScript
- 后端：FastAPI + SQLite
- 智能能力：OpenAI 兼容接口；默认 `ENABLE_MOCK_LLM=true`，无需 API key 可离线演示

## 进入仓库必读顺序

1. `docs/AGENT_HANDOFF.md`：当前能力、风险、下一轮候选。
2. `docs/iterations/README.md`：迭代索引。
3. 最新的 `docs/iterations/iteration_*.md`：最近一轮实现和 closeout。
4. `README.md`：启动、环境变量和验证命令。

## 默认工作流

每轮较完整的工程任务必须走以下流程：

1. **Grounding**：先读代码、README、现有 docs 和 git 状态，不直接猜。
2. **差距/风险审查**：复杂任务先由主 agent 做本地只读审查；只有用户明确授权 subagents 时，才分工审查功能缺口、bug、测试缺口。
3. **iter-start**：为新一轮创建或更新 `docs/iterations/iteration_<id>_<slug>.md`，并更新 `docs/iterations/README.md`。
4. **实现**：按已有架构小步改动，避免无关重构；前后端契约变更必须同步类型、API、测试和文档。
5. **验证**：至少运行后端测试和前端构建；涉及性能或并发时跑性能 smoke。
6. **iter-finish**：收尾时更新 iteration closeout 和 `docs/AGENT_HANDOFF.md`，记录验证结果、遗留风险和下一轮候选。
7. **Git**：提交前检查 `git status`、`git diff --check`、暂存范围；除非用户明确要求，不主动 push。

## 自动迭代模式

当用户明确说“启动自动迭代”“起一轮迭代”“按完整迭代流执行”或给出同等授权时，视为本轮已授权：

- 使用只读 subagents 做进度/差距/bug 审查。
- 实现后再次使用只读 subagents 做代码审查、安全/密钥审查和必要的前端审查。
- 跑项目验证命令。
- 执行 iter-finish 并自动 commit。

自动迭代模式的标准顺序：

1. 读取 `AGENTS.md`、`docs/AGENT_HANDOFF.md`、迭代索引、最新 iteration 和 `git status`。
2. 调用 subagents 跟踪当前进度：至少一个功能差距视角、一个 bug/质量风险视角；前端改动较多时加 UI/UX 视角。
3. 主 agent 汇总审查结果，创建/更新本轮 iteration 文件和索引。
4. 按计划实现，保持改动范围收敛。
5. 运行后端测试、前端构建和必要 smoke。
6. 调用收尾审查 subagents：代码正确性、契约/测试覆盖、安全/密钥；审查必须只读。
7. 修复审查发现的问题，并重跑相关验证。
8. 执行 iter-finish：更新 iteration closeout、`docs/AGENT_HANDOFF.md`、验证结果、审查结论和 follow-ups。
9. 检查 `git diff --check`、`git status`、暂存范围，然后自动 commit。
10. 只有用户明确说“push”或“commit+push”时才 push。

如果用户只说“实现这个小改动”，不默认进入自动迭代模式。

## subagent 使用规则

- 只有用户明确要求 subagents、delegation 或 parallel agent work 时才调用。
- subagent 默认只读审查，除非明确分配独立写入范围。
- 不让多个 agent 修改同一文件集合。
- subagent 输出必须被主 agent 汇总进 iteration 记录或 handoff，不要只停留在对话里。

## 验证命令

```bash
.venv/bin/python -m pytest backend/tests
npm run build
DATABASE_PATH=/tmp/arxiv_iter.sqlite3 .venv/bin/python -m uvicorn backend.app.main:app --port 8000
.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0
git diff --check
```

性能 smoke 需要后端服务正在运行；跑完应关闭服务，避免遗留进程影响下一轮。

## 工程守则

- 不提交真实 API key、`.env`、本地数据库、构建产物、缓存目录。
- 默认 mock LLM 路径必须可用；真实 LLM 路径必须有明确失败处理。
- 前端默认不得静默回退 mock；只有 `VITE_USE_MOCK=true` 才允许内置样例数据。
- API 契约变更必须同步 `src/types.ts`、`src/api.ts`、React Query hooks 和后端测试。
- SQLite 写路径要考虑事务、外键和并发锁。
- UI 改动遵循现有 shadcn/ui + Tailwind 风格，不引入新的视觉体系。
- 推送前如远端有新提交，先 fetch/rebase，保留远端用户改动。

## 迭代记录格式

每轮 iteration 建议包含：

```text
Context / Goals / Scope / Acceptance Criteria / Plan / Risks And Questions / Progress Notes / Closeout
```

Closeout 至少包含：

```text
Summary / Validation / Review / Follow-ups
```

`docs/AGENT_HANDOFF.md` 是跨迭代续写的单一入口；每轮 iter-finish 必须追加或更新。
