# Agent Handoff

最后更新：2026-07-13，iter05 closeout。

## Current Status

- 当前分支：`codex/refactor-paper-storage`，已将 `origin/main` 的 iter02–04 Agent/FTS 能力适配到新论文存储。
- 论文唯一身份：`source + source_id`；支持 arXiv、USENIX、SIGOPS 和本地上传。
- PDF 由内容寻址 AssetStore 管理；Docling `PaperDocument` 与 PDF `source_hash` 绑定。
- Chunk 只从当前已完成的 `PaperDocument` 生成；FTS5 trigram 只是可重建的派生索引。
- QA 默认真实 `agentic` 模式，可显式使用 `classic`；两者都不会回退 mock。
- `search_metadata` 只用于候选规划；最终引用只能来自 `search_text` 检索并经 `open_evidence` 打开的当前正文 Chunk。
- API Key 只从 `LLM_API_KEY` 环境变量读取；默认配置为 `https://api.deepseek.com` / `deepseek-v4-flash`。
- 远端 `UIPrototype/` 交付物原样合入，没有作为当前业务实现修改。

## Data And Agent Flow

```text
PaperCandidate -> papers(source, source_id) -> PDF AssetStore
    -> PaperDocument(source_hash) -> paper_chunks -> optional FTS5
    -> QA Agent search/open allowlist -> cited answer
```

PDF asset 变化时，系统删除旧 `PaperDocument`/Chunk，失活旧 summary，并清理 Wiki/概念关联。本轮明确不提供旧 `arxiv_id/file_path` schema 的数据迁移；当前没有需保留的真实数据。

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests --basetemp=.codex-tmp\pytest-merge-4 -p no:cacheprovider
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m mypy --explicit-package-bases backend/app/config.py backend/app/main.py backend/app/services/agents.py backend/app/services/fulltext.py backend/app/services/llm.py backend/app/services/paper_tools.py backend/app/services/qa_agent.py backend/app/services/search.py backend/app/services/text_utils.py
npm run build
.\.venv\Scripts\python.exe scripts\performance_smoke.py --base-url http://127.0.0.1:8765 --requests 100 --workers 100 --threshold 3.0
git diff --check -- . ':!UIPrototype/**'
```

结果：47 个后端测试通过；两组 mypy 检查通过；前端 build 通过；100 并发性能 smoke 通过，p95 `0.4087s`、max `0.4165s`；排除未改动的远端 `UIPrototype/` 后 diff check 通过。真实模型 smoke 保持 `RUN_REAL_LLM_TESTS=true` 显式开关，本轮未产生付费调用。

## Known Risks

- Docling 解析与远程 PDF 下载仍是同步长任务；大批量使用需任务队列。
- deterministic embedding 只用于本地重排，真实检索质量仍需 gold set 评估。
- FTS5 trigram 不可用时会回退到 Chunk 全量重排，正确性保留但大数据量性能会下降。
- 前端尚无 Playwright 端到端覆盖；当前依赖 TypeScript build 和 API 回归。

## Next Candidates

1. 建立真实论文 QA/retrieval gold set，评估引用准确率、检索恢复、延迟与成本。
2. 将 PDF 下载、Docling 解析、Chunk/FTS 建索引移入可观测任务队列。
3. 增加 Playwright smoke，覆盖上传/解析、Chunk 展示、Agent QA 和论文工作台。
4. 设计用户 Review + Memory 闭环，保证偏好和失败案例可审计。

## Git Notes

- 本轮实现记录：`docs/iterations/iteration_iter05_agent-storage-integration.md`。
- 推送前必须再次 `git fetch origin main`，确认远端未超越当前合并基点。
- 交付走 feature branch + PR，不直推 `main`。
