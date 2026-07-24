# Iteration iter03 - FTS5 Chunk 检索性能优化

## Context

iter02 已经建立可追溯 `paper_chunks`、chunk-first 检索问答和详情页片段展示。当前 chunk 检索仍会从 SQLite 拉取候选后在 Python 中逐条做 keyword + deterministic embedding 评分；这适合课程 MVP 的小 seed 库，但在更多论文和正文 chunks 下会成为规模风险。iter03 聚焦引入 SQLite FTS5 作为 query-aware prefilter，同时保持现有 API 契约、评分语义和 mock/offline 演示能力。

## Goals

- 增加可选的 `paper_chunks_fts` FTS5 索引，覆盖 chunk content、heading 和 paper title。
- 为已有 `paper_chunks` 提供可重复 FTS backfill，支持旧库升级。
- 让 `replace_paper_chunks` 在同一事务内同步主表和 FTS rows，避免 stale candidates。
- 将 `_search_chunks` 改为 FTS 候选预筛 + 现有 Python rerank，并在空查询、特殊查询或 FTS 不可用时 fallback。
- 补齐后端测试，确认响应 shape 不变、chunk citation 仍优先、准确率基线不回退。

## Scope

- 后端：schema/init、FTS 支持探测、chunk FTS backfill、chunk 写入同步、search/QA 检索候选层、测试。
- 文档：iteration 记录、索引、closeout 和 handoff。
- 不改前端类型/API/UI，不做 PDF/HTML 结构解析、真实 QA gold set 或 Playwright smoke。

## Acceptance Criteria

- `.venv/bin/python -m pytest backend/tests` 通过。
- `npm run build` 通过。
- 后端启动后，`scripts/performance_smoke.py --requests 100 --workers 100 --threshold 3.0` 通过。
- `git diff --check` 通过。
- FTS5 可用时，seed/backfill 后 FTS rows 与 `paper_chunks` 同步。
- 替换 chunk 后，FTS 可搜到新内容且搜不到旧内容。
- `paper_ids` scoped QA/search 不被全局 FTS 候选裁剪误伤。
- 特殊字符 query 和空 query 不破坏现有 fallback 行为。

## Plan

- 创建 iter03 记录并更新 iteration 索引。
- 在数据库层加入 FTS5 支持探测、虚拟表创建、rebuild/backfill 和 chunk FTS 同步 helper。
- 改造 `replace_paper_chunks`，在同一事务内删除旧 FTS rows、插入主表、用 chunk `id` 写入 FTS rowid。
- 改造 `_search_chunks`，优先通过安全 MATCH 表达式获取 scoped chunk ids，再复用现有评分和响应 shape；异常时回到全量评分。
- 增加 schema、backfill、replace、special query、paper scoped QA/search 和 API shape 测试。
- 运行完整验证，调用只读 closeout review subagents，修复 findings。
- 更新 Closeout、`docs/AGENT_HANDOFF.md`，检查 diff/status 并 commit。

## Risks And Questions

- FTS5 在部分 SQLite 构建中可能不可用；本轮必须探测并 fallback，不能阻塞启动。
- FTS tokenizer 对中英混排和 `C++`、`gpt-4o-mini` 等特殊查询需要接近 substring 语义；本轮使用 trigram tokenizer，短于 3 字符的查询走旧路径。
- `paper_title` 被索引后，标题更新必须同步 `title_hash` 和 FTS rebuild，避免 title-based 去重与检索标题不一致。
- 本轮不改变 QA confidence、citation 字段或前端显示。

## Progress Notes

- 2026-07-09：iter03 启动，主题锁定为 FTS5 Chunk 检索性能优化；已按自动迭代协议启动只读功能差距和 bug/质量风险审查。
- 2026-07-09：预审查结论：需要 FTS5 支持探测、旧库 FTS backfill、`replace_paper_chunks` 同事务同步、`paper_ids` scoped candidate filtering、特殊 query fallback，并保持现有 rerank 与 API shape。
- 2026-07-09：完成 FTS5 trigram 索引、旧 schema 自动重建、可重复 backfill、chunk replace 同步、FTS 失败降级和 search/QA 候选预筛；补齐 schema、backfill、replace stale、scoped FTS、special query、API shape 和 title hash 回归测试。
- 2026-07-09：closeout review 后修复 `title_hash` 更新、FTS ready 探测、`replace_paper_chunks` savepoint 原子性、FTS 空候选退回全扫、unicode tokenizer 无法召回中英混排 `RAG` 等问题。

## Closeout

### Summary

- 新增可选 `paper_chunks_fts` FTS5 trigram 索引，索引 chunk content、heading 和 paper title，并以 `paper_chunks.id` 作为 FTS `rowid`。
- `init_schema` 会探测 FTS5、创建或重建 FTS schema、为已有 chunks 做可重复 backfill；FTS 不可用时保留原检索路径。
- `replace_paper_chunks` 使用 savepoint 同步主表和 FTS rows；FTS 同步失败时禁用坏索引并重试主表写入，保证演示路径不被可选索引阻断。
- `_search_chunks` 改为 FTS scoped candidate ids + 现有 keyword/embedding rerank；`None` 表示 FTS 不可用并 fallback，空列表表示有效无候选，避免 no-match query 全量 chunk 扫描。
- 同步修复论文标题更新时的 `title_hash` 维护，避免标题变化后 title-based 去重失效。

### Validation

- `.venv/bin/python -m pytest backend/tests`: passed, 33 tests.
- `npm run build`: passed.
- `.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0`: passed, 0 failures, p95 `0.9062s`, max `0.9164s`.
- `git diff --check`: passed.

### Review

- Pre-implementation read-only reviews found expected gaps: no FTS table/backfill, no FTS sync in `replace_paper_chunks`, no candidate prefilter, missing scoped/special-query tests; all were addressed.
- Closeout correctness review found four issues: `title_hash` not updated with title changes, FTS readiness checking only `sqlite_master`, chunk replace missing savepoint/fallback, and empty FTS candidates falling back to full chunk scan. All were fixed and covered by tests.
- Closeout contract/test review found API shape compatible and requested stronger scoped FTS and special-query assertions; tests now directly inspect FTS scoped candidates and assert `C++`/hyphen/Chinese chunk recall plus no-match chunk behavior.
- Closeout security review found no blocking issues: MATCH and dynamic `IN` values are parameterized, FTS rank/debug fields and `embedding_json` are not exposed, and no secrets or generated artifacts were added.

### Follow-ups

- Build a real arXiv retrieval/QA gold set to measure FTS chunk recall and citation quality beyond seed metadata.
- Improve PDF/HTML parsing quality beyond plain text extraction, including sections, table/figure captions and citation alignment.
- Add Playwright smoke for paper detail processing, chunks panel rendering, QA evidence and learning workflows.
- Consider a dedicated migration/version table if future SQLite schema changes become more complex than idempotent init/backfill.
