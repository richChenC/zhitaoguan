// Run using playwright-cli run-code --filename against the isolated TRAE page.
async (page) => {
  const samples = [];
  for (const width of [1480, 1101, 1100, 1024, 980]) {
    await page.setViewportSize({width, height: 940});
    for (const theme of ['light', 'dark']) {
      await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist: false}), theme);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const sample = await page.evaluate(() => {
        const info = element => {
          const style = getComputedStyle(element), rect = element.getBoundingClientRect();
          const before = getComputedStyle(element, '::before');
          return {
            text: element.textContent.trim(), rect: {x: rect.x, y: rect.y, w: rect.width, h: rect.height},
            font: style.font, color: style.color, background: style.backgroundColor,
            borderColor: style.borderColor, borderWidth: style.borderWidth,
            borderRadius: style.borderRadius, padding: style.padding, margin: style.margin,
            gap: style.gap, alignItems: style.alignItems, justifyContent: style.justifyContent,
            before: {width: before.width, height: before.height, background: before.backgroundColor,
              color: before.color, content: before.content, display: before.display},
          };
        };
        const selectors = ['.app-nav', '.nav-group', '.app-nav footer', '.nav-utilities', '.nav-status',
          '#localAccountButton', '.account-avatar', '.account-summary', '.account-name', '.account-status',
          '.account-status i', '#feedbackToggle', '.nav-settings', '#localServiceState',
          '.nav-group button::first', 'main', '.workspace-filters', '.workspace-commands', '.table-panel'];
        const controls = {};
        for (const selector of selectors) {
          if (selector.endsWith('::first')) continue;
          const element = document.querySelector(selector);
          if (element) controls[selector] = info(element);
        }
        return {width: innerWidth, theme: document.documentElement.dataset.theme, controls,
          tabs: [...document.querySelectorAll('.nav-group button')].map(info)};
      });
      await page.screenshot({path: `reference-navigation-${width}-${theme}.png`});
      samples.push(sample);
    }
  }
  return samples;
}
