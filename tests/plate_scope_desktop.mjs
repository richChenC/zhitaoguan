import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'output/playwright'),`plate-scope-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const python=path.join(root,'.venv/Scripts/python.exe'),source=path.join(root,'data/thimble.db');
const hash=()=>createHash('sha256').update(fs.readFileSync(source)).digest('hex'),before=hash();
const env={...process.env,PYTHONIOENCODING:'utf-8',THIMBLE_ALLOW_MULTI_INSTANCE:'1',
  THIMBLE_PYTHON:python,THIMBLE_DB_PATH:path.join(output,'isolated-test.db'),
  THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
  THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')};
execFileSync(python,['-X','utf8','-c',`
import json
from src.backend import server
server.init_db()
with server.connect() as db:
 for outage,unit,depth in [('D101',1,60),('D102',1,20),('D103',1,70),('D106',1,10),('D201',2,12)]:
  for tube in range(1,51):
   key=f'mock-{outage}-{tube}'
   code='WAR' if tube==1 else 'NDD'
   db.execute("INSERT INTO findings(outage,unit_id,thimble_id,position,indication,percent,location,site_code,entry_no,channel,report_path,filename,business_key,source_key,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
    (outage,unit,tube,server.position_for(unit,tube),code,depth if tube==1 else None,'P1' if tube==1 else '', 'D',tube,'C3','SIMULATED.RPT','SIMULATED.ECT',key,key,'2026-11-01T00:00:00'))
 for outage in ['D101','D102','D103','D104']:
  for tube in range(1,51):
   if outage=='D102' and tube==1: continue
   if outage=='D104' and tube!=1: continue
   events=['replaced'] if (outage,tube) in [('D101',1),('D104',1)] else ['replaced','shifted'] if (outage,tube)==('D102',2) else []
   state='replaced' if events else 'normal'
   db.execute("INSERT INTO tube_states(outage,unit_id,thimble_id,state,events_json,offset_mm,offset_confirmed,note,source) VALUES(?,?,?,?,?,?,1,?,?)",
    (outage,1,tube,state,json.dumps(events),42 if 'shifted' in events else 0,'SIMULATED - not real inspection data','SIMULATED-MAINTENANCE.xlsx'))
`],{cwd:root,env,encoding:'utf8'});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
env.THIMBLE_PORT=String(socket.address().port);
await new Promise(resolve=>socket.close(resolve));
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const app=await _electron.launch({timeout:60000,executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu'],cwd:root,env});
let page;
const evidence={checks:[],errors:[],layouts:[],exports:[]};
const ready=()=>page.waitForFunction(()=>document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false');
const check=async(name,run)=>{
  if(process.env.THIMBLE_TEST_CHECK&&!name.includes(process.env.THIMBLE_TEST_CHECK))return;
  await run();evidence.checks.push(name);console.log('PASS',name);
};
const cell=tube=>page.locator(`#chart34 [data-tube="${tube}"]`);
async function chooseOutages(codes) {
  const picker=page.locator('.vw-replacement-picker');
  if(!await picker.evaluate(node=>node.open))await picker.locator('summary').click();
  await page.locator('[data-replacement-select=none]').click();
  for(const code of codes)await page.locator(`[data-replacement-outage="${code}"]`).check();
  await picker.locator('summary').click();
}
async function capture(name) {
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  await page.screenshot({path:path.join(output,name+'.png')});
}
try {
  page=await app.firstWindow();page.setDefaultTimeout(30000);await ensureLocalLogin(page);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await page.waitForFunction(()=>document.readyState==='complete');
  await app.evaluate(({BrowserWindow})=>{const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setContentSize(1440,1000);});
  await page.locator('[data-view=analytics]').click();await ready();
  const health=await page.evaluate(()=>window.api('/api/health'));
  assert.equal(path.resolve(health.db_path),env.THIMBLE_DB_PATH);
  await page.locator('#vwUnit').selectOption('D1');await ready();
  await check('Extension charts belong only to the trends navigation',async()=>{
    for(const tab of ['overview','tube','risk']) {
      await page.locator(`[data-analytics-tab="${tab}"]`).click();
      assert.equal(await page.locator('#panelTubeTrend').isVisible(),false);
      assert.equal(await page.locator('#panelDistCheck').isVisible(),false);
    }
    await page.locator('[data-analytics-tab=trends]').click();
    assert.equal(await page.locator('#panelTubeTrend').isVisible(),true);
    assert.equal(await page.locator('#panelDistCheck').isVisible(),true);
    assert.equal(await page.locator('#panelTubeTrend').count(),1);
    assert.equal(await page.locator('#panelDistCheck').count(),1);
  });
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('[name=vwPlateMode][value=replacement]').check();
  await check('All-outage replacement counts use explicit events and flag missing current records',async()=>{
    assert.match(await page.locator('#c34Tag').innerText(),/所选大修明确记录 3 次 · 全库累计 3 次/);
    assert.match(await page.locator('#vwReplacementAudit summary').innerText(),/所选大修 3 次明确换管记录 · 全库累计 3 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/全库历史累计[\s\S]*3 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/所选大修明细[\s\S]*3 次/);
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    assert.match(await cell(1).getAttribute('aria-label'),/明确换管至少 2 次.*资料不全/);
    assert.match(await cell(2).getAttribute('aria-label'),/明确换管至少 1 次/);
    assert.equal(await cell(3).locator('rect').getAttribute('fill'),'#e6ebef');
    assert.equal(await cell(1).locator('rect').getAttribute('stroke-dasharray'),'3 2');
    assert.match(await page.locator('#vwReplacementAudit summary').innerText(),/维护完整 2\/6 次/);
    assert.doesNotMatch(await page.locator('#c34Toolbar').innerText(),/全部已记录大修/);
  });
  await check('Chosen complete outages support exact zero; compound replacement counts once with provenance',async()=>{
    await chooseOutages(['D101','D103']);
    assert.match(await page.locator('#c34Tag').innerText(),/所选大修明确记录 1 次 · 全库累计 3 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/全库历史累计[\s\S]*3 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/所选大修明细[\s\S]*1 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/未选大修明细[\s\S]*2 次/);
    assert.doesNotMatch(await page.locator('#c34Tag').innerText(),/资料不全/);
    assert.equal(await cell(2).locator('rect').getAttribute('fill'),'#ffffff');
    assert.match(await cell(2).getAttribute('aria-label'),/明确换管 0 次.*完整/);
    await page.locator('#vwReplacementAudit summary').click();
    assert.match(await page.locator('#vwReplacementAudit tbody tr').last().innerText(),/D103.*无换管/);
    await page.locator('#vwReplacementAudit summary').click();
    await chooseOutages(['D102']);
    assert.match(await cell(1).getAttribute('aria-label'),/换管次数未确认.*资料不全/);
    await page.locator('.vw-replacement-picker summary').click();
    assert.match(await page.locator('.vw-replacement-picker-body').innerText(),/D105[\s\S]*换管记录缺失/);
    await cell(2).click();
    assert.equal(await page.locator('[data-replacement-record]').count(),1);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/D102.*换管/s);
    assert(page.locator('#vwTubeDetail').evaluate(node=>node.classList.contains('is-replacement-detail')));
    assert.match(await page.locator('#vwTubeDetail').innerText(),/SIMULATED - not real inspection data/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/记录索引 D102\/1\/2/);
    assert.doesNotMatch(await page.locator('#vwTubeDetail').innerText(),/最大报告深度|移位距离/);
  });
  await check('Zero-event scopes keep an empty plate with accurate explanations and no stale channel data',async()=>{
    const expectBlankPlate=async message=>{
      assert.equal(await page.locator('#chart34 svg').count(),1);
      assert.equal(await page.locator('#chart34 .vw-plate-grid rect').count(),157);
      assert.equal(await page.locator('#chart34 .vw-plate-outline').count(),1);
      assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
      assert.equal(await page.locator('#chart34 [data-tube] text').count(),50);
      assert.equal(await page.locator('#c34Legend .lb,[data-replacement-record]').count(),0);
      assert.match(await page.locator('#vwTubeDetail').innerText(),message);
      assert.match(await page.locator('#chart34 svg').getAttribute('data-empty-message'),message);
      await page.locator('#c34Note').evaluate(node=>{node.closest('details').open=true});
      assert.match(await page.locator('#c34Note').innerText(),/空白不表示零次换管/);
      assert.doesNotMatch(await page.locator('#c34Tag').innerText(),/共 0 次|0 根|0 条/);
      assert.doesNotMatch(await page.locator('#vwReplacementAudit summary').innerText(),/已记录换管 0 次|0\/0/);
    };
    await chooseOutages(['D103']);
    await expectBlankPlate(/维护资料完整，未记录换管事件/);
    assert.equal(await page.locator('#chart34 [data-tube="15"][data-position="N5"] text').textContent(),'15');
    await capture('empty-plate-complete-records');
    await chooseOutages(['D105']);
    await expectBlankPlate(/缺少维护记录/);
    await capture('empty-plate-incomplete-records');
    await chooseOutages([]);
    await expectBlankPlate(/请先选择大修/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/请选择大修/);
    await capture('empty-plate-no-selection');
    await page.locator('#vwUnit').selectOption('D2');await ready();
    await expectBlankPlate(/缺少维护记录/);
    assert.equal(await page.locator('#chart34 [data-tube="42"][data-position="N5"] text').textContent(),'42');
    assert.match(await page.locator('#vwReplacementAudit summary').innerText(),/维护资料不全/);
    for(const [width,theme] of [[1440,'light'],[800,'light'],[1440,'dark'],[800,'dark']]) {
      await app.evaluate(({BrowserWindow},width)=>BrowserWindow.getAllWindows()[0].setContentSize(width,900),width);
      await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
      await page.locator('#chart34').scrollIntoViewIfNeeded();
      await expectBlankPlate(/缺少维护记录/);
      const layout=await page.locator('#vwTube').evaluate(host=>{
        const chart=host.querySelector('#chart34').getBoundingClientRect();
        const svg=host.querySelector('#chart34 svg').getBoundingClientRect();
        const detail=host.querySelector('#vwTubeDetail').getBoundingClientRect();
        return {width:svg.width,height:svg.height,
          centered:Math.abs(svg.x+svg.width/2-chart.x-chart.width/2),
          separate:detail.left>=chart.right-1||detail.top>=chart.bottom-1,
          overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth};
      });
      assert(layout.width>200&&layout.height>200,JSON.stringify(layout));
      assert(layout.centered<2&&layout.separate&&layout.overflow<=1,JSON.stringify(layout));
      await capture(`empty-plate-${theme}-${width}`);
    }
    await page.evaluate(()=>window.appAppearance.setTheme('light'));
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1440,1000));
    await page.locator('#vwUnit').selectOption('D1');await ready();
    await chooseOutages(['D101']);
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    assert.equal(await page.locator('#chart34 svg[data-empty-message]').count(),0);
    assert.equal(await page.locator('#chart34 [aria-pressed=true]').count(),0);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/所选大修明细[\s\S]*1 次/);
  });
  await check('Cumulative scope stays explicit under a global filter; choosing one outage excludes future replacements',async()=>{
    await page.locator('#vwUnit').selectOption('D1');await ready();
    await page.locator('#vwOutage').selectOption('D101');await ready();
    assert.match(await page.locator('.vw-replacement-picker summary').innerText(),/6 次大修/);
    await chooseOutages(['D101']);
    assert.match(await page.locator('#c34Tag').innerText(),/D101.*所选大修明确记录 1 次/);
    assert.doesNotMatch(await cell(1).getAttribute('aria-label'),/D104/);
    await cell(1).click();
    assert.equal(await page.locator('[data-replacement-record]').count(),1);
    assert.equal(await page.locator('[data-replacement-record]').getAttribute('data-replacement-record'),'D101');
    await page.locator('#vwOutage').selectOption('');await ready();
  });
  await check('Historical maxima retain the peak report, and colors follow settings',async()=>{
    await page.locator('[name=vwPlateMode][value=depth]').check();
    await page.locator('#vwPlateOutage').selectOption('all');
    assert.match(await cell(1).getAttribute('aria-label'),/D103.*历史最大磨损 70%/);
    await cell(1).click();
    assert.match(await page.locator('#vwTubeDetail').innerText(),/最大值来源大修\s*D103/);
    await page.locator('#vwPlateOutage').selectOption('D102');
    assert.match(await cell(1).getAttribute('aria-label'),/D102.*最大磨损 20%/);
    await page.evaluate(()=>{
      localStorage.setItem('thimbleSeverityMidThreshold','15');
      localStorage.setItem('thimbleSeverityHighThreshold','65');
      localStorage.setItem('thimbleSeverityMidColor','#af7621');
      window.dispatchEvent(new Event('severity-settings-changed'));
    });
    assert.equal(await cell(1).locator('rect').getAttribute('fill'),'#af7621');
    assert.match(await page.locator('#c34Legend').innerText(),/15–<65%/);
    await page.locator('[name=vwPlateMode][value=coverage]').check();
    assert.match(await page.locator('#c34Toolbar').innerText(),/检测结论/);
  });
  await check('Maintenance-only outages keep all 50 channels without inventing inspection conclusions',async()=>{
    await page.locator('#vwPlateOutage').selectOption('D104');
    for(const mode of ['depth','coverage','state']) {
      await page.locator(`[name=vwPlateMode][value=${mode}]`).check();
      assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
      assert.match(await cell(1).getAttribute('aria-label'),/无检测记录/);
    }
    await cell(1).click();
    assert.match(await page.locator('#vwTubeDetail').innerText(),/换管/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/SIMULATED - not real inspection data/);
  });
  await check('Tube detail separates NDD from missing depth and never turns unknown replacement history into zero',async()=>{
    await page.locator('[name=vwPlateMode][value=depth]').check();
    await page.locator('#vwPlateOutage').selectOption('D101');
    assert.match(await cell(2).getAttribute('aria-label'),/NDD/);
    assert.doesNotMatch(await cell(2).getAttribute('aria-label'),/磨损 深度缺失/);
    await cell(2).click();
    assert.match(await page.locator('#vwTubeDetail').innerText(),/最大报告深度\s*NDD/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/全库历史累计换管\s*1 次/);
    assert.match(await page.locator('#vwTubeDetail').innerText(),/截至 D101 明细核查\s*明确换管 0 次/);
  });
  await check('Scope controls lead metrics; title and plate are centered at desktop, compact, and dark sizes',async()=>{
    await page.locator('[name=vwPlateMode][value=replacement]').check();
    await chooseOutages(['D101','D102','D103','D104']);
    for(const [width,height,theme] of [[1440,1000,'light'],[1000,800,'light'],[800,800,'light'],[1440,1000,'dark'],[800,800,'dark']]) {
      await app.evaluate(({BrowserWindow},{width,height})=>BrowserWindow.getAllWindows()[0].setContentSize(width,height),{width,height});
      await page.evaluate(theme=>window.appAppearance.setTheme(theme),theme);
      await page.locator('#c34Toolbar').scrollIntoViewIfNeeded();
      await page.waitForTimeout(250);
      const geometry=await page.locator('#vwTube').evaluate(host=>{
        const box=node=>node.getBoundingClientRect();
        const heading=box(host.querySelector('h2')),panel=box(host.querySelector('.panel'));
        const caption=box(host.querySelector('#c34Tag')),actions=box(host.querySelector('.vw-panel-actions'));
        const chart=box(host.querySelector('#chart34')),svg=box(host.querySelector('#chart34 svg'));
        const scope=box(host.querySelector('.vw-plate-scope')),metrics=box(host.querySelector('.vw-plate-modes'));
        return {titleOffset:Math.abs(heading.x+heading.width/2-panel.x-panel.width/2),
          plateOffset:Math.abs(svg.x+svg.width/2-chart.x-chart.width/2),
          scopeLeads:scope.top<metrics.top+2&&(Math.abs(scope.top-metrics.top)>3||scope.left<metrics.left),
          overflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,
          captionOverlapsActions:caption.left<actions.right&&caption.right>actions.left&&caption.top<actions.bottom&&caption.bottom>actions.top,
          viewport:innerWidth};
      });
      assert(geometry.titleOffset<2,JSON.stringify(geometry));
      assert(geometry.plateOffset<2,JSON.stringify(geometry));
      assert(geometry.scopeLeads,JSON.stringify(geometry));
      assert(geometry.overflow<=1,JSON.stringify(geometry));
      assert.equal(geometry.captionOverlapsActions,false,JSON.stringify(geometry));
      evidence.layouts.push({width,height,theme,...geometry});
      await capture(`plate-${theme}-${width}`);
    }
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1440,1000));
    await page.evaluate(()=>window.appAppearance.setTheme('light'));
    await page.locator('#vwReplacementAudit summary').click();
    await page.locator('#vwReplacementAudit').scrollIntoViewIfNeeded();
    await page.locator('.vw-replacement-picker summary').click();
    await capture('outage-picker-and-audit');
    await page.locator('.vw-replacement-picker summary').click();
    await cell(1).click();
    await page.locator('#vwTubeDetail').scrollIntoViewIfNeeded();
    await capture('replacement-evidence');
  });
  await check('Real PNG exports include selected scope and incomplete-data caveats and open as nonblank images',async()=>{
    await page.evaluate(()=>window.appAppearance.setTheme('light'));
    await app.evaluate(({dialog},output)=>{
      globalThis.plateExportPaths=[];
      dialog.showSaveDialog=async (...args)=>{
        const options=args.at(-1);
        const filename=options.defaultPath.split(/[\\\\/]/).at(-1);
        const filePath=output+'/'+filename;globalThis.plateExportPaths.push(filePath);
        return {canceled:false,filePath};
      };
    },output);
    const cases=[
      {codes:['D101','D103'],incomplete:false},
      {codes:['D101','D102','D103'],incomplete:true},
      {codes:['D103'],incomplete:false,blank:true},
      {codes:['D105'],incomplete:true,blank:true},
      {codes:[],incomplete:false,blank:true}
    ];
    await page.evaluate(()=>{
      const original=CanvasRenderingContext2D.prototype.fillText;
      window.__plateExportText=[];
      CanvasRenderingContext2D.prototype.fillText=function(text,...args){
        window.__plateExportText.push(String(text));
        return original.call(this,text,...args);
      };
    });
    for(const [index,{codes,incomplete,blank}] of cases.entries()) {
      await chooseOutages(codes);
      await page.evaluate(()=>{window.__plateExportText=[]});
      await page.locator('#vwTube .vw-export').click();
      await page.waitForFunction(()=>!document.querySelector('#vwTube .vw-export').classList.contains('is-busy'));
      const files=await app.evaluate(()=>globalThis.plateExportPaths);
      assert.equal(files.length,index+1);
      const file=files[index];
      const labels=await page.evaluate(()=>window.__plateExportText.join(''));
      for(const code of codes)assert(file.includes(code),file);
      assert.doesNotMatch(path.basename(file),/维护资料不全|仅为已记录次数|暂无明确换管记录/,
        'Completeness explanations must be retained in the image without expanding the filename');
      if(incomplete)assert.match(labels,/维护资料不全/);
      else assert.doesNotMatch(labels,/维护资料不全/);
      if(blank)assert.match(labels,codes.length?/暂无明确换管记录/:/未选择大修/);
      if(!codes.length)assert.equal((path.basename(file).match(/未选择大修/g)||[]).length,1);
      assert(fs.statSync(file).size>15000);
      const image=await app.evaluate(({nativeImage},file)=>{
        const image=nativeImage.createFromPath(file);
        const bitmap=image.toBitmap();let nonWhite=0;
        for(let index=0;index<bitmap.length;index+=4)if(bitmap[index]<220||bitmap[index+1]<220||bitmap[index+2]<220)nonWhite++;
        const {width,height}=image.getSize();
        const footer=image.crop({x:0,y:height-80,width,height:80}).toBitmap();
        let footerInk=0;
        for(let index=0;index<footer.length;index+=4)
          if(footer[index]<220||footer[index+1]<220||footer[index+2]<220)footerInk++;
        return {empty:image.isEmpty(),width,height,nonWhite,footerInk};
      },file);
      assert.equal(image.empty,false);assert(image.width>=1000&&image.nonWhite>5000);
      if(blank)assert(image.footerInk>100,'Exported empty plates retain their explanatory caption');
      evidence.exports.push({file,labels,...image});
    }
  });
  await check('An empty base never claims complete records or retains stale plates and replacement evidence',async()=>{
    await page.locator('[data-base=LF]').click();await ready();
    await page.locator('[data-analytics-tab=overview]').click();
    assert.match(await page.locator('#analysisAlerts summary').innerText(),/当前范围暂无数据/);
    assert.match(await page.locator('[data-insight=quality]').innerText(),/当前范围暂无数据/);
    assert.doesNotMatch(await page.locator('#vwOverviewSummary').innerText(),/检测记录齐全/);
    assert.equal(await page.locator('#chart34 [data-tube]').count(),0);
    assert.equal(await page.locator('[data-replacement-record]').count(),0);
    await capture('empty-base-no-false-completeness');
  });
  await check('Failed reload clears prior metrics, audits, and charts until a successful retry',async()=>{
    await page.locator('#vwReset').click();await ready();
    await page.locator('#vwUnit').selectOption('D1');await ready();
    await page.locator('[data-analytics-tab=tube]').click();
    await page.locator('[name=vwPlateMode][value=replacement]').check();
    await cell(1).click();
    assert(await page.locator('[data-replacement-record]').count()>0);
    await page.route('**/api/analysis/visualization?*',route=>route.fulfill({
      status:503,json:{error:'SIMULATED reload failure'}
    }));
    await page.locator('#vwRefresh').click();await ready();
    assert.match(await page.locator('#analysisAlerts').innerText(),/可视化数据加载失败.*SIMULATED reload failure/);
    assert.equal(await page.locator('#vizRetry').count(),1);
    assert.equal(await page.locator('#vwReplacementAudit table').count(),0);
    assert.equal(await page.locator('[data-replacement-record]').count(),0);
    assert.equal(await page.locator('#vwOverviewSummary [data-metric]').count(),0);
    assert.equal(await page.locator('#chart34 svg,#chartTubeTrend svg,#chartDistHistogram svg').count(),0);
    await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1100,800));
    await page.waitForTimeout(250);
    await page.locator('[data-analytics-tab=overview]').click();
    await page.locator('[data-analytics-tab=tube]').click();
    assert.equal(await page.locator('#chart34 svg').count(),0,'Resize and navigation cannot restore stale data');
    await page.locator('#vwTube .vw-export').click();
    await page.locator('#toast').getByText('数据尚未加载，请先重新加载',{exact:true}).waitFor({state:'visible'});
    await capture('failed-reload-no-stale-data');
    await page.unroute('**/api/analysis/visualization?*');
    await page.locator('#vizRetry').click();await ready();
    assert.equal(await page.locator('#chart34 [data-tube]').count(),50);
    assert.equal(await page.locator('#vwReplacementAudit tbody tr').count(),6);
    assert.equal(await page.locator('#vizRetry').count(),0);
  });
  assert.deepEqual(evidence.errors,[]);
  assert.equal(hash(),before,'Real database must not be changed');
  evidence.sourceUnchanged=true;evidence.passed=true;
} catch(error) {
  evidence.failure=error.stack;await capture('failure').catch(()=>{});throw error;
} finally {
  fs.writeFileSync(path.join(output,'verification.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);await app.close();
}
