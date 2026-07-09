# Iteration iter02 - 正文解析与可追溯 Chunk 知识链路

## Context

iter01 已经把核心 API 契约、mock/real LLM 路径、SQLite 并发设置、问答 citation 和性能 smoke 基线收紧。当前知识链路仍主要基于论文摘要和生成后的 Wiki 分区，缺少可追溯到原始正文的片段层。iter02 聚焦补齐 PDF/HTML 正文解析、chunk 入库和 chunk-first 检索问答能力，同时保留离线演示路径。

## Goals

- 增加可追溯 `paper_chunks` 存储，记录来源、顺序、offset、token 估算和 embedding。
- 在论文结构化解析中接入 HTML/PDF 正文抽取与 chunk indexing，失败时回退 metadata chunk。
- 让检索和问答优先使用 chunks 作为证据，并保留 Wiki fallback。
- 暴露论文 chunks API，并在论文详情页展示原文片段来源和可核验内容。
- 补齐后端契约测试、chunking 测试和前端构建验证。

## Scope

- 后端：schema、chunk CRUD、fulltext 抽取服务、process pipeline、search/QA citation shape、chunks API、测试。
- 前端：`PaperChunk` 类型、chunks API/hook、论文详情 chunks 面板、QA evidence 对 chunk/source 字段的展示兼容。
- 文档：iteration 记录、索引、closeout 和 handoff。

## Acceptance Criteria

- `.venv/bin/python -m pytest backend/tests` 通过。
- `npm run build` 通过。
- 后端启动后，`scripts/performance_smoke.py --requests 100 --workers 100 --threshold 3.0` 通过。
- `git diff --check` 通过。
- 处理论文后生成至少一个可追溯 chunk；正文获取失败时生成 metadata chunk 且 `process_paper` 不失败。
- `/api/papers/{paper_id}/chunks` 支持分页，未知论文返回 404。
- `/api/wiki/search` 和 `/api/qa` 能返回 chunk-backed citations，并兼容旧 Wiki citation 字段。

## Plan

- 创建 iteration 记录并更新索引。
- 增加 `paper_chunks` schema、写入替换、详情查询和分页查询。
- 新增 fulltext 服务，按 HTML -> PDF -> metadata fallback 抽取并切 chunk。
- 将 chunk 抽取写入 `process_paper`，并把正文 excerpt 传给 SummaryAgent。
- 改造 search/QA 为 chunk-first + wiki fallback，并扩展 citation 字段。
- 更新前端类型、API hook、论文详情 chunks 面板和 QA evidence 展示。
- 增加测试并运行完整验证。
- 执行只读 closeout review、修复 findings、更新 closeout 和 handoff 后 commit。

## Risks And Questions

- arXiv HTML/PDF 网络请求不稳定，必须保证失败时落到 metadata chunk。
- PDF 文本抽取质量依赖第三方库，本轮只建立基础正文片段，不做复杂版面还原。
- 本轮不实现 FTS5、定时 ingestion、订阅推荐或真实大规模 QA gold set。
- 当前工作区已有 agent 入口文档改动，实施时保留并继续更新，不回退。

## Progress Notes

- 2026-07-09：iter02 启动，主题锁定为正文解析与可追溯 chunks；已按自动迭代协议启动只读功能差距和 bug/质量风险审查。
- 2026-07-09：完成 `paper_chunks` schema、metadata seed backfill、HTML/PDF/metadata fulltext 服务、process pipeline 接入、chunk-first search/QA、chunks API、前端 chunks 面板和 QA citation 展示。
- 2026-07-09：closeout review 后修复 retrieval 预裁剪、默认 seed 无 chunks、fulltext fetch redirect/size/PDF 限制、chunks UI 错误态和长文本可访问性问题。

## Closeout

### Summary

- 新增可追溯 `paper_chunks` 表，记录 source、URL、顺序、heading、offset、token 估算和 embedding；reprocess 会在同一事务中删除并重建该论文 chunks，避免 stale rows。
- 新增 fulltext 服务：`ENABLE_FULLTEXT_FETCH=auto` 下 mock/offline 默认 metadata chunks，真实路径可抓取 arXiv HTML/PDF；抓取失败会 fallback metadata，并限制 URL、content-type、下载大小、PDF 页数和抽取字符数。
- `process_paper` 已接入 `FullTextExtractor` 和 `ChunkIndexer`，SummaryAgent 使用 capped fulltext excerpt；seed 中已处理论文会 backfill metadata chunks。
- `/api/wiki/search` 和 `/api/qa` 改为 chunk-first + Wiki fallback，citation 保留旧字段并新增 `chunk_id/source/source_type/chunk_index/offset` 等可选字段。
- 新增 `/api/papers/{paper_id}/chunks` 分页 API；前端新增 chunks 类型、API hook、详情页原文片段面板和 QA evidence chunk/source 标签。

### Validation

- `.venv/bin/python -m pytest backend/tests`: passed, 22 tests.
- `npm run build`: passed.
- `.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0`: passed, 0 failures, p95 `1.2061s`, max `1.2171s`.
- `git diff --check`: passed.

### Review

- Pre-implementation read-only reviews found expected gaps: no chunk storage, process pipeline only using metadata, wiki-only retrieval, missing frontend contract, missing PDF dependency and tests; all were addressed.
- Closeout correctness review found chunk retrieval pre-limited by recency and seed processed papers missing chunks; fixed by scoring all chunks before limiting and backfilling metadata chunks for processed seed/existing DB rows.
- Closeout security review found redirect/size/PDF parsing limits missing; fixed by final URL validation, arXiv-only URL guard, content-type checks, capped download bytes, capped PDF pages and capped extracted characters. No secrets found.
- Closeout contract/UI reviews found no blocking contract mismatches; non-blocking fallback/pagination tests and chunk panel error/wrapping/accessibility improvements were added.

### Follow-ups

- Add SQLite FTS5 or another query-aware prefilter before chunk/vector ranking for larger local libraries.
- Improve PDF/HTML parsing quality beyond plain text extraction, including section headings and table/figure handling.
- Build a real arXiv retrieval/QA gold set to evaluate chunk citations beyond seed metadata.
- Add Playwright smoke for paper detail processing, chunk panel rendering, QA evidence and learning workflows.
