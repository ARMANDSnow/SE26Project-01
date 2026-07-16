import { expect, test } from "@playwright/test"

async function register(page: import("@playwright/test").Page) {
  await page.goto("/")
  await page.getByRole("button", { name: "没有账户？创建账户" }).click()
  const username = `e2e_${Date.now()}_${Math.floor(Math.random() * 10000)}`
  await page.getByLabel("用户名").fill(username)
  await page.getByLabel("密码").fill("playwright-password")
  await page.getByRole("button", { name: "注册并登录" }).click()
  await expect(page.getByRole("button", { name: "打开任务中心" })).toBeVisible()
}

test("creates, restores and completes the deterministic research harness", async ({ page }) => {
  await register(page)
  const trigger = page.getByRole("button", { name: "打开任务中心" })
  await trigger.focus()
  await trigger.click()
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeVisible()
  await page.keyboard.press("Escape")
  await expect(trigger).toBeFocused()

  await trigger.click()
  await page.getByLabel("任务标题").fill("Playwright Harness")
  await page.getByLabel("研究目标").fill("验证刷新后从数据库恢复确定性三步骨架")
  await page.getByRole("button", { name: "创建 Harness" }).click()
  const runLink = page.locator('a[href^="/runs/"]').filter({ hasText: "Playwright Harness" })
  await expect(runLink).toBeVisible()
  await runLink.click()
  await expect(page.getByRole("heading", { name: "任务中心" })).toBeHidden()
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/)
  await expect(page.getByRole("heading", { name: "执行步骤" })).toBeVisible()
  await expect(page.getByText("Harness 骨架输出；未执行论文调研或外部调用。")).toHaveCount(3)
  await expect(page.getByText("已完成", { exact: true }).first()).toBeVisible()

  await page.reload()
  await expect(page.getByRole("heading", { name: "执行步骤" })).toBeVisible()
  await expect(page.getByText("Harness 骨架输出；未执行论文调研或外部调用。")).toHaveCount(3)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
})
