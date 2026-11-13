async page => {
  if (page.url().includes("/login.html")) {
    await page.getByRole("textbox", {name: "姓名", exact: true}).fill("Accounts Probe");
    await page.getByRole("textbox", {name: "用户名", exact: true}).fill("accountsprobe");
    await page.getByRole("textbox", {name: "密码 显示密码", exact: true}).fill("AccountsProbe@2026");
    await page.getByRole("textbox", {name: "确认密码 显示确认密码", exact: true}).fill("AccountsProbe@2026");
    await page.getByRole("button", {name: "创建并进入", exact: true}).click();
  }
  await page.getByRole("tab", {name: "账户与权限 个人账户、角色与密码", exact: true}).click();
  await page.waitForFunction(() => document.querySelector("#localAccountCount")?.textContent.includes("个账户"));
  const selectors = ["#currentAccountPanel", "#currentAccountPanel > h3", ".account-profile",
    ".account-profile > div", "#currentAccountPanel > button", "#localAccountsPanel",
    "#localAccountsPanel > header", ".account-overview", ".account-stat", ".account-storage-note",
    ".account-guide-host", ".account-role-guide > summary", ".account-manager-layout",
    ".account-directory", ".account-editor", ".account-directory > header", ".account-editor > header",
    ".account-search input", "[data-account-roster]", ".account-roster-row", ".account-editor form",
    ".account-editor form > label", ".account-editor form > label > input", ".account-editor fieldset",
    ".account-editor fieldset > label", ".account-permission-preview", ".account-form-actions"];
  const samples = [];
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist: false}), theme);
    for (const width of [1180, 1100, 1000, 900, 820]) {
      await page.setViewportSize({width, height: 820});
      await page.locator("#currentAccountPanel").scrollIntoViewIfNeeded();
      await page.waitForTimeout(160);
      const controls = await page.evaluate(selectors => Object.fromEntries(selectors.map(selector => [
        selector, [...document.querySelectorAll(selector)].map(el => {
          const r = el.getBoundingClientRect(), css = getComputedStyle(el);
          return {text: el.innerText || el.value || "", rect: r.toJSON(),
            css: Object.fromEntries(["fontSize", "fontWeight", "lineHeight", "padding", "gap", "margin",
              "gridTemplateColumns", "color", "backgroundColor", "border", "borderRadius"].map(k => [k, css[k]]))};
        })])), selectors);
      samples.push({theme, width, controls});
      await page.screenshot({path: `accounts-${theme}-${width}-top.png`});
      await page.locator(".account-form-actions").scrollIntoViewIfNeeded();
      await page.screenshot({path: `accounts-${theme}-${width}-editor.png`});
    }
  }
  return {samples, api: await page.evaluate(async () => (await fetch("/api/auth/users")).json())};
}
