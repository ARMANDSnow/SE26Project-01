# Research Quality Evaluation

本目录保存离线、版本化的 Citation entailment 与 coverage 验收证据，不读取默认用户数据库，也不接入生产 Citation Validator。

`reports/rag_citation_entailment_v1_validation.{json,md}` 是可复算的未验证质量报告；`reports/iter16_authenticated_performance_smoke.json` 保存隔离认证性能结果。

## Dataset v1

`gold/rag_citation_entailment_v1.jsonl` 固定为 60 个审定案例，标签 `supported / contradicted / insufficient` 各 20 条。案例来自 5 篇 2023 年以来的公开 RAG 论文：

- [RAGAS](https://arxiv.org/abs/2309.15217)
- [Self-RAG](https://arxiv.org/abs/2310.11511)
- [Corrective Retrieval Augmented Generation](https://arxiv.org/abs/2401.15884)
- [RAPTOR](https://arxiv.org/abs/2401.18059)
- [RAGChecker](https://arxiv.org/abs/2408.08067)

Evidence 使用针对公开 abstract metadata 的短 curator summary，不保存本地数据库 ID、私有正文或用户数据。每条案例保存稳定 ID、公开论文身份、Artifact 类型、exact fact statement、Evidence、章节/段落 locator、SHA-256、预期标签和标注说明。`scripts/build_research_quality_gold.py` 只用于确定性重建这份版本化 fixture；提交前必须由审定者检查生成 diff，不能把任意模型输出直接标成 adjudicated。

Coverage 的语义单位固定为：报告/矩阵事实语句、Cluster 摘要与区分特征、非 publication 时间线事件/阶段/转折点、Graph 语义边。publication 元数据和 `contains/precedes` 等确定性关系通过 `deterministic_relation` 单独计数，不伪装为语义 Citation。v1 中 50 个语义单位均带 Citation，10 个 publication/确定性关系单列。

## Metrics

- confusion matrix 按 `expected_label → predicted_label` 统计；
- macro-F1 是三类 F1 的算术平均；
- supported precision 是预测为 supported 的案例中真实 supported 的比例；
- false-accept rate 是预测为 supported 的案例中真实 contradicted/insufficient 的比例；
- coverage 是 `citation_present / coverage_required`，并按 Artifact 分项；
- 默认通过条件要求 macro-F1、supported precision 和 coverage 同时 `>= 0.90`。

`>90%` 只对应该固定 gold set 上明确命名的指标。仓库中的 validation report 仅证明 schema、hash、分布与报告生成可复现；未运行真实 judge，因此明确显示“未验证”，不能用于宣称模型质量已达标。

## CLI

仅校验数据并生成“未验证”报告：

```bash
.venv/bin/python scripts/evaluate_research_quality.py \
  --dataset evaluation/gold/rag_citation_entailment_v1.jsonl \
  --output-json evaluation/reports/rag_citation_entailment_v1_validation.json \
  --output-markdown evaluation/reports/rag_citation_entailment_v1_validation.md \
  --threshold 0.90
```

确定性评分已有 prediction 文件：

```bash
.venv/bin/python scripts/evaluate_research_quality.py \
  --dataset evaluation/gold/rag_citation_entailment_v1.jsonl \
  --predictions /path/to/predictions.jsonl \
  --output-json /tmp/research-quality.json \
  --output-markdown /tmp/research-quality.md \
  --threshold 0.90
```

Prediction 必须逐条使用 `case_id + predicted_label`；缺失、重复、未知案例、未知标签和未知字段均直接失败。

真实 judge 只在获得单独付费授权后运行 `--use-llm`。该模式复用当前 OpenAI-compatible 配置，每个案例最多一次 provider 请求，不隐藏重试；缺少配置、provider 失败、case ID/schema 不匹配或敏感输出均 fail closed。报告只记录模型名、dataset/evaluator/prompt hash，不记录 API Key、Authorization、provider body 或绝对路径。
