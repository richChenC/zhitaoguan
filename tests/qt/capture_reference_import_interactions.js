async page => {
  await page.setViewportSize({width: 1180, height: 820});
  const close = page.locator("#importDialog").getByRole("button", {name: "关闭", exact: true});
  if (await close.isVisible()) await close.click();
  await page.getByRole("tab", {name: "导入与显示 来源与可视化", exact: true}).click();
  const sourceRoot = await page.evaluate(() => window.__paritySourceRoot);
  if (!sourceRoot) throw new Error("Set window.__paritySourceRoot to an isolated RPT fixture before capture");
  await page.locator("#serverRoot").fill(sourceRoot);
  const save = page.getByRole("button", {name: "保存来源", exact: true});
  if (await save.isEnabled()) await save.click();
  await page.waitForFunction(() => document.querySelector("#sourceDirectorySaveStatus").textContent.includes("已保存"));
  await page.getByRole("button", {name: "扫描指套管目录", exact: true}).click();
  await page.waitForFunction(() => document.querySelector("#serverStatus").textContent.includes("已扫描"));
  const scan = await page.locator("#serverStatus").innerText();
  const source = await page.locator("#serverSources").innerText();
  await page.locator("#serverSources button").first().click();
  await page.waitForFunction(() => document.querySelector("#importDialog").open);
  await page.waitForTimeout(1000);
  const wizard = await page.locator("#importDialog").innerText();
  await page.screenshot({path: "reference-source-to-rpt.png"});
  await page.keyboard.press("Escape");
  await close.click();
  await page.getByRole("tab", {name: "对比规则 历次结果匹配", exact: true}).click();
  await page.locator("#arName").fill("TRAE来源验证");
  await page.locator("#arTolerance").fill(".025");
  await page.locator("#arNote").fill("隔离数据库交互核对");
  await page.locator("#arCreate").click();
  await page.waitForFunction(() => document.querySelector("#arActiveRule").textContent.includes("TRAE来源验证"));
  await page.getByRole("radio", {name: "以 v1 作为新版本基础", exact: true}).check();
  const base = await page.locator("#arBaseHint").innerText();
  const inheritedNote = await page.locator("#arNote").inputValue();
  await page.locator("#arName").fill("TRAE刷新草稿");
  await page.locator("#arTolerance").fill(".03");
  await page.locator("#arNote").fill("刷新保留");
  await page.locator("#arRefresh").click();
  await page.waitForTimeout(200);
  const draft = {name: await page.locator("#arName").inputValue(),
                 tolerance: await page.locator("#arTolerance").inputValue(),
                 note: await page.locator("#arNote").inputValue()};
  await page.screenshot({path: "reference-rules-history-draft.png"});
  const rules = await page.evaluate(async () => (await fetch("/api/analysis-rules")).json());
  return {scan, source, wizard, base, inheritedNote, draft, rules};
}
