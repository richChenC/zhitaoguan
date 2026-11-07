import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.resolve(root,'../../05_测试与验证/03_自动化临时产物'),`record-header-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const socket=net.createServer();
await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));
const port=socket.address().port;
await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const app=await _electron.launch({
  executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),
    THIMBLE_PYTHON:path.join(root,'.venv/Scripts/python.exe'),
    THIMBLE_DB_PATH:path.join(output,'data/test.db'),THIMBLE_DATA_DIR:path.join(output,'data'),
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')}
});
try {
  const page=await app.firstWindow();
  page.setDefaultTimeout(30000);
  await ensureLocalLogin(page);
  await page.locator('[data-workspace-columns=focus]').waitFor();
  await page.waitForFunction(()=>document.querySelector('#rows')?.getAttribute('aria-busy')!=='true');
  for (const width of [1186,1600]) {
    await app.evaluate(({BrowserWindow},width)=>{
      const win=BrowserWindow.getAllWindows()[0];
      win.unmaximize();win.setMinimumSize(320,480);win.setContentSize(width,1000);
    },width);
    for (const mode of ['focus','all']) {
      await page.locator(`[data-workspace-columns=${mode}]`).click();
      await page.evaluate(()=>{
        const body=document.querySelector('#rows');
        body.innerHTML='<tr><td colspan="18">empty</td></tr>';
      });
      await page.waitForFunction(mode=>document.querySelector('#rows td').colSpan===(mode==='focus'?10:18),mode);
      const empty=await page.locator('#workspace .table-panel table').evaluate(table=>{
        const headers=[...table.querySelectorAll('th')].filter(th=>getComputedStyle(th).display!=='none');
        const tableRect=table.getBoundingClientRect(),last=headers.at(-1).getBoundingClientRect();
        return {count:headers.length,tableRight:tableRect.right,lastRight:last.right,
          font:getComputedStyle(headers[0]).fontSize};
      });
      assert.equal(empty.count,mode==='focus'?10:18);
      assert(Math.abs(empty.tableRight-empty.lastRight)<2,JSON.stringify({width,mode,empty}));
      assert.equal(empty.font,'12px');
      await page.evaluate(()=>{
        document.querySelector('#rows').innerHTML='<tr>'+Array.from({length:18},(_,i)=>`<td>value ${i+1}</td>`).join('')+'</tr>';
      });
      const layout=await page.locator('#workspace .table-panel table').evaluate(table=>{
        const headers=[...table.querySelectorAll('th')],cells=[...table.querySelectorAll('#rows td')];
        return headers.map((header,index)=>{
          if (getComputedStyle(header).display==='none') return null;
          const h=header.getBoundingClientRect(),c=cells[index].getBoundingClientRect();
          return {index,left:Math.abs(h.left-c.left),right:Math.abs(h.right-c.right)};
        }).filter(Boolean);
      });
      assert(layout.every(column=>column.left<1&&column.right<1),JSON.stringify({width,mode,layout}));
      if (mode==='all') {
        assert(await page.locator('#workspace .table-panel .table-wrap').evaluate(node=>node.scrollWidth>node.clientWidth));
      }
      await page.screenshot({path:path.join(output,`${mode}-${width}.png`)});
      console.log(`PASS ${mode} ${width}px: empty and populated columns align`);
    }
  }
  await page.locator('[data-workspace-columns=focus]').click();
  let requested='';
  await page.route('**/api/findings?*',route=>{
    requested=route.request().url();
    return route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({items:[],core_items:[],total:0,page:1,pages:1,size:100})});
  });
  await page.locator('[data-column-filter=position]').click();
  await page.locator('#workspaceColumnFilter input').fill('N5');
  await page.locator('#workspaceColumnFilter button[type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('[data-column-filter=position]').getAttribute('aria-pressed')==='true');
  await page.waitForFunction(()=>document.querySelector('#rows').getAttribute('aria-busy')!=='true');
  assert.equal(new URL(requested).searchParams.get('column_position'),'N5');
  await page.locator('[data-column-filter=position]').click();
  await page.locator('#workspaceColumnFilter .column-filter-actions button').first().click();
  await page.waitForFunction(()=>document.querySelector('[data-column-filter=position]').getAttribute('aria-pressed')==='false');
  console.log('PASS column filter applies and clears through the desktop UI');
} finally {
  await app.close();
}
