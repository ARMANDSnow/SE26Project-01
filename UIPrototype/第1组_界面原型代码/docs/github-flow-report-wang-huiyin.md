# GitHub Flow 实践报告

## 1. 基本信息

- 姓名：王徽音
- 仓库地址：https://github.com/ARMANDSnow/SE26Project-arxiv-paper-reading-tool
- feature 分支：`docs/add-wang-huiyin`
- PR 标题：`Add Wang Huiyin to developer list`
- 修改类型：文档修改

## 2. 本次修改内容

本次在 feature 分支上完成了一次简单的文档贡献：在 `README.md` 的“开发者包括”部分，将“王徽音”添加到“柴英伦”之后。

该修改用于练习 GitHub Flow 的完整协作流程，包括同步远程仓库、创建 feature 分支、提交 commit、推送远程分支、创建 Pull Request、指定 reviewer、合并 PR，以及删除 feature 分支。

## 3. GitHub Flow 操作过程

### 3.1 同步远程仓库

先切换到 `main` 分支，并获取远程最新版本：

```bash
git checkout main
git fetch --all --prune
git pull --ff-only origin main
```

### 3.2 创建并切换 feature 分支

```bash
git checkout -b docs/add-wang-huiyin
```

### 3.3 在 feature 分支上修改文档

修改 `README.md`，在“开发者包括”列表中新增：

```text
王徽音
```

同时新增本报告文档：

```text
docs/github-flow-report-wang-huiyin.md
```

### 3.4 提交更改

```bash
git add README.md docs/github-flow-report-wang-huiyin.md
git commit -m "Add Wang Huiyin to developer list"
```

### 3.5 推送 feature 分支

```bash
git push origin docs/add-wang-huiyin
```

### 3.6 创建 Pull Request

在 GitHub 上创建 Pull Request：

- base 分支：`main`
- compare 分支：`docs/add-wang-huiyin`
- PR 标题：`Add Wang Huiyin to developer list`
- reviewer：指定小组其他成员

### 3.7 Review 与合并

等待 reviewer 审查通过后，将 PR 合并到 `main` 分支。

### 3.8 删除 feature 分支

PR 合并后，删除本地和远程 feature 分支：

```bash
git checkout main
git pull origin main
git branch -d docs/add-wang-huiyin
git push origin --delete docs/add-wang-huiyin
```

## 4. 验证方式

本次修改只涉及 Markdown 文档，不影响前端或后端运行逻辑。

已检查内容：

- `README.md` 中开发者名单已包含“王徽音”。
- 新增实践报告文档路径为 `docs/github-flow-report-wang-huiyin.md`。
- Git 工作区在提交前仅包含本次文档相关修改。

## 5. 截图记录

提交作业时请补充以下截图：

- PR 页面截图
- reviewer 审查截图
- PR 合并成功截图
- `git log --oneline --graph --decorate --all` 命令截图

推荐截图命令：

```bash
git log --oneline --graph --decorate --all
```
