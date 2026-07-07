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
```

`ENABLE_MOCK_LLM=true` 时系统使用本地规则生成摘要、概念、方法和问答结果。没有 API Key 时也会自动走 mock 路径。

## 测试

```bash
.venv/bin/python -m pytest backend/tests
.venv/bin/python scripts/performance_smoke.py
npm run build
```

## MVP 覆盖

- 论文自动抓取与管理：arXiv API、去重、分类、作者、时间、链接展示
- 论文结构化解析：生成 summary、concepts、methods、experiments Wiki 内容
- 论文 Wiki 与检索：标题、作者、关键词、类别、概念标签和 Wiki 检索
- 智能问答：基于 Wiki 片段检索，答案带论文出处
- 学习管理：收藏、笔记、评论、阅读历史、关注主题和对比阅读
- 多 Agent：FetcherAgent、ReaderAgent、SummaryAgent、ValidatorAgent、QAAgent
- 进阶预留：研究脉络、订阅推荐、概念知识图谱

## 开发者包括：
柴英伦 戴颀恩