// Capture final reference styles after the complete stylesheet cascade.
async (page) => {
  const samples = [];
  const settled = async () => {
    await page.waitForFunction(() => document.querySelector('#rows').getAttribute('aria-busy') !== 'true');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };
  const capture = async name => {
    await settled();
    await page.evaluate(() => document.querySelector('main').scrollTop = 0);
    samples.push(await page.evaluate(name => {
      const info = element => {
        const s = getComputedStyle(element), r = element.getBoundingClientRect();
        return {text:element.textContent.trim().slice(0,250),rect:{x:r.x,y:r.y,w:r.width,h:r.height},
          display:s.display,padding:s.padding,margin:s.margin,font:s.font,color:s.color,
          background:s.backgroundColor,border:s.border,gap:s.gap,order:s.order,
          gridColumns:s.gridTemplateColumns,disabled:element.disabled};
      };
      const selectors = ['#workspace .split','#workspace .table-panel','#workspace .core-panel',
        '.core-panel-title','.core-panel-title h2','.core-panel-title span','#exportCorePng',
        '.core-switch','.core-switch button','#coreMap','.reference-grid','.grid-cell',
        '.ref-letters span','.ref-numbers span','.path-marker','.path-half',
        '.flow-mark','#coreStats','#coreStats span','#coreStats small','#coreStats b',
        '#detail','#detail::before','.selection-detail-head','.selected-record-list article'];
      const controls = {};
      for (const selector of selectors) {
        if (selector.endsWith('::before')) {
          controls[selector] = {content:getComputedStyle(document.querySelector('#detail'),'::before').content};
        } else {
          let elements = [...document.querySelectorAll(selector)];
          if (selector === '.grid-cell') elements = [elements[0],elements.at(-1)];
          if (selector === '.selected-record-list article') elements = elements.slice(0,2);
          controls[selector] = elements.filter(Boolean).map(info);
        }
      }
      return {name,width:innerWidth,theme:document.documentElement.dataset.theme,controls};
    },name));
  };
  for (const width of [1480,1281,1280,1121,1120,1101,1100,1024,980]) {
    await page.setViewportSize({width,height:940});
    for (const theme of ['light','dark']) {
      await page.evaluate(theme => window.appAppearance.setTheme(theme,{persist:false}),theme);
      await capture(`${width}-${theme}-empty`);
    }
  }
  await page.setViewportSize({width:1480,height:940});
  await page.getByRole('button',{name:'全选本页',exact:true}).click();
  await capture('1480-dark-selected');
  for (const mode of ['combined','odd','even']) {
    await page.locator(`[data-core-mode="${mode}"]`).click();
    await capture(`1480-dark-selected-${mode}`);
  }
  await page.screenshot({path:'reference-plate-selected-dark.png'});
  await page.getByRole('button',{name:'清除勾选',exact:true}).click();
  await page.locator('[data-core-mode="combined"]').click();
  await page.evaluate(() => window.appAppearance.setTheme('light',{persist:false}));
  await page.screenshot({path:'reference-plate-light.png'});
  return samples;
}
