# Iteration iter01 - 可信知识链路与稳定性修复

## Context

当前项目已经覆盖 arXiv 抓取、论文库、结构化 Wiki、概念图谱、带出处问答和学习管理等 MVP 入口，但仍偏演示型。iter01 聚焦把核心链路从“可展示”推进到“可验证、可失败、可定位”。

## Goals

- 修复高优先级 API 契约和数据库一致性问题。
- 收紧前端 mock 策略，让真实后端错误进入错误态。
- 接入最小真实 LLM 路径，保留 mock 模式便于离线演示。
- 补齐关注主题订阅入口。
- 建立 FastAPI 契约测试、最小准确率评测和性能 smoke 验证基线。

## Scope

- 后端：收藏 404、结构化解析失败契约、ingest 去重统计、SQLite `busy_timeout`/WAL、图谱空结果、LLM 解析和问答路径。
- 前端：`VITE_USE_MOCK` 显式开关、订阅查询/新增、process 失败处理、ingest 去重展示。
- 测试：FastAPI/TestClient 契约测试、foreign key 一致性、seed 数据准确率断言、构建和性能 smoke。

## Acceptance Criteria

- `.venv/bin/python -m pytest backend/tests` 通过。
- `npm run build` 通过。
- 本地 API 启动后，`scripts/performance_smoke.py --requests 100 --workers 100 --threshold 3.0` 通过。
- 生产默认模式下，后端 404/500 不再被前端 mock 数据掩盖。
- 无匹配图谱主题返回空节点和空关系。

## Plan

- 创建迭代记录和索引。
- 修复数据库写入、去重和并发设置。
- 统一 API 成功/失败契约并补测试。
- 接入最小 LLM 结构化输出与问答合成。
- 更新前端 API 层、学习管理订阅 UI 和相关类型。
- 运行验证并记录 closeout 结果。

## Risks And Questions

- 本轮不实现完整 PDF/HTML 正文解析、后台定时调度、个性化推荐算法。
- LLM 输出只做最小 JSON 解析和校验，准确率评测先基于 seed 数据建立可自动运行的下限。
- 当前工作区已有未提交前端改动，实施时只改本轮相关文件，不回退既有改动。

## Progress Notes

- 2026-07-09：iter01 启动，基线测试曾通过：后端 6 tests、前端 build、100 并发 smoke p95 约 0.98s。
- 2026-07-09：实现核心契约修复、显式前端 mock 开关、最小 LLM 解析/问答路径、订阅入口和新增测试；验证通过：后端 15 tests、前端 build、100 并发 smoke p95 约 1.24s。

## Closeout

### Summary

- 完成后端核心契约修复：收藏不存在论文返回 404，结构化解析失败返回 422，ingest 返回抓取/新增/去重统计，图谱无匹配主题返回空结果。
- 完成可靠性增强：SQLite 文件库启用 `busy_timeout` 和 WAL，批量 ingest 使用显式事务，重复标题不同 arXiv ID 不再导致入库 500。
- 完成知识链路增强：非 mock 模式下结构化解析和问答会调用 `LLMClient`，mock 模式保留离线演示路径。
- 完成前端收口：默认不再静默回退 mock，新增 `VITE_USE_MOCK=true` 显式演示开关，学习管理页新增关注主题入口。
- 完成测试基线：FastAPI 契约测试、foreign key 一致性、seed 数据 citation/grounding 准确率下限和包含 QA 的性能 smoke。

### Validation

- `.venv/bin/python -m pytest backend/tests`: passed, 15 tests.
- `npm run build`: passed.
- `.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0`: passed, 0 failures, p95 `1.255s`, max `1.2574s`.
- `git diff --check`: passed.

### Review

- No blocking findings after closeout review.
- Secret scan found only documented environment variable names and placeholder API key text; no credentials were committed.
- Residual risk: FastAPI `@app.on_event("startup")` emits a deprecation warning but does not block current validation.

### Follow-ups

- iter02 candidate: full PDF/HTML parsing with traceable chunks.
- iter02 candidate: scheduled arXiv ingestion and subscription-driven recommendations.
- iter02 candidate: larger retrieval/QA gold set beyond the current seed-based 90% baseline.
