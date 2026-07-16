import { expect, test, type Page } from "@playwright/test"

async function register(page: Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "没有账户？创建账户" }).click()
  await page.getByLabel("用户名").fill(`e2e_${Date.now()}_${Math.floor(Math.random() * 10000)}`)
  await page.getByLabel("密码").fill("playwright-password")
  await page.getByRole("button", { name: "注册并登录" }).click()
  await expect(page.getByRole("button", { name: "打开任务中心" })).toBeVisible()
  await expect(page.getByPlaceholder("输入问题，Enter 发送…")).toBeVisible()
}

test("routes deep research into a persisted data card and responsive workflow", async ({ page }, testInfo) => {
  const errors: string[] = []
  await register(page)
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (message) => { if (message.type() === "error") errors.push(message.text()) })

  if (testInfo.project.name === "mobile-390") {
    for (const target of [page.getByLabel("回答模式"), page.getByRole("button", { name: "发送" })]) {
      expect((await target.boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
    }
  }

  const taskTrigger = page.getByRole("button", { name: "打开任务中心" })
  await taskTrigger.focus()
  await taskTrigger.click()
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible()
  await expect(page.getByText("新建 Harness 骨架")).toHaveCount(0)
  await page.keyboard.press("Escape")
  await expect(taskTrigger).toBeFocused()

  await page.getByLabel("回答模式").selectOption("deep_research")
  const title = `Playwright Harness ${testInfo.project.name}`
  await page.getByPlaceholder("输入问题，Enter 发送…").fill(`${title}\n验证刷新恢复与三步工作流`)
  await page.getByRole("button", { name: "发送" }).click()
  const card = page.getByRole("region", { name: new RegExp(title) })
  await expect(card).toBeVisible()
  await expect(card.getByText("真实三步骨架", { exact: false })).toBeVisible()
  const openButton = card.getByRole("button", { name: "查看 Workflow" })
  await openButton.focus()
  await openButton.click()
  await expect(page).toHaveURL(/\?thread=.*&run=/)
  let workflow = testInfo.project.name === "desktop-1440" ? page.locator("aside:visible") : page.locator('[role="dialog"]:visible')
  await expect(workflow.getByRole("heading", { name: title })).toBeVisible()
  await expect(workflow.getByText("当前为 Harness 骨架。", { exact: false })).toBeVisible()
  const firstStep = workflow.getByRole("button", { name: /规范化任务/ })
  await expect(firstStep).toBeVisible()
  if (await firstStep.getAttribute("aria-expanded") !== "true") await firstStep.click()
  await expect(workflow.getByText("Harness 骨架输出；未执行论文检索、导入或模型研究。")).toBeVisible()

  if (testInfo.project.name !== "desktop-1440") {
    const close = page.getByRole("button", { name: "关闭 Workflow" })
    await close.click()
    await expect(openButton).toBeFocused()
    await openButton.click()
  }

  await page.reload()
  workflow = testInfo.project.name === "desktop-1440" ? page.locator("aside:visible") : page.locator('[role="dialog"]:visible')
  await expect(workflow.getByRole("heading", { name: title })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
  if (testInfo.project.name === "mobile-390") {
    expect((await workflow.getByRole("button", { name: "关闭 Workflow" }).boundingBox())?.height ?? 0).toBeGreaterThanOrEqual(44)
  }
  expect(errors).toEqual([])
})

test("keeps normal chat streaming, reload and explicit fork outside Research", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-1440", "ordinary Chat regression runs once on desktop")
  await register(page)
  let routeCalls = 0
  let chatRunCalls = 0
  await page.route("**/api/chat/route", async (route) => {
    routeCalls += 1
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ route: "normal_chat", reason: "explicit" }) })
  })
  await page.route("**/api/chat/runs", async (route) => {
    chatRunCalls += 1
    const content = `普通回答 ${chatRunCalls}`
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: `event: text.delta\ndata: ${JSON.stringify({ delta: content })}\n\nevent: message.completed\ndata: ${JSON.stringify({ content })}\n\n`,
    })
  })
  await page.getByLabel("回答模式").selectOption("normal")
  await page.getByPlaceholder("输入问题，Enter 发送…").fill("这是普通问题")
  await page.getByRole("button", { name: "发送" }).click()
  await expect(page.getByText("普通回答 1", { exact: true })).toBeVisible()
  await expect(page.getByRole("region", { name: /Research Run/ })).toHaveCount(0)

  await page.getByRole("button", { name: "重新生成一个分支" }).click()
  await expect(page.getByText("普通回答 2", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "分叉", exact: true }).last().click()
  await page.getByPlaceholder("输入新分支中的下一条问题…").fill("继续普通分支")
  await page.getByRole("button", { name: "创建分支" }).click()
  await expect(page.getByText("普通回答 3", { exact: true })).toBeVisible()
  expect(routeCalls).toBe(2)
  expect(chatRunCalls).toBe(3)
})
