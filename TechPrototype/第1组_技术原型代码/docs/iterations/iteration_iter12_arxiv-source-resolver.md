# Iteration iter12 - arXiv 结构化源解析优先

## Context

iter11 已确认重复全文解析慢的主要原因是重复跑 Docling，并通过缓存短路解决了同一 PDF 的重复解析问题。首次解析仍然慢，真实计时显示 PDF 下载约 1-2 秒，而 Docling/PDF 版面解析约 26 秒以上。为了降低首次解析成本，本轮尝试为 arXiv 论文增加结构化源解析路径：优先下载 arXiv e-print LaTeX 源并转 Markdown，失败时再 fallback 到现有 PDF + Docling。

## Goals

- arXiv 来源论文优先尝试 LaTeX source resolver。
- 结构化源解析失败时保留现有 PDF fallback。
- 已解析的 arXiv LaTeX 文档可继续命中缓存，不重复下载源文件。
- 跑真实论文实验，对比 LaTeX resolver 与 PDF Docling 的耗时。

## Scope

- `backend/app/services/arxiv_source.py`
- `backend/app/services/documents.py`
- `backend/app/services/agents.py`
- `backend/tests/test_core.py`
- `pyproject.toml`
- `docs/iterations/README.md`
- `docs/AGENT_HANDOFF.md`

## Acceptance Criteria

- arXiv 论文能通过 e-print LaTeX 源生成 Markdown 和 chunks。
- 非 arXiv 或 LaTeX 源不可用时仍可走 PDF Docling。
- arXiv LaTeX 缓存命中时不触发源下载或 PDF 解析。
- 后端测试覆盖 resolver 优先级和基础 LaTeX 转 Markdown。
- 给出真实论文速度对比结果。

## Plan

1. 增加 arXiv e-print 下载、TeX 包解析、main tex 选择、`\input` 展开和基础 LaTeX 到 Markdown 转换。
2. 在 `parse_paper_document()` 中接入 `arxiv_latex -> pdf/docling` 优先级。
3. 同步 agent 的 expected source hash 判断。
4. 补单测并运行验证。
5. 用真实 arXiv 论文计时比较。

## Risks And Questions

- LaTeX 到 Markdown 当前是轻量转换，不等价于完整 TeX 编译；复杂宏、表格、算法环境和自定义命令可能损失格式。
- arXiv e-print 源可能是单文件、gzip、tar 包，或不存在/受限；需要保留 PDF fallback。
- source cache key 以 arXiv id、updated_at 和 resolver 版本生成；如果 versionless arXiv id 指向更新版本但元数据未更新，可能需要手动重解析。

## Progress Notes

- 2026-07-16：iter-start，开始实现 arXiv LaTeX source resolver 与 PDF fallback。
- 2026-07-16：完成 arXiv e-print 下载、TeX 包解析、main tex 选择、`\input` 展开和基础 LaTeX -> Markdown 转换。
- 2026-07-16：接入解析优先级：arXiv LaTeX cache -> arXiv LaTeX source -> PDF cache -> PDF Docling fallback。
- 2026-07-16：真实论文 `1706.03762` 实验中，LaTeX resolver 2.260s，强制 PDF Docling 34.961s，约 15.47x 加速。

## Closeout

### Summary

- 新增 `backend/app/services/arxiv_source.py`，支持从 `https://arxiv.org/e-print/{source_id}` 下载 arXiv 源包，解析 tar/gzip/单 TeX 文件，选择主 `.tex`，展开 `\input`/`\include`，并转换为 Markdown。
- `parse_paper_document()` 现在对 arXiv 论文优先尝试结构化源；源解析不可用或失败时保留现有 PDF Docling fallback。
- 缓存优先级调整为 arXiv LaTeX cache -> arXiv LaTeX source -> PDF cache -> PDF Docling，避免已有 PDF 缓存阻止后续结构化源解析。
- `process_paper()` 的 expected source hash 同步支持 arXiv LaTeX source key，避免把已完成的 LaTeX 解析误判为过期。

### Experiment

真实论文：`1706.03762`，Attention Is All You Need。

| Path | Time | Parser | Markdown chars | Tokens | Chunks |
| --- | ---: | --- | ---: | ---: | ---: |
| arXiv e-print LaTeX source | 2.260s | `arxiv_latex` | 42,924 | 10,733 | 42 |
| forced PDF Docling fallback | 34.961s | `docling` | 47,205 | 11,867 | 39 |
| arXiv LaTeX cache hit | 0.000882s | `arxiv_latex` | 42,924 | - | - |

本次样本中，结构化源路径比 PDF Docling 快约 15.47x，节省约 32.701s。

### Validation

- `.\.venv\Scripts\python.exe -m pytest backend\tests`：73 passed。
- `.\.venv\Scripts\python.exe -m mypy --no-incremental`：Success, 46 source files。
- `npm run build`：通过；Vite 仍提示既有主 bundle 超过 500 kB。
- `git diff --check`：通过，仅有 Windows 行尾提示。

### Review

- resolver 只对 `source == arxiv` 的论文启用，其他来源仍走 PDF 路径。
- arXiv source 下载使用可信 HTTPS host 白名单，不解压到文件系统，tar 包只读取 `.tex` 成员。
- 当前 LaTeX 转 Markdown 是轻量文本转换，不等价于完整 TeX 编译；复杂宏、表格、算法和图注仍可能不如 PDF/HTML 渲染完整。

### Follow-ups

- 对更多 arXiv 论文做样本集评估，统计 source 可用率、解析失败率和文本质量。
- 增加 HTML resolver，例如 ar5iv/official HTML 来源，并比较 HTML 与 LaTeX 的质量。
- 将解析任务后台化，避免首次解析阻塞 HTTP 请求。
