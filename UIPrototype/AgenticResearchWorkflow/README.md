# PaperWiki Agentic Research Workflow 原型

这是一个独立的高保真前端设计原型，用于评审 Chat + Workflow 的产品方向。它不连接后端，不会进入正式 Vite 构建，也不会向生产页面注入假数据。

## 打开方式

在仓库根目录运行：

```bash
python3 -m http.server 4173 --directory UIPrototype/AgenticResearchWorkflow
```

然后访问：<http://127.0.0.1:4173/>

## 可交互内容

- 展开/收起 Workflow 步骤；
- 暂停和继续模拟 Research Run；
- 打开任务中心；
- 回答“需要确认”的关键问题；
- 打开命令面板；
- 切换浅色/深色主题；
- 在 Chat 输入框补充调研要求；
- 桌面三栏、平板 Workflow 抽屉和移动端单栏布局。

## 文件

- `index.html`：语义化页面结构和模拟数据；
- `styles.css`：沿用 PaperWiki 暖色体系的设计 token、组件和响应式；
- `app.js`：纯前端交互状态。

## 产品边界

原型中的进度、论文数量和工具调用均为界面演示数据。正式实现必须绑定真实 `Research Run`、`Step`、`Event`、`Decision` 和 `Artifact`，不得使用前端计时器伪造执行进度。
