async page => {
  const samples = [];
  await page.getByRole("tab", {name: "导入与显示 来源与可视化", exact: true}).click();
  for (const theme of ["light", "dark"]) {
    await page.evaluate(theme => {
      document.documentElement.dataset.theme = theme;
      document.documentElement.classList.toggle("dark", theme === "dark");
      document.body.dataset.theme = theme;
    }, theme);
    for (const width of [1180, 1000, 900, 820]) {
      await page.setViewportSize({width, height: 820});
      for (const tab of ["校验问题", "导入批次", "文件校验", "报告版本", "跨组复核"]) {
        await page.getByRole("tab", {name: tab, exact: true}).click();
        await page.waitForTimeout(120);
        await page.locator("#settingsImportPane .import-quality").scrollIntoViewIfNeeded();
        const controls = await page.evaluate(() => {
          const root = document.querySelector("#settingsImportPane .import-quality");
          const selectors = [":scope", ":scope > summary", ".iq-toolbar", ".iq-toolbar label",
            "#iqBatch", "#iqCategory", "#iqRefresh", "#iqExport", "#iqRollback", "#iqRestore",
            "#iqStatus", ".iq-tabs", ".iq-tabs button", ".ac-table-wrap", "th", "td", ".iq-pager"];
          return Object.fromEntries(selectors.map(selector => [selector,
            (selector === ":scope" ? [root] : [...root.querySelectorAll(selector)]).map(el => {
              const r = el.getBoundingClientRect(), c = getComputedStyle(el);
              return {text: el.innerText || el.value || "",
                rect: {x: r.x, y: r.y, width: r.width, height: r.height},
                css: Object.fromEntries(["padding", "margin", "gap", "fontSize", "fontWeight",
                  "lineHeight", "color", "backgroundColor", "border", "borderRadius",
                  "maxHeight", "minWidth", "maxWidth", "flex"].map(key => [key, c[key]]))};
            })]));
        });
        samples.push({theme, width, tab, controls});
        if (tab === "校验问题") await page.screenshot({path: `quality-${theme}-${width}.png`});
      }
    }
  }
  return {samples};
}
