import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Run against an isolated service: this test intercepts reads and never imports data.
const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
fs.mkdirSync('tmp/browser', { recursive: true });
const base = process.env.THIMBLE_TEST_URL || 'http://127.0.0.1:8877';
const combinations = [
  { site: 'H', unit_id: 1, outage: 'H101' },
  { site: 'H', unit_id: 2, outage: 'H201' },
  { site: 'F', unit_id: 1, outage: 'F101' },
];
const records = Array.from({ length: 42 }, (_, index) => {
  const scope = index < 40 ? combinations[0] : combinations[index - 39];
  return {
    ...scope, id: index + 1, site_code: scope.site, thimble_id: index % 2 + 1,
    position: index % 2 ? 'G14' : 'L11', indication: 'WAR', percent: 25,
    volts: 1.2, location: 'P1', channel: 'P1: 4-6', analyst: '核查人员',
  };
});
let mode = 'empty', fail = false, overviewFail = false, reads = [];
let releaseOverview;
let releaseNavigationRequest;
const overviewGate = new Promise(resolve => { releaseOverview = resolve; });
let holdOverview = true, releaseSlow, slowStarted;
let slowGate, slowSignal;
const json = data => ({ contentType: 'application/json', body: JSON.stringify(data) });
await page.route('**/api/overview', async route => {
  if (holdOverview) await overviewGate;
  if (overviewFail) return route.fulfill({ status: 503, ...json({ error: '测试：服务不可用' }) });
  const empty = mode === 'empty';
  return route.fulfill(json({
    stats: { findings: empty ? 0 : records.length, outages: empty ? 0 : 3, units: empty ? 0 : 2, analysts: empty ? 0 : 1 },
    sites: empty ? [] : ['H', 'F'], units: empty ? [] : [1, 2],
    outages: empty ? [] : ['H201', 'H101', 'F101'],
    combinations: empty ? [] : combinations, history: [],
  }));
});
await page.route('**/api/findings?*', async route => {
  const p = new URL(route.request().url()).searchParams;
  reads.push(Object.fromEntries(p));
  if (p.get('analyst') === 'slow') {
    slowStarted();
    await slowGate;
    return route.fulfill(json({ items: [], core_items: [], total: 0, page: 1, pages: 1, size: 50 })).catch(() => {});
  }
  if (fail) return route.fulfill({ status: 503, ...json({ error: '测试：服务不可用' }) });
  const items = (mode === 'empty' ? [] : records).filter(row =>
    (!p.get('site') || row.site === p.get('site')) &&
    (!p.get('unit') || String(row.unit_id) === p.get('unit')) &&
    (!p.get('outage') || row.outage === p.get('outage')) &&
    (!p.get('analyst') || row.analyst.includes(p.get('analyst'))) &&
    (!p.get('thimble') || String(row.thimble_id) === p.get('thimble'))
  );
  const size = Number(p.get('size')), pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(pages, Number(p.get('page')));
  return route.fulfill(json({ items: items.slice((current - 1) * size, current * size), core_items: items, total: items.length, page: current, pages, size }));
});
const textIs = (selector, expected) => page.waitForFunction(({ selector, expected }) =>
  document.querySelector(selector)?.textContent.includes(expected), { selector, expected });
try {
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__thimbleState);
  assert.equal(reads.length, 0, 'records must wait for overview before classifying an empty database');
  holdOverview = false; releaseOverview();
  await textIs('#workspaceEmptyNotice', '尚未导入检测记录');
  assert.equal(await page.locator('#selectAllRows').isDisabled(), true);
  await page.locator('#workspaceEmptyNotice button').click();
  assert.equal(await page.locator('#importDialog').evaluate(dialog => dialog.open), true);
  await page.evaluate(() => window.toast('弹窗内通知布局核验',{type:'warning',duration:60000}));
  const modalFeedback = await page.locator('#toast').evaluate(host => {
    const toast = host.getBoundingClientRect(), actions = document.querySelector('#importDialog .dialog-actions').getBoundingClientRect();
    return {
      inDialog: host.parentElement === document.querySelector('#importDialog form'),
      visible: !!host.getClientRects().length,
      inDialogBounds: toast.top >= document.querySelector('#importDialog').getBoundingClientRect().top &&
        toast.bottom <= document.querySelector('#importDialog').getBoundingClientRect().bottom + 1,
      overlapsActions: toast.left < actions.right && toast.right > actions.left && toast.top < actions.bottom && toast.bottom > actions.top,
    };
  });
  assert.equal(modalFeedback.inDialog, true);
  assert.equal(modalFeedback.visible, true);
  assert.equal(modalFeedback.inDialogBounds, true);
  assert.equal(modalFeedback.overlapsActions, false, 'modal notifications must not cover dialog actions');
  await page.locator('#importDialog').evaluate(dialog => dialog.close());
  await page.waitForFunction(() => document.querySelector('#toast').parentElement === document.body);
  await page.locator('#toast button').click();
  await page.screenshot({ path: 'tmp/browser/workspace-empty.png', fullPage: true });

  mode = 'data';
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.locator('#pageSize').selectOption('20');
  await textIs('#pageInfo', '1 / 3');
  await page.locator('#site').selectOption('H');
  await page.locator('#unit').selectOption('1');
  await page.locator('#outage').selectOption('H101');
  await textIs('#resultInfo', '共 40 条');
  await page.locator('#rows input').first().check();
  await textIs('#detail', '已勾选 1 条记录');
  assert.equal(await page.locator('#clearPageSelection').isDisabled(), false);
  await page.locator('#nextBtn').click();
  await textIs('#pageInfo', '2 / 2');
  await textIs('#detail', '已勾选 1 条记录');
  assert.equal(await page.evaluate(() => window.__thimbleState.selectedRecords.size), 1, 'selection and details must survive paging');
  await page.locator('#prevBtn').click();
  await textIs('#pageInfo', '1 / 2');
  assert.equal(await page.locator('#rows input').first().isChecked(), true);

  reads = [];
  await page.locator('#unit').selectOption('2');
  await textIs('#resultInfo', '共 1 条');
  assert.equal(reads.length, 1, 'unit change must send one consistent request');
  assert.equal(reads[0].unit, '2');
  assert.equal(reads[0].outage, undefined, 'outage from the previous unit must be cleared before requesting records');
  assert.equal(await page.evaluate(() => window.__thimbleState.selectedRecords.size), 0);
  await page.locator('#analyst').fill('无匹配');
  await page.locator('#analyst').press('Enter');
  await textIs('#workspaceEmptyNotice', '没有匹配的检测记录');
  await page.locator('#pageSize').selectOption('50');
  await textIs('#workspaceEmptyNotice', '没有匹配的检测记录');
  await page.locator('#workspaceEmptyNotice button').click();
  await textIs('#resultInfo', '共 42 条');
  assert.equal(await page.locator('#pageSize').inputValue(), '50', 'reset must preserve the selected page size');
  assert.equal(await page.locator('#unit option').count(), 3, 'reset must rebuild unit options for all bases');
  await page.screenshot({ path: 'tmp/browser/workspace-recovered.png', fullPage: true });

  slowGate = new Promise(resolve => { releaseSlow = resolve; });
  slowSignal = new Promise(resolve => { slowStarted = resolve; });
  await page.locator('#analyst').fill('slow');
  await page.locator('#analyst').press('Enter');
  await slowSignal;
  assert.equal(await page.locator('#selectAllRows').isDisabled(), true);
  await page.locator('#analyst').fill('核查人员');
  await page.locator('#analyst').press('Enter');
  await textIs('#resultInfo', '共 42 条');
  releaseSlow();
  await page.waitForLoadState('networkidle');
  assert.equal(await page.locator('#rows tr[data-i]').count(), 42, 'a stale response must never replace the latest results');

  await page.locator('#rows input').first().check();
  fail = true;
  await page.locator('#searchBtn').click();
  await textIs('#rows', '检测记录加载失败');
  assert.equal(await page.evaluate(() => window.__thimbleState.items.length), 0);
  assert.equal(await page.evaluate(() => window.__thimbleState.selectedRecords.size), 0);
  assert.equal(await page.locator('#selectAllRows').isDisabled(), true);
  assert.equal(await page.locator('#nextBtn').isDisabled(), true);
  await page.screenshot({ path: 'tmp/browser/workspace-load-error.png', fullPage: true });
  fail = false;
  await page.locator('#workspaceEmptyNotice button').click();
  await textIs('#resultInfo', '共 42 条');

  let navigationRequestStarted;
  const navigationGate = new Promise(resolve => { releaseNavigationRequest = resolve; });
  const navigationStarted = new Promise(resolve => { navigationRequestStarted = resolve; });
  await page.route('**/api/navigation-feedback-short', async route => {
    await new Promise(resolve => setTimeout(resolve, 120));
    return route.fulfill(json({ ok: true }));
  });
  await page.evaluate(() => { window.__shortNavigationRequest = fetch('/api/navigation-feedback-short').then(response => response.json()); });
  await page.waitForTimeout(60);
  assert.equal(await page.locator('body').evaluate(body => body.classList.contains('network-busy')), false, 'short requests should not flash the global busy state');
  assert.equal(await page.locator('#requestActivity').isHidden(), true, 'short requests should not show request activity');
  assert.deepEqual(await page.evaluate(() => window.__shortNavigationRequest), { ok: true });
  await page.unroute('**/api/navigation-feedback-short');

  await page.route('**/api/navigation-feedback-long', async route => {
    navigationRequestStarted();
    await navigationGate;
    return route.fulfill(json({ ok: true }));
  });
  await page.evaluate(() => { window.__longNavigationRequest = fetch('/api/navigation-feedback-long').then(response => response.json()); });
  await navigationStarted;
  await page.waitForFunction(() => document.body.classList.contains('network-busy'));
  assert.equal(await page.locator('#requestActivity').isVisible(), true, 'long requests should expose the actual active request');
  assert.equal(await page.locator('#networkProgress').evaluate(el => getComputedStyle(el).visibility), 'visible');
  assert((await page.locator('#requestActivity').textContent()).includes('正在读取本机数据'));
  releaseNavigationRequest();
  await page.evaluate(() => window.__longNavigationRequest);
  await page.waitForFunction(() => !document.body.classList.contains('network-busy') && document.querySelector('#requestActivity').hidden);
  await page.unroute('**/api/navigation-feedback-long');

  overviewFail = true;
  await page.reload({ waitUntil: 'networkidle' });
  await textIs('#rows', '数据总览加载失败');
  overviewFail = false;
  await page.locator('#workspaceEmptyNotice button').click();
  await textIs('#resultInfo', '共 42 条');
  for (const viewport of [{ width: 1440, height: 960 }, { width: 1024, height: 768 }]) {
    await page.setViewportSize(viewport);
    await page.locator('#analyst').fill('无匹配');
    await page.locator('#analyst').press('Enter');
    await textIs('#workspaceEmptyNotice', '没有匹配的检测记录');
    const button = await page.locator('#workspaceEmptyNotice button').boundingBox();
    assert(button && button.x >= 0 && button.x + button.width <= viewport.width &&
      button.y >= 0 && button.y + button.height <= viewport.height, 'recovery action must remain inside the window');
    await page.screenshot({ path: `tmp/browser/workspace-no-match-${viewport.width}.png`, fullPage: true });
  }
  assert.deepEqual(errors, [], 'no unhandled errors are expected');
  console.log('WORKSPACE_FEEDBACK PASS: empty import, reset, linked filters, paging selection, superseded requests, short/long activity feedback, load retry, startup retry, two viewport sizes');
} finally {
  releaseOverview(); releaseSlow?.(); releaseNavigationRequest?.();
  await browser.close();
}
