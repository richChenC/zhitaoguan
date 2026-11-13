async page => {
  await page.setViewportSize({width:1480,height:940});
  await page.waitForFunction(() => document.querySelector('#rows')?.getAttribute('aria-busy') !== 'true');
  const samples=[], requests=[];
  page.on('request',request=>{
    if(request.method()==='POST'&&new URL(request.url()).pathname==='/api/findings/edit')
      requests.push(request.postDataJSON());
  });
  const original=await page.evaluate(()=>({...state.items[0]}));
  const begin=async(field,row=0)=>{
    await page.locator('#rows tr').nth(row).locator(`[data-edit-field="${field}"]`).dblclick();
    const editor=page.locator('.inline-finding-editor');
    await editor.waitFor();
    return editor;
  };
  const saved=async(field,value)=>{
    await page.waitForFunction(({field,value})=>
      !document.querySelector('.inline-finding-editor')&&
      document.querySelector('#rows').getAttribute('aria-busy')!=='true'&&state.items[0]?.[field]===value,
      {field,value});
  };
  let editor=await begin('analysis');
  samples.push(await editor.evaluate(control=>{
    const style=getComputedStyle(control);
    return {name:'multiline-open',tag:control.tagName,value:control.value,
      rect:control.getBoundingClientRect().toJSON(),cell:control.parentElement.getBoundingClientRect().toJSON(),
      style:Object.fromEntries(['fontFamily','fontSize','fontWeight','lineHeight','paddingTop','paddingLeft',
        'borderTopWidth','borderRadius','minHeight','height'].map(key=>[key,style[key]]))};
  }));
  await page.screenshot({path:'reference-multiline-editor.png'});
  await editor.fill('NATIVE MULTILINE CHECK\n中文第二行');
  await editor.press('End');
  await editor.press('Enter');
  samples.push({name:'enter-newline',value:await editor.inputValue(),requests:requests.length});
  const entered=await editor.inputValue();
  await editor.press('Control+Enter');
  await saved('analysis',entered);
  samples.push({name:'control-enter-saved',value:await page.evaluate(()=>state.items[0].analysis),
    selected:await page.evaluate(()=>selectedRecords().map(row=>row.id)),requests:requests.length});
  editor=await begin('analysis');
  await editor.fill('CANCELED VALUE');
  await editor.press('Escape');
  await page.waitForFunction(()=>!document.querySelector('.inline-finding-editor'));
  samples.push({name:'escape-preserves',value:await page.evaluate(()=>state.items[0].analysis),requests:requests.length});
  editor=await begin('analysis');
  await editor.fill(original.analysis??'');
  await page.locator('#workspace .table-panel .panel-title').click();
  await saved('analysis',original.analysis??'');
  samples.push({name:'blur-restored',value:await page.evaluate(()=>state.items[0].analysis),requests:requests.length});
  const locationRecord=await page.evaluate(()=>({...state.items[2]}));
  editor=await begin('location',2);
  samples.push({name:'location-raw-editor',tag:await editor.evaluate(control=>control.tagName),
    value:await editor.inputValue(),raw:locationRecord.location_raw,display:locationRecord.location});
  await editor.press('Escape');
  return {record:original,locationRecord,samples,requests};
}
