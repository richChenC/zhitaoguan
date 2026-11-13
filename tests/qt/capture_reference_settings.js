async page => {
  const samples = [];
  await page.waitForFunction(() => document.querySelector('#dataSourceMode')?.dataset.state !== 'loading');
  for (const theme of ['light', 'dark']) {
    await page.evaluate(theme => window.appAppearance.setTheme(theme, {persist:false}), theme);
    for (const width of [1180, 1001, 1000, 820]) {
      await page.setViewportSize({width,height:820});
      for (const pane of ['Data', 'Preferences', 'Import', 'Rules', 'Accounts', 'Maintenance']) {
        await page.locator(`#settings${pane}Tab`).click();
        await page.waitForTimeout(150);
        samples.push(await page.evaluate(({theme,width,pane}) => {
          const selectors = ['main', '#settings', '.settings-window-heading', '.settings-window-heading h1',
            '.settings-window-heading p', '.settings-window-state', '.settings-workspace', '.settings-sidebar',
            '.settings-sidebar-label', '.settings-nav', '.settings-local-indicator', '.settings-sections',
            `#settings${pane}Pane`, `#settings${pane}Pane .panel-title`,
            `#settings${pane}Pane .software-settings-body`, '.storage-details', '.storage-path-value',
            '#dataSourcePath', '#copyDataSourcePath', '#dataSourceStatus', '#refreshDataSource',
            '#validateDataSource', '#dataSourceMode', '.settings-quick-actions', '.settings-quick-heading',
            '.settings-quick-grid', '#settingsPreferencesPane .settings-action-row'];
          const read = node => {
            const style=getComputedStyle(node);
            return {text:node.innerText, rect:node.getBoundingClientRect().toJSON(),
              visible:!!node.getClientRects().length,
              style:Object.fromEntries(['fontSize','fontWeight','lineHeight','color','backgroundColor',
                'borderColor','borderRadius','paddingTop','paddingRight','paddingBottom','paddingLeft',
                'gap','rowGap','columnGap','gridTemplateColumns','marginTop','marginBottom'].map(key=>[key,style[key]]))};
          };
          const controls=Object.fromEntries(selectors.map(selector=>[selector,
            document.querySelector(selector)?read(document.querySelector(selector)):null]));
          const rows=[...document.querySelectorAll(`#settings${pane}Pane .setting-row`)]
            .map(node=>({...read(node),control:node.querySelector('select,input,.theme-switch')?
              read(node.querySelector('select,input,.theme-switch')):null}));
          return {theme,width,pane,controls,rows,
            tabs:[...document.querySelectorAll('.settings-nav button')].map(read),
            quick:[...document.querySelectorAll('.settings-quick-grid button')].map(read)};
        }, {theme,width,pane}));
        if(width===1180 || pane==='Data')
          await page.screenshot({path:`reference-settings-${pane}-${width}-${theme}.png`});
      }
    }
  }
  await page.locator('#settingsDataTab').click();
  await page.locator('[data-settings-jump="settingsImportPane"]').click();
  const quickJump = await page.locator('#settingsImportTab').getAttribute('aria-selected');
  await page.locator('#settingsImportTab').press('ArrowDown');
  const arrowNext = await page.locator('#settingsRulesTab').getAttribute('aria-selected');
  await page.locator('#settingsRulesTab').press('End');
  const end = await page.locator('#settingsMaintenanceTab').getAttribute('aria-selected');
  await page.locator('#settingsMaintenanceTab').press('ArrowRight');
  const wrap = await page.locator('#settingsDataTab').getAttribute('aria-selected');
  return {samples, keyboard:{quickJump,arrowNext,end,wrap}};
}
