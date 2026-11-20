async page => {
  if (page.url().includes("/login.html")) {
    await page.getByRole("textbox", {name: "姓名", exact: true}).fill("Backup Probe");
    await page.getByRole("textbox", {name: "用户名", exact: true}).fill("backupprobe");
    await page.getByRole("textbox", {name: "密码 显示密码", exact: true}).fill("BackupProbe@2026");
    await page.getByRole("textbox", {name: "确认密码 显示确认密码", exact: true}).fill("BackupProbe@2026");
    await page.getByRole("button", {name: "创建并进入", exact: true}).click();
  }
  await page.goto("http://127.0.0.1:18886/?window=settings");
  await page.locator("#settingsMaintenanceTab").click();
  await page.waitForFunction(() => document.querySelector("#backupSummary")?.textContent.includes("有效检测记录"));
  while (await page.locator(".backup-row").count() < 3) {
    const before = await page.locator(".backup-row").count();
    await page.locator("#backupNow").click();
    await page.waitForFunction(before => document.querySelectorAll(".backup-row").length > before &&
      !document.querySelector("#backupNow").disabled, before);
  }
  const selectors = ["#backupPanel", "#backupPanel > .panel-title", "#backupPanel h2",
    "#backupPanel .software-settings-body", "#backupSummary", "#backupSummary > div",
    "#backupSummary span", "#backupSummary strong", ".backup-actions", ".backup-actions button",
    ".backup-list-head", ".backup-list", ".backup-row", ".backup-info", ".backup-info b",
    ".backup-info small", ".backup-meta", ".backup-restore"];
  const read = async selectors => page.evaluate(selectors => Object.fromEntries(selectors.map(selector =>
    [selector, [...document.querySelectorAll(selector)].map(el => {
      const r = el.getBoundingClientRect(), css = getComputedStyle(el);
      return {text: el.innerText, rect: r.toJSON(),
        css: Object.fromEntries(["fontSize", "fontWeight", "lineHeight", "padding", "gap", "margin",
          "gridTemplateColumns", "color", "backgroundColor", "border", "borderRadius"].map(k => [k, css[k]]))};
    })])), selectors);
  const samples = [], dialogs = [];
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist: false}), theme);
    for (const width of [1180, 1000, 900, 820]) {
      await page.setViewportSize({width, height: 820});
      await page.locator("#backupPanel").scrollIntoViewIfNeeded();
      await page.waitForTimeout(180);
      samples.push({theme, width, controls: await read(selectors)});
      await page.screenshot({path: `backup-${theme}-${width}.png`});
    }
    await page.setViewportSize({width: 1180, height: 820});
    await page.locator(".backup-restore").first().click();
    await page.waitForFunction(() => !document.querySelector("#restoreAck").disabled);
    dialogs.push({theme, controls: await read(["#restoreDialog", ".wizard-head", ".restore-danger",
      ".restore-compare", ".restore-compare > div", ".restore-check", ".wizard-actions", "#restoreMsg",
      "#restoreConfirm", "#restoreCancel"])});
    await page.screenshot({path: `backup-restore-${theme}.png`});
    await page.locator("#restoreAck").check();
    const enabled = await page.locator("#restoreConfirm").isEnabled();
    await page.locator("#restoreCancel").click();
    if (!enabled) throw new Error("Checked and validated backup did not enable restore");
  }
  return {samples, dialogs, api: await page.evaluate(async () => (await fetch("/api/backups")).json())};
}
