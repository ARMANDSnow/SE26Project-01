# arXiv 智能论文阅读工具

面向科研论文学习场景的课程演示版 MVP。系统支持 arXiv 论文抓取、结构化 Wiki 沉淀、概念图谱、带出处问答，以及收藏、笔记、阅读历史等学习管理能力。

## 技术栈

- 前端：Vite + React + TypeScript
- 后端：FastAPI + SQLite
- 阅读工作台：assistant-ui + Docling
- 智能能力：兼容 OpenAI Chat Completions；默认使用 DeepSeek V4 Flash。未配置密钥时，结构化解析与问答会明确返回“LLM 未配置”。

## 快速启动

安装依赖：

```powershell
npm install
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

启动后端：

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

启动前端：

```bash
npm run dev
```

访问：

- 前端：http://127.0.0.1:5173
- 后端文档：http://127.0.0.1:8000/docs

## 环境变量

```dotenv
LLM_BASE_URL=https://api.deepseek.com
LLM_CHAT_MODEL=deepseek-v4-flash
LLM_API_KEY=your_api_key
LLM_CONTEXT_WINDOW=131072
LLM_MAX_OUTPUT_TOKENS=4096
ARXIV_DEFAULT_CATEGORIES=cs.AI,cs.CL,cs.LG
```

也可以将仅包含 API Key 的 `apikey.txt` 放在项目根目录；该文件已被 Git 忽略。环境变量 `LLM_API_KEY` 的优先级高于文件。单篇论文 Chat 不使用 RAG：Docling 解析后的论文全文始终加入上下文，`LLM_CONTEXT_WINDOW` 只会裁剪当前分支的历史消息；若论文全文本身超过模型窗口，请改用更长上下文模型。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
.\.venv\Scripts\python.exe scripts\performance_smoke.py
npm run build
```

## MVP 覆盖

- 论文自动抓取与管理：arXiv API、去重、分类、作者、时间、链接展示
- 论文结构化解析：生成 summary、concepts、methods、experiments Wiki 内容
- 论文 Wiki 与检索：标题、作者、关键词、类别、概念标签和 Wiki 检索
- 智能问答：基于 Wiki 片段检索，答案带论文出处
- 单篇阅读工作台：PDF/解析文本/概要/笔记与 Chat 并排，支持消息编辑、重新生成、分支和服务端历史
- 学习管理：收藏、笔记、评论、阅读历史、关注主题和对比阅读
- 多 Agent：FetcherAgent、ReaderAgent、SummaryAgent、ValidatorAgent、QAAgent
- 进阶预留：研究脉络、订阅推荐、概念知识图谱

## 开发者包括：
柴英伦
王徽音
刘小菲
戴颀恩
丁宇轩
