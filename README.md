# arXiv 智能论文阅读工具

面向科研论文学习场景的课程演示版 MVP。当前前端以 Chat 为入口，保留论文库、我的资料库和单篇论文阅读工作台；图谱、学习管理和旧版跨论文问答的一层页面已下线，但相关后端能力仍保留供后续 Agent 化改造使用。

## 技术栈

- 前端：Vite + React + TypeScript
- 后端：FastAPI + SQLite
- 阅读工作台：assistant-ui + Docling
- 智能能力：兼容 OpenAI Chat Completions；默认使用 DeepSeek V4 Flash。未配置密钥时，结构化解析与问答会明确返回“LLM 未配置”。

## 快速启动

安装依赖：

```powershell
npm ci
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
LLM_JSON_RESPONSE_FORMAT=true
LLM_CONTEXT_WINDOW=131072
LLM_MAX_OUTPUT_TOKENS=4096
ARXIV_DEFAULT_CATEGORIES=cs.AI,cs.CL,cs.LG
SESSION_COOKIE_NAME=paperwiki_session
SESSION_TTL_SECONDS=604800
SESSION_COOKIE_SECURE=false
```

API Key 只从 `LLM_API_KEY` 环境变量读取。登录 Session 默认保存在当前后端进程内存中，有效期为 7 天；进程重启会要求重新登录，多 worker/多实例部署前应将 `SessionStore` 替换为 Redis。生产 HTTPS 环境应设置 `SESSION_COOKIE_SECURE=true`。

主页 Chat 支持“自动判断 / 普通对话 / 深度研究”三种模式。普通 Chat 仍只发送系统提示和当前对话分支历史；深度研究会原子创建十步 `topic` Run，真实执行 ResearchBrief、检索、去重导入、筛选、全文准备、证据阅读和 PaperBrief 抽取，并把步骤、论文、Artifact、工具摘要与预算持久化到数据库。缺少真实模型配置时会明确失败为 configuration unavailable，不会生成伪调研数据。standalone `/api/research/runs` 仍保留确定性三步 Harness 作为可测试骨架。单篇论文 Chat 不进入 Research Route。

## 数据库 schema

当前 schema version 7 支持 v2→v3→v4→v5→v6→v7 连续迁移。v5 新增 Research Run、Step、Event 和 Decision；v6 为 Chat 增加受控 `content_parts_json`；v7 新增版本化 `research_artifacts` 和 owner-scoped `research_run_papers`，PaperBrief 与当前 PDF/Docling/Chunk source hash 绑定。租约 generation 与每次副作用前后的 fencing 用于阻止过期 worker 覆盖新 attempt。更早的 `arxiv_id/file_path` v0 schema不提供自动迁移；不得在未备份或未确认归属时重建这类用户数据库。开发新功能可显式设置独立 `DATABASE_PATH`。只有确认没有需要保留的数据后，才执行破坏性重建：

```powershell
.\.venv\Scripts\python.exe scripts\reset_database.py --database backend\data\arxiv_wiki.sqlite3 --apply
```

该命令会删除指定数据库及其 WAL/SHM 文件，并创建空的当前版本 schema。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe scripts\performance_smoke.py
npm run build
npm run test:e2e
```

已配置真实 DeepSeek Key 时，可显式运行一次最小付费 Chat smoke：

```powershell
$env:RUN_REAL_LLM_TESTS="true"
.\.venv\Scripts\python.exe scripts\real_chat_smoke.py
```

真实 topic research smoke 需在启动后端前配置 `LLM_API_KEY`；使用非默认兼容服务时同时设置 `LLM_BASE_URL` 和 `LLM_CHAT_MODEL`，重启后端后在主页显式选择“深度研究”。`LLM_BASE_URL` 应指向 API 前缀（常见为以 `/v1` 结尾），客户端会追加 `/chat/completions`。若 provider 不支持 OpenAI 的 `response_format=json_object`，还需显式设置 `LLM_JSON_RESPONSE_FORMAT=false`；本地仍会用提示中的完整 JSON Schema 和 strict Pydantic 校验 fail closed，且不会在一个预算槽内暗中重试第二次模型调用。该流程会调用真实模型、arXiv 和可能的 PDF/Docling，运行前应确认费用与默认 50/12/40/100/30 分钟预算。

## 后端结构

FastAPI 后端按 `api -> services -> repositories -> db` 分层；认证依赖从内存 Session 解析当前用户，业务层不信任客户端用户 ID。`main.py` 仅负责应用装配。详细职责、事务边界和兼容策略见 [`backend/app/ARCHITECTURE.md`](backend/app/ARCHITECTURE.md)。

## MVP 覆盖

- 论文自动抓取与管理：arXiv、USENIX、SIGOPS 与本地上传，按 `source + source_id` 去重
- 内容寻址存储：PDF 按 SHA-256 去重缓存，Docling 解析结果与源文件 hash 绑定
- 论文结构化解析：从已解析正文生成 summary、concepts、methods、experiments Wiki 内容
- 论文 Wiki 与检索：标题、作者、关键词、类别、概念标签和 Wiki 检索
- 主页通用 Chat：真实模型多轮对话，只携带当前消息树分支，支持服务端持久化、编辑、重新生成、分支切换和显式 Fork；`/api/chat/route` 保守区分普通 Chat 与 Research Run
- Research Workflow：Chat 以 assistant-ui 原生 `research-run` data part 持久化 topic Run 卡片；共享 Workflow 展示 ResearchBrief、候选/入选/排除、全文阶段、真实预算、工具摘要和 PaperBrief，并支持安全暂停、继续、二次确认停止、重试、Budget Decision 和 SSE 续传；standalone Harness 继续运行确定性三步骨架
- 单篇阅读工作台：PDF/解析文本/概要/笔记与 Chat 并排，支持消息编辑、重新生成、分支和服务端历史
- 后端跨论文问答：Agent 通过 FTS5 与语义重排搜索当前正文 Chunk，只允许引用已打开证据；当前无独立前端入口
- 学习管理：收藏、笔记、评论、阅读历史、关注主题和对比阅读
- 多 Agent：ReaderAgent、SummaryAgent、ValidatorAgent、QAAgent；默认为真实 agentic 模式，可显式选择 classic 单轮模式
- 进阶预留：研究脉络、订阅推荐、概念知识图谱

## 产品规划

- Agentic Research 产品文档、Workflow UX/UI 规格与重构路线图：[docs/product/README.md](docs/product/README.md)

## 开发者包括：
柴英伦
王徽音
刘小菲
戴颀恩
丁宇轩
