async page => {
  const samples = [];
  for (const width of [1180, 1000, 901, 900, 820]) {
    await page.setViewportSize({width, height: 820});
    for (const pane of ["Import", "Rules"]) {
      await page.getByRole("tab", {name: pane === "Import" ? "导入与显示 来源与可视化" : "对比规则 历次结果匹配", exact: true}).click();
      await page.waitForTimeout(100);
      const controls = await page.evaluate(pane => {
        const root = document.querySelector("#settings" + pane + "Pane");
        root.scrollTop = 0;
        const selectors = pane === "Import" ?
          [".software-settings-panel", ".panel-title", ".software-settings-body", "#serverRoot", "#selectServerRoot", "#saveSourceDirectory", "#scanServerBtn", "#sourceDirectorySaveStatus", "#serverStatus", "#serverSources", "#reportPolicyNote", ".setting-row", ".severity-section-title", ".severity-control", "#severityThresholdNote"] :
          ["#analysisRulesPanel", ".panel-title", ".software-settings-body", ".ar-compact-note", ".ar-active", ".ar-list-head", ".ar-list", ".ar-rule-row", ".ar-new", ".ar-new-heading", ".ar-base-hint", ".setting-row", "#arName", "#arTolerance", "#arNote", "#arError", "#arCreate"];
        return Object.fromEntries(selectors.map(selector => [selector, [...root.querySelectorAll(selector)].map(el => {
          const r = el.getBoundingClientRect(), c = getComputedStyle(el);
          return {text: el.innerText || el.value || "", rect: {x: r.x, y: r.y, width: r.width, height: r.height},
            css: Object.fromEntries(["padding", "margin", "gap", "fontSize", "fontWeight", "lineHeight", "color", "backgroundColor", "border", "borderRadius", "gridTemplateColumns"].map(key => [key, c[key]]))};
        })]));
      }, pane);
      samples.push({width, pane, controls});
      await page.screenshot({path: "reference-" + pane + "-" + width + ".png"});
    }
  }
  return {samples};
}
