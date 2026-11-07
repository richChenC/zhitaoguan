import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_NIGHT_OUTPUT_ROOT || process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `night-workspaces-${Date.now()}`);
const source = path.join(root, 'data', 'thimble.db');
const database = path.join(output, 'data', 'thimble.db');
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const hash = () => createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before = hash();
const evidence = {checks:[], errors:[]};
fs.mkdirSync(path.dirname(database), {recursive:true});
execFileSync(python, ['-X','utf8','-c', `import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`, source, database]);
const socket = net.createServer();
await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(runtime).href);
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  executablePath:packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:[...(packaged ? [] : [root]), '--disable-gpu'], cwd:root,
  env:{...process.env, PYTHONIOENCODING:'utf-8', PYTHONUNBUFFERED:'1',
    THIMBLE_ALLOW_MULTI_INSTANCE:'1', THIMBLE_PORT:String(port), THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:database, THIMBLE_DATA_DIR:path.dirname(database),
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'), THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'server.log')},
});
if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
const page = await app.firstWindow();
page.setDefaultTimeout(35000);
page.on('pageerror', error => evidence.errors.push(error.message));
let settingsPage;
async function openSettings(section){
  settingsPage=app.windows().find(candidate=>candidate.url().includes('window=settings'));
  if(settingsPage){await settingsPage.locator(`[data-settings-pane="${section}"]`).click();return settingsPage;}
  const opened=app.waitForEvent('window');
  await page.locator('[data-open-settings]').click();
  settingsPage=await opened;settingsPage.setDefaultTimeout(35000);
  await settingsPage.locator('#settings').waitFor();
  await settingsPage.locator(`[data-settings-pane="${section}"]`).click();
  return settingsPage;
}

async function capture(name) {
  const image = await app.evaluate(async ({BrowserWindow}) =>
    (await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output, `${name}.png`), Buffer.from(image, 'base64'));
}

async function inspect(name, selector) {
  await page.waitForTimeout(200);
  const sample = await page.locator(selector).evaluate(host => {
    const parse = value => {
      const parts = value.match(/[\d.]+/g)?.map(Number);
      return parts?.length >= 3 ? [...parts.slice(0,3),parts[3] ?? 1] : [0,0,0,0];
    };
    const blend = (a,b) => a.slice(0,3).map((v,i)=>v*a[3]+b[i]*(1-a[3]));
    const luminance = color => color.map(v=>v/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4)
      .reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
    const nodes = [...host.querySelectorAll('*')].filter(node =>
      node instanceof HTMLElement && node.checkVisibility() && !node.closest(':disabled') &&
      [...node.childNodes].some(child=>child.nodeType===Node.TEXT_NODE && child.textContent.trim()));
    const contrast = nodes.map(node => {
      const layers = [];
      for (let parent=node; parent; parent=parent.parentElement) layers.unshift(parse(getComputedStyle(parent).backgroundColor));
      const background = layers.reduce((base,layer)=>blend(layer,base),[255,255,255]);
      const style = getComputedStyle(node), foreground = blend(parse(style.color),background);
      const values = [luminance(foreground),luminance(background)].sort((a,b)=>a-b);
      const parents = [];
      for (let parent=node.parentElement; parent && parents.length<3; parent=parent.parentElement)
        parents.push(parent.id ? `#${parent.id}` : `${parent.tagName}.${String(parent.className).replaceAll(' ','.')}`);
      return {tag:node.tagName,id:node.id,class:node.className,parents,text:node.textContent.trim().slice(0,80),
        color:style.color,background,ratio:(values[1]+0.05)/(values[0]+0.05)};
    });
    const surfaces=[...host.querySelectorAll('#c32Toolbar select,#c32Legend .lb,#vwTubeDetail th')]
      .filter(node=>node.checkVisibility()).map(node=>{
        const style=getComputedStyle(node),color=parse(style.backgroundColor);
        return {tag:node.tagName,text:node.textContent.trim(),background:style.backgroundColor,
          opaque:color[3]===1,luminance:luminance(color.slice(0,3))};
      });
    return {contrast,surfaces,width:innerWidth,height:innerHeight,overflow:document.querySelector('main').scrollWidth-
      document.querySelector('main').clientWidth};
  });
  evidence.checks.push({name,...sample});
  const failures = sample.contrast.filter(item=>item.ratio<4.5);
  console.log(name, JSON.stringify({samples:sample.contrast.length,failures:failures.length,overflow:sample.overflow}));
  if (failures.length) console.log(JSON.stringify(failures.slice(0,18)));
  await capture(name);
}

const ready = () => page.waitForFunction(() =>
  document.querySelector('.official-viz')?.getAttribute('aria-busy')==='false' &&
  document.querySelector('#chart34 svg'));

try {
  await ensureLocalLogin(page);
  await page.locator('#rows tr[data-i]').first().waitFor();
  await app.evaluate(({BrowserWindow}) => {
    const win=BrowserWindow.getAllWindows()[0];win.unmaximize();win.setSize(1440,900);
  });
  await page.evaluate(()=>window.appAppearance.setTheme('dark'));
  await page.locator('#rows .ledger-editable').first().hover();
  await inspect('01-workbench-dark','#workspace');
  await page.locator('#rows input[type=checkbox]').first().check();
  await inspect('02-workbench-selected-dark','#workspace');
  await page.locator('[data-view=analytics]').click();
  await ready();
  await inspect('03-overview-dark','#analytics');
  const history = page.locator('.vw-unit-history').first();
  await history.locator(':scope > summary').click();
  const outage = history.locator('.vw-outage-row').last();
  await outage.locator(':scope > summary').click();
  await outage.scrollIntoViewIfNeeded();
  await inspect('04-history-dark','#analytics');
  await page.locator('#vwRefresh').click();await ready();
  assert(await history.evaluate(node=>node.open),'Refresh must preserve expanded history');
  const coverage=page.locator('.vw-coverage-disclosure');
  evidence.coverageVisible=await coverage.isVisible();
  if(evidence.coverageVisible) {
    await coverage.locator(':scope > summary').click();
    await page.locator('.vw-audit > summary').click();
    await coverage.scrollIntoViewIfNeeded();
    await inspect('14-coverage-audit-dark','#analytics');
  }
  await page.locator('[data-analytics-tab=trends]').click();
  await inspect('15-position-dark','#analytics');
  await page.locator('[data-analytics-tab=tube]').click();
  await page.locator('#chart34 [data-tube]').first().click();
  await page.locator('#vwTubeDetail').scrollIntoViewIfNeeded();
  await inspect('05-tube-dark','#analytics');
  const detailHistory=page.locator('#vwTubeDetail details').first();
  if (await detailHistory.count()) await detailHistory.locator('summary').first().click();
  await page.locator('.vw-tube-history > summary').click();
  await inspect('06-tube-history-dark','#analytics');
  for(const mode of ['state','coverage']) {
    await page.locator(`[name=vwPlateMode][value=${mode}]`).check({force:true});
    await inspect(`16-plate-${mode}-dark`,'#analytics');
  }
  await page.locator('[name=vwPlateMode][value=depth]').check({force:true});
  await page.locator('[data-view=workspace]').click();
  await page.locator('[data-view=analytics]').click();
  assert.equal(await page.locator('[data-analytics-tab=tube]').getAttribute('aria-selected'),'true');
  // Report generation is a primary workspace, separate from software settings.
  await page.locator('[data-view=reports]').click();
  await page.locator('#rcCatalogStatus').filter({hasText:'表式已就绪'}).waitFor();
  await page.screenshot({path:path.join(output,'07-report-center-dark.png')});
  await app.evaluate(({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'));
    win.setSize(1040,760);win.webContents.setZoomFactor(1.25);
  });
  await page.screenshot({path:path.join(output,'10-report-zoom-dark.png')});
  await app.evaluate(({BrowserWindow})=>{
    const win=BrowserWindow.getAllWindows().find(item=>!item.webContents.getURL().includes('window=settings'));
    win.setSize(1040,760);win.webContents.setZoomFactor(1.25);
  });
  await page.locator('[data-view=analytics]').click();
  await inspect('11-tube-zoom-dark','#analytics');
  await page.locator('[data-analytics-tab=overview]').click();
  await inspect('12-overview-zoom-dark','#analytics');
  await page.locator('[data-view=workspace]').click();
  await inspect('13-workbench-zoom-dark','#workspace');
  await page.evaluate(()=>window.appAppearance.setTheme('light'));
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.waitForFunction(()=>getComputedStyle(document.body).backgroundColor
    .match(/\d+/g)?.slice(0,3).every(value=>Number(value)>180));
  await page.waitForTimeout(250);
  evidence.lightBackground=await page.evaluate(()=>getComputedStyle(document.body).backgroundColor);
  await capture('19-workbench-light');
  assert.deepEqual(evidence.errors,[]);
  const failures=evidence.checks.flatMap(check=>check.contrast.filter(item=>item.ratio<4.5)
    .map(item=>({name:check.name,...item})));
  assert.equal(failures.length,0,`Night mode has ${failures.length} low-contrast text samples: ${
    failures.slice(0,6).map(item=>`${item.name}: ${item.text} (${item.ratio.toFixed(2)})`).join('; ')}`);
  const surfaces=evidence.checks.flatMap(check=>check.surfaces);
  assert(surfaces.length>0,'Expanded charts must include theme surface checks');
  assert(surfaces.every(item=>item.opaque&&item.luminance<0.2),
    'Chart filters, legend labels and history headers must use dark surfaces');
  assert(evidence.checks.every(check=>check.overflow<=2),'Workspace must not overflow the main scroller');
  evidence.passed=true;
} catch (error) {
  evidence.failure=error.stack;
  await capture('failure').catch(()=>{});
  throw error;
} finally {
  await app.close();
  evidence.sourceUnchanged=hash()===before;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.sourceUnchanged,'Original database must remain unchanged');
}
