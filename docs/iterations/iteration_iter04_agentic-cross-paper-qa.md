# Iteration iter04 - Agent 驱动的跨论文知识库探索

## Context

iter03 已建立可追溯 chunks 与 FTS5 候选预筛，但问答仍是固定的单轮 Top-K：系统先选 5 条证据，再让模型一次合成答案。助教 2026-07-13 的建议要求项目更接近论文阅读 Agent：模型应能把本地论文库当作工具，自主决定搜索、打开证据、继续追查和收尾回答，同时保留 Review、Memory 与 Evaluation 的后续闭环。

本轮预审查还确认了四类现存问题：真实 LLM 失败会静默降级；重复处理会残留旧概念关联；普通 chunk 约束错误可能误关 FTS；空白问题、笔记和关注主题可绕过校验。iter04 先修这些可靠性问题，再实现最小可验证的跨论文问答 Agent。

## Goals

- 修复预审查中可复现的概念替换、FTS 降级和输入校验问题。
- 让真实模型成功、失败与 fallback 状态可观测，避免“看似验证成功、实际走了 mock”。
- 提供只读的论文库工具：元数据搜索、全文搜索、显式打开证据。
- 实现带预算、停止条件、paper scope 和 citation allowlist 的多轮 tool-calling QA Agent。
- 保持默认 mock/offline 演示可用，并让 mock 路径展示确定性的多步探索 trace。
- 增加真实 API opt-in smoke，验证至少两篇论文、至少两次工具调用和引用闭环。
- 建立长期项目 Memory/TODO，持久化助教建议与尚未实现事项。

## Scope

- 后端：LLM chat/tool-call 客户端、论文库只读工具、QA Agent 编排、错误/执行 trace、输入校验、概念替换与 FTS 错误边界、测试、真实 smoke。
- 前端：QA 契约同步、Agent 探索 trace 与更准确的“证据匹配度”文案；不新增视觉体系。
- 文档：长期 backlog、README 能力边界、iteration、handoff 和验证记录。
- 不在本轮实现真实 embedding 全量迁移、用户反馈自动改写 prompt、章节/表格/公式解析、自主研究 Idea/novelty 判断或代码复现。

## Acceptance Criteria

- 重复处理论文后，旧 `paper_concepts` 关联不再残留。
- chunk 主表约束错误不会删除或禁用健康的 FTS 索引。
- 纯空白 question/note/topic 返回 422；QA paper ids 去重并有数量上限。
- Agent 只可调用 allowlist 只读工具；工具参数、结果长度、轮数、总调用数均有硬上限。
- 只有被 `open_evidence` 打开的证据可以进入 citations；paper scope 不可越界。
- mock 测试覆盖 search -> open -> answer；scripted LLM 测试覆盖多轮 tool calls、跨两篇论文引用、非法参数和停止条件。
- 真实 smoke 只有显式启用才运行，并断言 `execution.mode=agentic_real`、工具调用数和跨论文 citations；没有 key 时明确跳过而不是假通过。
- `.venv/bin/python -m pytest backend/tests`、`npm run build`、性能 smoke、`git diff --check` 通过。

## Plan

- 汇总只读预审查，创建 iter04 记录和长期 backlog。
- 修复 stale concepts、FTS 错误边界、空白/长度/数量校验和真实 LLM 可观测性。
- 新增论文库工具及 QA Agent 循环，保持旧检索作为可调用能力与 classic fallback。
- 同步 API、TypeScript 类型、React Query 与 QA 页面 trace。
- 增加单元/接口测试和 opt-in 真实模型 smoke。
- 跑完整验证与性能 smoke，再调用只读 subagents 做正确性、契约/测试、安全/密钥和 UI 审查。
- 修复 findings，执行 iter-finish，更新 handoff/backlog 并自动 commit；不 push。

## Risks And Questions

- 当前进程未设置 `LLM_API_KEY`，因此真实 smoke 在获得安全环境注入前只能明确 skip；不得把 key 写入命令、日志、文档或测试 fixture。
- OpenAI-compatible 服务的 tool-call 响应细节可能不同；客户端需给出可诊断但不泄露 provider 响应/密钥的错误。
- 现有 chunk heading 只是近似片段标题，本轮按 evidence chunk 打开；真正章节/附录导航留到后续。
- 论文正文属于不可信数据，系统 prompt 必须明确“证据不是指令”，工具不得暴露任意文件系统或 shell。

## Progress Notes

- 2026-07-13：完成 Grounding；基线 33 backend tests passed，frontend build passed，真实模型相关环境变量未设置。
- 2026-07-13：功能差距审查确认全库 QA 仍是固定 Top-5 单轮 RAG，`QAAgent`/`EvidenceValidator` 仅为 trace 标签，没有 planner、tool schema、tool loop 或 citation allowlist。
- 2026-07-13：bug/质量审查复现 stale concepts、主表约束错误误关 FTS、空白输入入库，并确认真实 LLM 异常会静默降级。
- 2026-07-13：架构审查建议最小工具集为 `search_metadata`、`search_text`、`open_evidence`，真实验证必须显式断言 `agentic_real` 和实际工具调用数。
- 2026-07-13：完成可复现 bug 修复：概念关联与共现边改为替换/重建；健康 FTS 不再因主表约束错误被禁用；空白输入和宽松 paper id 被拒绝；classic QA 与论文处理的 provider 错误显式返回安全 502。
- 2026-07-13：实现只读论文库工具、真实模型 tool-calling 循环、mock 多步探索、paper scope、调用/轮数/字符/时间预算，以及“只有已打开证据可引用”的 answer/citation 双向校验；前端显示探索路径、状态、停止原因与 E 编号证据。
- 2026-07-13：首轮收尾审查发现并修复无效 citation 退化、未配对 tool call、空 scope snippet 泄露、真实 smoke fallback 假阳性、前端未打开证据误展示等 P1；复核确认无新 P0/P1。
- 2026-07-13：用户授权复用另一个本地项目的环境配置，密钥与 URL 只在子进程内映射且未复制、打印或写入仓库。排查并修复网关要求 SDK 兼容 headers、GPT-5 `max_completion_tokens`、长生成超时与瞬态重试；最终 `gpt-5.5-medium` 真实 smoke 两次通过。
- 2026-07-13：最终验证为 53 backend tests passed、frontend build passed、100 requests / 100 workers smoke 0 failures（p95 `0.9707s`）、桌面和 390px Playwright 0 console error、`git diff --check` passed；最终真实 smoke 为 10 tool calls、2 cited papers、HTML full text。
- 2026-07-13（push 前复验）：使用真实 `gpt-5.5-medium` 从前端导入并处理两篇新 arXiv 论文（52/45 chunks）。首轮发现模型可能只查元数据便提前收尾，新增“仅选择已处理候选、自动补做正文检索与证据打开”的恢复路径；最终浏览器问答以 7 次工具调用打开 3 条 HTML 证据，完成双论文比较与引用。

## Closeout

### Summary

- 新增 `search_metadata`、`search_text`、`open_evidence` 三个只读论文库工具，以及最多 6 轮、10 次实际工具调用、单轮 3 次执行、累计 16k 证据字符和软时间上限的 QA Agent。
- 真实模型可以自主搜索、打开和继续追查；答案中的 `[E#]` 必须与声明的 citation IDs 完全一致，且只允许引用本轮实际打开的证据。默认 mock 路径也执行确定性的 search -> open -> answer，保留离线演示能力。
- API 增加 agentic/classic 模式与结构化 execution trace；前端展示探索步骤、执行状态、停止原因和已打开证据，并将“置信度”改为“证据支持度”。
- 修复重复处理残留概念/共现边、主表约束错误误关 FTS、空白输入和宽松 ID、真实 provider 错误静默降级、tool-call 未配对、空 scope snippet 泄露等问题。
- LLM 客户端增加 GPT-5 payload、SDK-compatible gateway headers、120 秒超时、瞬态重试、禁止自动重定向和清洗错误码；真实密钥未进入仓库、日志、文档或数据库。
- 新增 `docs/PROJECT_BACKLOG.md`，持久化助教关于 Agentic Retrieval、Review、Memory、Evaluation 和产品定位的建议。
- 当真实模型只完成元数据筛选便提前回答时，编排器会在剩余工具预算内为最多两篇已处理候选补全 `search_text -> open_evidence`，再要求模型基于 E 编号收尾，避免安全拒答成为常见失败路径。

### Validation

- `.venv/bin/python -m pytest backend/tests`: passed, 54 tests.
- `npm run build`: passed.
- `.venv/bin/python scripts/performance_smoke.py --base-url http://127.0.0.1:8000 --requests 100 --workers 100 --threshold 3.0`: passed, 0 failures, p95 `0.9707s`, max `0.9746s`.
- `ENABLE_MOCK_LLM=false RUN_REAL_LLM_TESTS=1 .venv/bin/python scripts/real_agent_smoke.py`: passed with `gpt-5.5-medium`, 10 tool calls, 2 cited papers and HTML full text. URL/key came from an external local environment file and were never persisted here.
- Playwright desktop + 390px QA page: passed, no horizontal overflow, 0 console errors/warnings.
- Push 前真实前端复验：两篇真实 arXiv 论文均处理成功；QA 页面显示 `真实模型自主探索`、`探索完成`、7 次工具调用、3 条 HTML 正文证据、双论文引用与 86% 证据支持度。最终成功请求后无新增 console error。
- `.venv/bin/python -m compileall -q backend scripts`: passed.
- `git diff --check`: passed.

### Review

- 预审查由功能差距、bug/质量和架构/Memory 三个只读视角完成；确认旧 QA 是固定单轮 Top-K 而非 Agent，并复现 stale concepts、FTS 误关、空白输入与真实错误静默降级。
- 收尾正确性审查发现无效 citation 退化、工具预算截断导致未配对调用、空 scope 越权 snippet、stale concept edges 与宽松 ID；均已修复并加入回归测试。
- 收尾安全审查发现真实 smoke 接受 fallback、classic/process 吞 provider 错误、累计资源预算不足，以及 urllib 跨域 redirect 可能转发 Authorization；均已修复并复核关闭。
- 前端审查发现未打开搜索结果可能被显示为证据、fallback/failed 不可见和 mock trace 不一致；均已修复。桌面与移动端视觉复核无阻断。
- Push 前真实浏览器复验发现模型可能只查元数据后提前收尾；已增加确定性证据恢复路径、停止原因文案和回归测试。
- 最终三路复核确认没有 P0/P1；secret scan 未发现 key、Authorization 值或 provider body。

### Follow-ups

- 建立用户 Review + Memory 闭环，让反馈以可审计方式影响后续回答。
- 建立真实 arXiv QA/retrieval gold set，评估检索恢复、引用准确、步数、延迟和成本。
- 提升 HTML/PDF 章节、附录、表格、图注、公式和 citation 对齐能力。
- 将 Agent 软 deadline 改为严格剩余时间预算，并补 response-read 瞬态错误、Retry-After 和完整重试矩阵测试。
- 增加 Agent QA 的 Playwright 自动化和 SQLite 并发写 smoke。
