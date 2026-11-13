async page => {
  const root = page.locator("#settingsImportPane .import-quality");
  const ready = () => page.waitForFunction(() =>
    document.querySelector("#settingsImportPane .import-quality").getAttribute("aria-busy") === "false");
  await root.getByRole("button", {name: "刷新清单", exact: true}).click();
  await ready();
  await root.getByRole("combobox", {name: "导入批次", exact: true}).selectOption("2");
  await ready();
  await root.getByRole("tab", {name: "跨组复核", exact: true}).click();
  await ready();
  const group = root.locator(".iq-review");
  if (await group.count() !== 1) throw new Error("Expected one isolated cross-group fixture");
  await group.getByRole("radio").nth(1).check();
  await group.getByRole("textbox", {name: "复核依据", exact: true}).fill("隔离复核依据");
  await group.getByRole("button", {name: "采用所选代表", exact: true}).click();
  await page.waitForFunction(() => document.querySelector("#iqStatus").textContent.includes("复核已保存"));
  await group.getByRole("button", {name: "保留全部", exact: true}).click();
  await page.waitForFunction(() => document.querySelector(".iq-review header span").textContent === "已确认保留全部");
  await group.getByRole("button", {name: "撤销复核", exact: true}).click();
  await page.waitForFunction(() => document.querySelector(".iq-review header span").textContent === "已撤销，待复核");
  await group.locator(".iq-review-history summary").click();
  const samples = [];
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => { document.documentElement.dataset.theme = theme; document.body.dataset.theme = theme; }, theme);
    for (const width of [1180, 1000, 900, 820]) {
      await page.setViewportSize({width, height: 820});
      await group.scrollIntoViewIfNeeded();
      const controls = await group.evaluate(group => {
        const bounds = group.getBoundingClientRect();
        return Object.fromEntries(["header", "header strong", ".ac-table-wrap", ".iq-review-actions",
          ".iq-review-reason", "[data-review]", ".iq-review-history", ".iq-review-history summary"].map(selector => [
          selector, [...group.querySelectorAll(selector)].map(el => {
            const r = el.getBoundingClientRect(), c = getComputedStyle(el);
            return {text: el.innerText || el.value || "",
              rect: {x: r.x - bounds.x, y: r.y - bounds.y, width: r.width, height: r.height},
              css: Object.fromEntries(["fontSize", "lineHeight", "padding", "gap", "backgroundColor", "borderRadius"].map(key => [key, c[key]]))};
          })]));
      });
      samples.push({theme, width, controls});
      await page.screenshot({path: `reference-quality-review-${theme}-${width}.png`});
    }
  }
  const api = await page.evaluate(async () => (await fetch("/api/cross-group-reviews?batch_id=2")).json());
  return {samples, status: await root.locator("#iqStatus").innerText(),
    groups: api.items.map(g => ({status: g.status, members: g.members.length, history: g.history.length}))};
}
