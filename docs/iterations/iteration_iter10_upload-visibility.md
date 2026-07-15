# Iteration iter10 - 用户上传归属与可见性

## Context

iter09 已实现登录和用户虚拟数据隔离，但上传接口只创建全局 `papers` 记录，没有保存上传者与可见性。结果是上传虽然要求登录，上传内容仍会被所有用户列出，也可通过 paper ID、PDF、搜索、QA 或 Chat 间接读取。

## Goals

- 保持 `papers` 作为论文全局身份与派生知识根节点，不把公共论文改造成用户私有副本。
- 新增独立 `paper_uploads` 记录上传 owner、visibility、provenance、moderation status 与原始文件名。
- 新上传默认 private；用户可显式选择 public，并可由所有登录用户读取。
- 将统一访问谓词贯穿目录、详情、PDF、Chunk、处理、解析、概要、资料库、Chat、Wiki 搜索、图谱、classic QA 与 agentic QA。
- 将历史上传迁移为 legacy public/approved，以保持升级前可见行为并明确其来源。

## Scope

- schema v4 与 v3→v4 migration。
- `repositories/uploads.py` 统一归属、元数据与访问检查。
- 上传 API 的 visibility 表单字段，以及 owner 修改 visibility 的 API。
- 前端上传可见性选择和论文响应中的 upload 元数据。
- 跨用户直接 URL、搜索、QA、Chat 和资料库绕过测试。

不包含：管理员审核界面、恶意内容扫描、分享链接、团队空间、对象存储 ACL、删除上传。

## Acceptance Criteria

- 私有上传只有 owner 能在任何读取路径访问；非 owner 获得 404 或空搜索结果，不泄露存在性。
- 公开上传对所有已登录用户可见；只有 owner 能修改 visibility。
- arXiv/USENIX/SIGOPS 等来源论文继续对所有登录用户共享。
- 上传响应包含 owner/visibility/provenance/moderation 元数据，不暴露其他用户敏感信息。
- v3 数据库自动迁移到 v4，已有 `source='upload'` 论文保持公开可见并标记 legacy。
- 后端测试、strict mypy、前端生产构建和差异检查通过。

## Plan

1. 增加 schema v4 migration 与上传 Repository。
2. 在论文响应和所有直接读取入口接入访问检查。
3. 贯穿搜索、图谱、QA Agent、Chat 和资料库间接读取链路。
4. 增加上传 visibility API 与前端选择。
5. 增加跨用户与迁移回归测试，完成验证和 closeout。

## Risks And Questions

- visibility 从 public 改为 private 后，其他用户可能仍有历史收藏、笔记或 Chat；这些记录保留但必须立即不可读，重新公开后可恢复。
- 公开上传目前只记录 moderation 状态，不提供管理员工作流；用户显式公开后立即可见，未来可把 rejected 状态纳入下架流程。
- 物理 PDF 仍按内容 hash 去重；逻辑权限必须绑定 paper/upload 记录，不能因 blob 相同而合并访问权。

## Progress Notes

- 2026-07-15：完成 iter-start 盘点；确认 papers 列表之外还存在 PDF、Chunk、解析、概要、Chat、Wiki、Graph、QA 与资料库间接读取路径。
- 2026-07-15：确定使用 `papers` 全局身份 + `paper_uploads` 授权元数据；新上传默认 private，显式 public 立即共享，历史上传迁移为 legacy public/approved。
- 2026-07-15：完成 schema v4、统一可访问谓词、owner-only visibility 修改接口和前端上传可见性选择。
- 2026-07-15：访问控制已覆盖目录/详情/PDF/Chunk/处理/解析/概要、收藏/目录/历史、论文 Chat、Wiki/FTS/Graph、classic QA、agentic QA 与论文工具箱；上传元数据缺失时采用 fail-closed。
- 2026-07-15：合并后审查修复 Session 失效时的旧用户前端缓存视图，并让匿名 health 计数排除私有上传；README 与架构文档同步 schema v4。

## Closeout

### Summary

- 新增 `paper_uploads`，将全局论文身份与上传授权元数据分离；记录 owner、private/public、user/legacy provenance、moderation status 与原始文件名。
- 新上传默认 private，可在上传时显式 public；owner 可通过 `PATCH /api/papers/{paper_id}/visibility` 修改，非 owner 统一获得 404。
- v3→v4 自动迁移将历史 `source='upload'` 记录标记为 legacy public/approved；非上传来源继续全局共享。
- 私有上传访问谓词贯穿所有已识别的直接和间接读取路径；public→private 后，其他用户已有收藏、历史与论文 Chat 数据保留但立即隐藏。
- 前端上传表单增加“私有上传/公开上传”选择，API 与 TypeScript 类型同步 upload 元数据。

### Validation

- `.\.venv\Scripts\python.exe -m pytest backend/tests`：70 passed。
- `.\.venv\Scripts\python.exe -m mypy`：45 个源文件无问题。
- `npm run build`：通过；Vite 仍提示既有约 913 kB 主包拆分建议。
- `git diff --check`：通过。

### Review

- 回归覆盖 v3→v4 legacy 迁移、默认私有上传、owner 发布/收回、非 owner 直接 URL 与 PDF 绕过、收藏/目录/历史/Chat 遗留记录隐藏，以及 Wiki、Graph、QA、PaperToolbox 间接泄露。
- 静态读取路径审查后，将缺失 `paper_uploads` 元数据的 upload 改为 fail-closed，并补充独立测试。
- PR 前审查后补充 Session 失效 UI 退回认证页、跨账号登录前清空旧用户查询缓存，以及 health 仅统计公开论文的防护。
- 未运行真实付费 LLM smoke；visibility 相关 LLM 路径通过访问前置检查和 mock/API 回归验证。

### Follow-ups

- moderation 目前只有状态模型，没有管理员审核、内容扫描或举报/下架界面；显式 public 的上传立即对登录用户可见。
- 尚未实现分享链接、团队 ACL、上传删除与对象存储级 ACL。
- 建议增加 Playwright 跨账户 smoke，覆盖上传、公开、收回和旧视图失效。
