async page => {
  await page.setViewportSize({width: 1180, height: 820});
  await page.evaluate(() => window.appAppearance.setTheme("light", {persist: false}));
  const editor = page.locator(".account-editor");
  await editor.getByRole("textbox", {name: "用户名（建议姓名完整拼音，创建后不可更改）", exact: true}).fill("referenceviewer");
  await editor.getByRole("textbox", {name: "姓名或显示名称", exact: true}).fill("参照账户验证");
  await editor.getByRole("textbox", {name: "密码（至少 6 位；编辑时留空保持不变）", exact: true}).fill("ReferenceViewer@2026");
  await editor.getByRole("textbox", {name: "确认密码", exact: true}).fill("Mismatch@2026");
  await editor.getByRole("button", {name: "创建账户", exact: true}).click();
  await page.waitForFunction(() => document.querySelector(".account-editor [role=status]").textContent.includes("不一致"));
  await editor.getByRole("textbox", {name: "确认密码", exact: true}).fill("ReferenceViewer@2026");
  await editor.getByRole("button", {name: "创建账户", exact: true}).click();
  await page.waitForFunction(() => document.querySelector("#localAccountCount").textContent.startsWith("2 个账户"));
  const created = await editor.locator("input[name=username]").inputValue();
  await editor.getByRole("textbox", {name: "姓名或显示名称", exact: true}).fill("未保存资料");
  await editor.getByRole("button", {name: "新建账户", exact: true}).click();
  await page.getByRole("button", {name: "继续编辑", exact: true}).click();
  const kept = await editor.locator("input[name=display_name]").inputValue();
  await editor.getByRole("button", {name: "新建账户", exact: true}).click();
  await page.getByRole("button", {name: "放弃更改", exact: true}).click();
  const cleared = await editor.locator("input[name=username]").inputValue();
  await page.locator(".account-role-guide > summary").click();
  const matrix = [];
  for (const width of [1180, 900, 820]) {
    await page.setViewportSize({width, height: 820});
    await page.locator(".account-role-guide").scrollIntoViewIfNeeded();
    matrix.push(await page.locator(".account-role-guide").evaluate((root, width) => ({
      width, rect: root.getBoundingClientRect().toJSON(),
      cards: [...root.querySelectorAll("article")].map(el => ({
        rect: el.getBoundingClientRect().toJSON(), text: el.innerText
      }))
    }), width));
    await page.screenshot({path: `reference-account-matrix-${width}.png`});
  }
  await page.setViewportSize({width: 1180, height: 820});
  await page.getByRole("button", {name: "账户安全与退出", exact: true}).click();
  const modal = page.locator(".local-account-dialog[open]");
  await modal.waitFor();
  const security = [];
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist: false}), theme);
    for (const expanded of [false, true]) {
      if (expanded) await modal.locator("summary").click();
      const controls = await modal.evaluate(root => Object.fromEntries([
        ":scope", "h2", ".account-dialog-identity", ".account-dialog-role", "details", "label", "input",
        ".auth-message", "menu", "button"
      ].map(selector => [selector, (selector === ":scope" ? [root] : [...root.querySelectorAll(selector)]).map(el => {
        const c = getComputedStyle(el);
        return {text: el.innerText || "", rect: el.getBoundingClientRect().toJSON(),
          css: Object.fromEntries(["fontSize", "lineHeight", "padding", "margin", "gap", "borderRadius"].map(k => [k,c[k]]))};
      })])));
      security.push({theme, expanded, controls});
      await page.screenshot({path: `reference-account-security-${theme}-${expanded}.png`});
    }
    await modal.locator("summary").click();
  }
  await modal.getByRole("button", {name: "关闭", exact: true}).click();
  return {created, kept, cleared, matrix, security};
}
