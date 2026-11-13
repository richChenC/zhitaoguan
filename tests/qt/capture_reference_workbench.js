// Capture the live reference's workbench geometry and filter-summary behavior.
async (page) => {
  const capture = async (name, screenshot = true) => {
    await page.waitForFunction(() => document.querySelector('#rows').getAttribute('aria-busy') !== 'true');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const sample = await page.evaluate(() => {
      const selectors = ['main', '#workspace', '#workspace .toolbar', '.workspace-filters',
        '.workspace-commands', '.workspace-command-group', '#workspaceFilterSummary', '#workspace .split',
        '#workspace .table-panel', '#workspace .table-panel .panel-title', '#workspace .core-panel',
        '#workspace .core-panel .panel-title', '#workspace .core-switch', '#workspace .core-map',
        '#workspace .table-wrap', '#workspace .pager', '.workspace-column-modes',
        '#workspace .workspace-filter', '#searchBtn', '#resetBtn', '#openImportFlow', '#exportLedgerBtn',
        '#btn-data-delete', '#btn-recycle-bin', '#clearRecordsBtn', '#workspaceRefreshRecords',
        '#selectAllRows', '#clearPageSelection', '#workspaceSelectionCount', '#pageSize', '#pageInfo',
        '#workspacePageRange', '#workspacePageJump'];
      const info = element => {
        const s = getComputedStyle(element), r = element.getBoundingClientRect();
        return {text: element.textContent.trim().slice(0, 150), rect: {x:r.x,y:r.y,w:r.width,h:r.height},
          padding:s.padding, margin:s.margin, gap:s.gap, font:s.font, background:s.backgroundColor,
          color:s.color, border:s.border, borderRadius:s.borderRadius,
          grid:s.gridTemplateColumns, disabled:element.disabled, active:element.dataset.active};
      };
      const controls = Object.fromEntries(selectors.map(selector => [selector,
        [...document.querySelectorAll(selector)].map(info)]));
      return {width:innerWidth, theme:document.documentElement.dataset.theme, controls,
        chips:[...document.querySelectorAll('.workspace-filter-chip')].map(element=>({
          text:element.querySelector('span').textContent, clear:element.querySelector('button').getAttribute('aria-label')}))};
    });
    if (screenshot) await page.screenshot({path:`reference-workbench-${name}.png`});
    return {name, ...sample};
  };
  const samples = [];
  for (const width of [1480, 1120, 1024, 980]) {
    await page.setViewportSize({width,height:940});
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => window.appAppearance.setTheme(theme,{persist:false}),theme);
      samples.push(await capture(`${width}-${theme}`));
    }
  }
  await page.getByRole('combobox',{name:'基地',exact:true}).selectOption('N');
  await page.getByRole('combobox',{name:'机组',exact:true}).selectOption('1');
  await page.getByRole('combobox',{name:'大修批次',exact:true}).selectOption('N101');
  await page.getByRole('combobox',{name:'检测结论',exact:true}).selectOption('war');
  await page.getByRole('combobox',{name:'维护状态',exact:true}).selectOption('plugged');
  await page.getByRole('combobox',{name:'分析人员',exact:true}).fill('张三');
  await page.getByRole('spinbutton',{name:'通道编号',exact:true}).fill('6');
  await page.getByRole('button',{name:'应用筛选',exact:true}).click();
  samples.push(await capture('seven-filters'));
  await page.getByRole('button',{name:'清除条件：检测结论：WAR',exact:true}).click();
  samples.push(await capture('clear-detection'));
  await page.getByRole('button',{name:'清除全部',exact:true}).click();
  samples.push(await capture('clear-all'));
  return samples;
}
