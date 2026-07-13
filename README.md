# arXiv 智能论文阅读工具

面向科研论文学习场景的课程演示版 MVP。系统支持 arXiv 论文抓取、结构化 Wiki 沉淀、概念图谱、带出处问答，以及收藏、笔记、阅读历史等学习管理能力。

## 技术栈

- 前端：Vite + React + TypeScript
- 后端：FastAPI + SQLite
- 智能能力：OpenAI 兼容接口，可通过环境变量配置；默认启用 mock LLM，保证离线可演示

## 快速启动

安装依赖：

```bash
npm install
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

启动后端：

```bash
.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000
```

启动前端：

```bash
npm run dev
```

访问：

- 前端：http://127.0.0.1:5173
- 后端文档：http://127.0.0.1:8000/docs

## 环境变量

```bash
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_api_key
LLM_CHAT_MODEL=gpt-4o-mini
LLM_EMBED_MODEL=text-embedding-3-small
ARXIV_DEFAULT_CATEGORIES=cs.AI,cs.CL,cs.LG
ENABLE_MOCK_LLM=true
ENABLE_FULLTEXT_FETCH=auto
VITE_USE_MOCK=false
```

`ENABLE_MOCK_LLM=true` 时系统使用本地规则生成摘要、概念、方法和问答结果。没有 API Key 时也会自动走 mock 路径。
`ENABLE_FULLTEXT_FETCH=auto` 时，mock/offline 路径默认使用元数据片段，真实 LLM 路径会尝试抓取 arXiv HTML/PDF 正文；可显式设置为 `true` 或 `false`。
`VITE_USE_MOCK=true` 时前端直接使用内置样例数据；默认关闭，以便后端错误能进入页面错误态。

密钥只应通过进程环境变量注入。仓库会忽略 `.env`/`.env.*`，并提供不含密钥的 `.env.example`；应用本身不会自动加载 `.env`。

当前 `LLM_CHAT_MODEL` 用于真实论文结构化与 Agent 问答。`LLM_EMBED_MODEL` 客户端已预留，但现有索引仍使用可离线复现的 deterministic embedding；在完成向量维度迁移和真实评测前，不把它描述为已启用的真实语义检索。

## 测试

```bash
.venv/bin/python -m pytest backend/tests
.venv/bin/python scripts/performance_smoke.py
npm run build
```

真实模型的跨论文 Agent smoke 是显式 opt-in，会产生 API 调用并访问 arXiv：

```bash
ENABLE_MOCK_LLM=false RUN_REAL_LLM_TESTS=1 .venv/bin/python scripts/real_agent_smoke.py
```

脚本从环境读取 `LLM_API_KEY`，不会打印 key、Authorization header、原始 provider 响应或论文答案。它只有在真实模型完成多轮工具调用、引用两篇论文且至少一篇取得 HTML/PDF 正文时才通过；缺 key 不会静默回退。

## Agent 工作流

- Agent 入口规则：[AGENTS.md](AGENTS.md)
- 当前状态交接：[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md)
- 迭代记录：[docs/iterations/README.md](docs/iterations/README.md)

## MVP 覆盖

- 论文自动抓取与管理：arXiv API、去重、分类、作者、时间、链接展示
- 论文结构化解析：生成 summary、concepts、methods、experiments Wiki 内容，并建立可追溯 chunks
- 论文 Wiki 与检索：标题、作者、关键词、类别、概念标签、Wiki 和 chunk 检索
- 智能问答：Agent 可自主调用元数据搜索、全文搜索和证据打开工具，进行跨论文多轮探索；只有实际打开的证据可进入引用
- 学习管理：收藏、笔记、评论、阅读历史、关注主题和对比阅读
- Agent 工作流：论文处理使用 ReaderAgent、SummaryAgent、ValidatorAgent；问答使用带预算和引用白名单的 QAAgent 工具循环
- 进阶预留：研究脉络、订阅推荐、概念知识图谱

## 开发者包括：
柴英伦
王徽音
刘小菲
戴颀恩
丁宇轩
