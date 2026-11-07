import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const runtime = path.join(process.env.USERPROFILE,
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {chromium} = await import(pathToFileURL(runtime).href);
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('http://state-mode.test/', route => route.fulfill({body:'<!doctype html><body></body>'}));
  await page.goto('http://state-mode.test/');
  await page.evaluate(html => {
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    document.body.innerHTML = parsed.querySelector('#states').outerHTML;
    window.state = {overview:{combinations:[{site:'N', unit_id:1, outage:'N101'}]}};
    window.toast = () => {};
    window.unique = values => [...new Set(values)];
    window.refill = (id, values, label) => {
      const field = document.getElementById(id), current = field.value;
      field.replaceChildren(new Option(label, ''), ...window.unique(values).map(value => new Option(value, value)));
      field.value = current;
    };
    window.api = async () => ({items:Array.from({length:50}, (_, index) => ({
      thimble_id:index + 1, maintained:false, current_events:[], state:'unknown',
      state_label:'未维护', generation:1, cumulative_offset_mm:0, warnings:[],
    }))});
  }, fs.readFileSync('src/desktop-ui/index.html', 'utf8'));
  for (const name of ['tube-state-workspace.js', 'tube-lifecycle-workspace.js']) {
    await page.addScriptTag({content:fs.readFileSync(`src/desktop-ui/${name}`, 'utf8')});
  }
  await page.evaluate(() => {
    window.stateMaintenance.overview();
    window.stateMaintenance.edit({outage:'N101', unit_id:1, thimble_id:7, state:'normal'});
  });
  const submit = page.locator('#stateForm button[type=submit]');
  const mode = page.locator('#lifecycleBatchMode');
  assert.equal(await submit.isDisabled(), false);
  await page.locator('#lifecycleSelectAll').click();
  assert.equal(await mode.isChecked(), true);
  assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选50根');
  assert.equal(await submit.isDisabled(), true);
  assert.match(await submit.getAttribute('title'), /关闭后才能保存单管/);
  await mode.uncheck();
  assert.equal(await page.locator('#lifecycleSelected').textContent(), '已选0根');
  assert.equal(await submit.isDisabled(), false);
  assert.deepEqual(errors, []);
  console.log('Select-all enters batch mode, disables single save and restores it after leaving batch mode.');
} finally {
  await browser.close();
}
