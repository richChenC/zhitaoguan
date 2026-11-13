// Exercise actual row/range selection and generate the real reference export.
async (page) => {
  await page.setViewportSize({width:1480,height:940});
  await page.waitForFunction(() => document.querySelector('#rows')?.getAttribute('aria-busy') !== 'true');
  const samples = [];
  const settled = async () => {
    await page.waitForFunction(() => document.querySelector('#rows').getAttribute('aria-busy') !== 'true');
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  };
  const capture = async name => {
    await settled();
    samples.push(await page.evaluate(name => ({
      name,selected:selectedRecords().map(row=>row.id),
      scopes:[...new Set(selectedRecords().map(row=>`${row.site_code}|${row.unit_id}|${row.outage}`))],
      sort:state.sort,order:state.order,stats:document.querySelector('#coreStats').textContent,
      page:state.page,first:state.items[0]?.id
    }),name));
  };
  await page.getByRole('button',{name:'清除勾选',exact:true}).evaluate(button=>button.click());
  const cell = row => page.locator('#rows tr').nth(row).locator('td').nth(2);
  await cell(0).click();
  await capture('row-0-click');
  await cell(3).click({modifiers:['Shift']});
  await capture('shift-row-3');
  await cell(3).click({modifiers:['Shift']});
  await capture('shift-same-row-3');
  await cell(56).click();
  await capture('reject-other-scope-row-56');
  await page.getByRole('button',{name:'全选本页',exact:true}).click();
  await capture('select-page');
  await page.getByRole('button',{name:'全选本页',exact:true}).click();
  await capture('select-page-again');
  // A double click must restore the initial checked state before editing.
  await page.locator('#rows tr').nth(1).locator('[data-edit-field="analysis"]').dblclick();
  await capture('double-click-editor');
  await page.locator('.inline-finding-editor').press('Escape');
  await capture('cancel-editor');
  const exported = await page.evaluate(() => {
    const {canvas,unit,outage} = createCoreSnapshot();
    const stats = selectedFindingStats();
    return {png:canvas.toDataURL('image/png').split(',')[1],width:canvas.width,height:canvas.height,unit,outage,
      settings:severitySettings(),records:selectedRecords(),tubeMaximums:[...stats.tubeMaximums],
      maxPercent:stats.maxPercent,densestZone:stats.densestZone,densestCount:stats.densestCount};
  });
  await page.getByRole('button',{name:'清除勾选',exact:true}).click();
  for (let index=0;index<3;index++) {
    await page.locator('th[data-sort="percent"]').click();
    await capture(`sort-percent-${index+1}`);
  }
  return {samples,exported};
}
