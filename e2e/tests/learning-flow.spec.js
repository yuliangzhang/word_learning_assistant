const { test, expect } = require("@playwright/test");

test("import -> commit -> chat today -> linked learn flow -> weekly report", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "单词管家" })).toBeVisible();

  await page.locator("#import-text").fill("antenna\nbecause\nscience");
  await page.locator("#import-tags").fill("Reading,Science");
  await page.getByRole("button", { name: "文本预览" }).click();

  await expect(page.getByText("导入预览清单")).toBeVisible();
  await page.getByRole("button", { name: "确认入库" }).click();
  await expect(page.getByText("导入完成，入库")).toBeVisible();

  await page.locator("#chat-input").fill("帮我开始今天任务");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("今日任务", { exact: false })).toBeVisible();

  await page.locator("#chat-input").fill("开始学习词库中的单词吧");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("学习链路已准备好", { exact: false })).toBeVisible();
  await expect(page.locator('a.link[href*="/artifacts/learning/"]').first()).toBeVisible();
  await expect(page.locator('a.link[href*="/artifacts/exercises/"]').first()).toBeVisible();

  await page.getByRole("button", { name: "生成周报" }).click();
  await expect(page.getByRole("link", { name: "打开周报 HTML" })).toBeVisible();
});
