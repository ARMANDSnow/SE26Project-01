# Iteration iter07 - 通用持久化 Chat 基础

## Context

产品入口将从传统功能仪表盘调整为以对话为中心的研究界面。用户确认删除仪表盘、知识图谱和学习管理三个一级页面，保留论文库、我的资料库和单篇论文页面，并将原“智能问答”改造成基于 assistant-ui 的大型 Chatbox。

本轮先建立不含 Agent 能力的通用 Chat：只向真实模型提供系统提示词和当前对话分支的用户/助手历史，不注入论文、资料库、文件、工具或联网搜索上下文。现有单篇论文 Chat 组件和消息树能力应尽量复用。

## Goals

- 将 `/` 改为通用 Chat，移除仪表盘、知识图谱、学习管理和独立 QA 的一级入口。
- 为 `paper_id = NULL` 的通用线程提供服务端创建、列表、持久消息和流式运行。
- 后端按当前消息树分支重建历史并调用真实 OpenAI 兼容模型。
- 抽取可复用的 assistant-ui 消息、Composer、History 和流式适配逻辑。
- 支持编辑、重新生成、分支切换和显式“从这里分叉”，并持久化当前 head。
- 保持单篇论文 Chat 行为及论文库、资料库、论文详情页可用。

## Scope

- FastAPI 通用线程 API、对话上下文构造和运行契约校验。
- React 路由、导航、通用 Chat 页面和共享 assistant-ui 组件。
- 通用 Chat 与单篇论文 Chat 的分支持久化修复。
- 后端回归测试、前端构建和文档更新。

不包含：论文上下文注入、跨论文 QA、Agent 工具、联网搜索、工作区文件系统、知识图谱工具和隐私污点追踪。

## Acceptance Criteria

- `/` 首屏为大型 Chatbox；旧 `/qa`、`/graph`、`/learning` 不再作为独立页面展示。
- 通用线程刷新后仍可加载，多个线程之间消息不串线。
- 通用 Chat 发给模型的上下文只包含系统提示和当前分支历史。
- 普通追加、编辑、重新生成使用一致且可验证的消息树契约。
- 用户可显式从一条消息继续新问题形成分支；分支选择器可切换并在刷新后保留选择。
- 单篇论文 Chat 仍使用完整解析正文，且重新生成不重复插入已有用户消息。
- 后端测试、mypy、前端 build 和 `git diff --check` 通过。

## Plan

1. 建立通用线程列表/创建 API，并为无论文线程构造纯对话模型上下文。
2. 收紧 append/edit/regenerate 请求语义和分支 head 持久化。
3. 抽取共享 assistant-ui Chat 组件和运行适配器。
4. 重构首页、路由与侧栏，接入服务端通用线程。
5. 补充回归测试并完成验证、closeout、handoff 与提交。

## Risks And Questions

- 通用 Chat 会调用真实模型；自动测试必须使用替身，真实付费 smoke 只在显式环境配置下运行。
- assistant-ui LocalRuntime 负责本地消息树，后端负责权威持久化；两者的 message ID、parent ID 和 active head 必须保持一致。
- 本轮移除的是前端一级页面，不删除现有图谱、学习管理或跨论文 QA 后端接口。

## Progress Notes

- 2026-07-15：`codex/develop` fast-forward 到 iter06，并创建 `codex/general-chat-foundation`。
- 2026-07-15：确认 assistant-ui 0.14.26 原生支持编辑/重新生成分支；现有客户端的 regenerate 请求和 head 持久化尚未正确接线。
- 2026-07-15：通用线程 API、纯对话上下文、共享 assistant-ui Chat、精简路由和显式 Fork 已实现。
- 2026-07-15：浏览器验收覆盖主 Chatbox、自动创建线程、精简导航、模型失败态和 Fork 控件。
- 2026-07-15：完整测试、mypy、生产构建和真实 DeepSeek 最小 smoke 均通过。

## Closeout

### Summary

- `/` 现在是大尺寸通用 Chatbox；删除仪表盘、图谱、学习管理和旧 QA 前端页面并保留兼容重定向。
- 新增 `paper_id = NULL` 通用线程创建/列表 API，沿当前消息树分支构造纯对话模型上下文并使用既有 SSE 运行链路持久化。
- 抽取共享 assistant-ui Chat 组件供主页和单篇论文复用，修正 regenerate 语义与 active head 持久化。
- 增加显式 Fork composer，同时保留编辑分叉、重新生成分支和分支选择器。
- 增加 `scripts/real_chat_smoke.py`，在显式开关下执行一次最小真实模型调用。

### Validation

- `pytest backend/tests`：59 passed。
- `python -m mypy`：通过。
- `npm run build`：通过；保留现有约 909 kB bundle 警告。
- 本地浏览器 QA：通过。
- `RUN_REAL_LLM_TESTS=true python scripts/real_chat_smoke.py`：`deepseek-v4-flash` 通过。
- `git diff --check -- . ':!UIPrototype/**'`：通过。

### Review

主 agent 完成本地只读差异、契约与安全审查；依照仓库规则，本轮未在用户未授权的情况下调用 subagent。未发现密钥写入、论文上下文误注入通用 Chat 或消息 ID 覆盖路径。

### Follow-ups

- 增加线程重命名、删除/归档和自动标题。
- 增加 Playwright 自动化分支回归。
- 设计后续 Agent 会话状态与显式上下文授权。
- 对 assistant-ui 和页面路由进行代码分割。
