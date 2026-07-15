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

API Key 只从 `LLM_API_KEY` 环境变量读取。单篇论文 Chat 不使用 RAG：Docling 解析后的论文全文始终加入上下文，`LLM_CONTEXT_WINDOW` 只会裁剪当前分支的历史消息；若论文全文本身超过模型窗口，请改用更长上下文模型。

## 数据库 schema

当前 schema 不迁移旧版 `arxiv_id/file_path` 数据。启动时如果检测到旧版或不匹配的数据库，后端会明确拒绝启动；确认没有需要保留的数据后执行破坏性重建：

```powershell
.\.venv\Scripts\python.exe scripts\reset_database.py --database backend\data\arxiv_wiki.sqlite3 --apply
```

该命令会删除指定数据库及其 WAL/SHM 文件，并创建空的当前版本 schema。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
.\.venv\Scripts\python.exe scripts\performance_smoke.py
npm run build
```

## MVP 覆盖

- 论文自动抓取与管理：arXiv、USENIX、SIGOPS 与本地上传，按 `source + source_id` 去重
- 内容寻址存储：PDF 按 SHA-256 去重缓存，Docling 解析结果与源文件 hash 绑定
- 论文结构化解析：从已解析正文生成 summary、concepts、methods、experiments Wiki 内容
- 论文 Wiki 与检索：标题、作者、关键词、类别、概念标签和 Wiki 检索
- 智能问答：Agent 通过 FTS5 与语义重排搜索当前正文 Chunk，只允许引用已打开证据
- 单篇阅读工作台：PDF/解析文本/概要/笔记与 Chat 并排，支持消息编辑、重新生成、分支和服务端历史
- 学习管理：收藏、笔记、评论、阅读历史、关注主题和对比阅读
- 多 Agent：ReaderAgent、SummaryAgent、ValidatorAgent、QAAgent；默认为真实 agentic 模式，可显式选择 classic 单轮模式
- 进阶预留：研究脉络、订阅推荐、概念知识图谱

## 开发者包括：
柴英伦
王徽音
刘小菲
戴颀恩
丁宇轩
