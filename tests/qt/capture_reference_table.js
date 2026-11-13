// Capture the reference table's final CSS and exercise its actual pagination.
async (page) => {
  const samples = [];
  const settled = async () => {
    await page.waitForFunction(() => document.querySelector('#rows').getAttribute('aria-busy') !== 'true');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };
  const capture = async name => {
    await settled();
    samples.push(await page.evaluate(name => {
      const info = element => {
        const style = getComputedStyle(element), rect = element.getBoundingClientRect();
        return {text:element.textContent.trim(), rect:{x:rect.x,y:rect.y,w:rect.width,h:rect.height},
          display:style.display, padding:style.padding, font:style.font, color:style.color,
          background:style.backgroundColor, border:style.border, gap:style.gap,
          disabled:element.disabled, value:element.value};
      };
      const selectors = ['#workspace .table-panel', '#workspace .table-panel .panel-title',
        '#resultInfo', '.workspace-table-actions', '.selection-tools', '.workspace-column-modes',
        '.workspace-column-modes button', '#workspace .table-wrap', '#workspace table',
        '#workspace thead th', '#workspace tbody tr:first-child td', '#workspace .pager',
        '.workspace-pager-settings', '.workspace-pager-navigation', '#workspacePageRange',
        '#pageSize', '#prevBtn', '#pageInfo', '#nextBtn', '#workspacePageJump',
        '#workspace .core-panel', '#workspace .core-panel .panel-title', '#exportCorePng',
        '#workspace .core-switch', '#workspace .core-switch button', '#coreMap'];
      return {name,width:innerWidth,theme:document.documentElement.dataset.theme,
        mode:document.querySelector('#workspace .table-panel').dataset.columns,
        controls:Object.fromEntries(selectors.map(s=>[s,[...document.querySelectorAll(s)].map(info)])),
        pageSizes:[...document.querySelector('#pageSize').options].map(o=>Number(o.value)),
        firstRecord:document.querySelector('#rows tr')?.textContent.trim()};
    }, name));
  };
  await page.getByRole('button',{name:'清除条件',exact:true}).evaluate(button => {
    if (!button.disabled) button.click();
  });
  await settled();
  for (const width of [1480,1120,1024,980]) {
    await page.setViewportSize({width,height:940});
    for (const theme of ['light','dark']) {
      await page.evaluate(theme=>window.appAppearance.setTheme(theme,{persist:false}),theme);
      for (const mode of ['focus','all']) {
        await page.locator(`[data-workspace-columns="${mode}"]`).click();
        await page.evaluate(()=>document.querySelector('main').scrollTop=0);
        await capture(`${width}-${theme}-${mode}`);
      }
    }
  }
  await page.locator('#nextBtn').click();
  await capture('next-page');
  await page.locator('#workspacePageJump').fill('46');
  await page.locator('#workspacePageJump').press('Enter');
  await capture('last-page');
  await page.locator('#workspacePageJump').fill('999');
  await page.locator('#workspacePageJump').press('Enter');
  await capture('same-last-page');
  await page.locator('#pageSize').selectOption('20');
  await capture('size-20');
  await page.locator('#workspacePageJump').fill('2');
  await page.locator('#workspacePageJump').press('Escape');
  await capture('escape-jump');
  await page.locator('#pageSize').selectOption('100');
  await page.locator('[data-workspace-columns="focus"]').click();
  await settled();
  await page.setViewportSize({width:1480,height:940});
  await page.evaluate(()=>document.querySelector('main').scrollTop=0);
  await page.screenshot({path:'reference-table-1480.png'});
  return samples;
}
