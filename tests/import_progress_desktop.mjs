import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const runtime = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {chromium} = await import(pathToFileURL(path.join(runtime, 'playwright/index.mjs')).href);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-live-progress-'));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), 'live-import-progress');
fs.mkdirSync(output, {recursive: true});
const socket = net.createServer();
await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const fixture = path.join(temp, 'two-sheets.xlsx');
const server = spawn(path.join(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', '-c', `
from openpyxl import Workbook
from src.backend import server
import time
book=Workbook()
for index,count in enumerate([80,120]):
 sheet=book.active if index==0 else book.create_sheet()
 sheet.title=f"检测明细{index+1}"
 sheet.append(["大修号","机组号","通道编号","幅值","三字码","数据流水号"])
 for row in range(count):
  sheet.append(["H209",2,row%50+1,1,"WAR",index*1000+row])
book.save(${JSON.stringify(fixture)})
book.close()
original=server.import_audit.finding_source
def slow_source(*args,**kwargs):
 original(*args,**kwargs)
 time.sleep(.015)
server.import_audit.finding_source=slow_source
server.main()
`], {cwd: root, env: {...process.env, THIMBLE_PORT: String(port), THIMBLE_DATA_DIR:temp,
  THIMBLE_DB_PATH: path.join(temp, 'test.db'), THIMBLE_LOG_PATH: path.join(temp, 'service.log'),
  THIMBLE_OUTPUT_DIR: path.join(temp, 'exports'), THIMBLE_REPORT_DIR: path.join(temp, 'reports')},
stdio: 'ignore'});
let browser;
try {
  const base = `http://127.0.0.1:${port}`;
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null) throw new Error('Progress fixture service exited');
    try { ready = (await fetch(base + '/api/health')).ok; } catch {}
    if (ready) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(ready, 'Progress fixture service did not start');
  browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const samples = [];
  page.on('response', async response => {
    if (!response.url().includes('/api/import-progress?') || !response.ok()) return;
    const value = await response.json().catch(() => null);
    if (value?.stage?.startsWith('写入检测记录')) samples.push(value);
  });
  await page.addInitScript(() => {
    window.__overallSamples=[];
    new MutationObserver(() => {
      const panel=document.querySelector('#importProgressPanel');
      const track=document.querySelector('#importProgressTrack');
      if(panel&&!panel.hidden&&track?.hasAttribute('aria-valuenow'))
        window.__overallSamples.push(Number(track.getAttribute('aria-valuenow')));
    }).observe(document,{subtree:true,attributes:true,attributeFilter:['aria-valuenow']});
  });
  await page.addInitScript(fixture => {window.desktopAPI = {selectExcel: async () => [fixture]};}, fixture);
  await page.goto(base);
  await ensureLocalLogin(page);
  await page.locator('#openImportFlow').waitFor();
  await page.locator('#openImportFlow').click();
  await page.locator('#selectExcelBtn').click();
  await page.locator('#excelFileList .excel-file-chip').waitFor();
  await page.locator('#runImport').click();
  await page.waitForFunction(() => document.querySelector('#importProgressLabel').textContent.includes('写入检测记录'));
  await page.waitForFunction(() => /已处理 \d+ \/ (80|120) 行/.test(document.querySelector('#importProgressMeta').textContent));
  const visible = await page.locator('#importProgressPanel').evaluate(panel => ({
    label: panel.querySelector('#importProgressLabel').textContent,
    percent: panel.querySelector('#importProgressPercent').textContent,
    counts: panel.querySelector('#importProgressMeta').textContent,
    timing: panel.querySelector('#importProgressEta').textContent,
  }));
  assert.match(visible.percent, /^\d+%$/);
  assert.match(visible.timing, /预计剩余/);
  await page.screenshot({path: path.join(output, 'live-row-counts.png')});
  await page.setViewportSize({width: 390, height: 844});
  const layout = await page.locator('#importProgressPanel').evaluate(panel => {
    const bounds = panel.getBoundingClientRect();
    return [...panel.querySelectorAll('#importProgressLabel,#importProgressMeta,#importProgressPercent,#importProgressEta')]
      .filter(node => node.getClientRects().length).map(node => {
        const rect = node.getBoundingClientRect();
        return {id: node.id, outside: rect.left < bounds.left || rect.right > bounds.right + 1,
          overflow: node.scrollWidth > node.clientWidth + 1};
      });
  });
  assert(layout.every(item => !item.outside && !item.overflow), JSON.stringify(layout));
  await page.screenshot({path: path.join(output, 'live-row-counts-narrow.png')});
  await page.waitForFunction(() => document.querySelector('#importStatus').textContent.includes('Excel 导入完成'));
  assert.match(await page.locator('#importStatus').textContent(), /新增 200 条/);
  assert.match(await page.locator('#importStatus').textContent(), /2 张数据表/);
  assert(new Set(samples.map(sample => `${sample.stage}:${sample.completed}`)).size >= 5, JSON.stringify(samples));
  assert(samples.some(sample => sample.total === 80) && samples.some(sample => sample.total === 120), 'Both worksheets need real counters');
  const overall=await page.evaluate(()=>window.__overallSamples);
  assert(overall.length>5,JSON.stringify(overall));
  assert.deepEqual(overall,[...overall].sort((a,b)=>a-b),'Overall percent must never restart at the next worksheet');
  assert(samples.every(sample=>sample.percent>35&&sample.percent<100));
  assert.equal(overall.at(-1),100);
  assert.equal(await page.locator('#runImport').isDisabled(),true,'Completed files must not be imported again by another click');
  assert.equal(await page.locator('#importStatus').getAttribute('data-outcome'),'success');
  const count = samples.length;
  await page.waitForTimeout(1000);
  assert.equal(samples.length, count, 'Progress polling must stop after the import');
  assert.equal(await page.locator('#importProgressPanel').isVisible(), false);
  assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify({passed: true, visible, samples, overall, layout, errors}, null, 2));
  console.log(JSON.stringify({passed: true, visible, updates: samples.length, output}, null, 2));
} finally {
  await browser?.close();
  server.kill();
  await new Promise(resolve => {
    if (server.exitCode !== null) return resolve();
    server.once('exit', resolve);
  });
}
