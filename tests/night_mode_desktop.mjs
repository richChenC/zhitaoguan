import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `night-mode-${Date.now()}`);
const source = path.join(root, 'data', 'thimble.db');
const database = path.join(output, 'data', 'thimble.db');
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const port = Number(process.env.THIMBLE_NIGHT_TEST_PORT || 18846);
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const before = hash(source);
fs.mkdirSync(path.dirname(database), {recursive:true});
await new Promise((resolve, reject) => {
  const listener = net.createServer();
  listener.once('error', reject);
  listener.listen(port, '127.0.0.1', () => listener.close(resolve));
});
execFileSync(python, ['-X', 'utf8', '-c', `import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`, source, database]);

const playwright = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(playwright).href);
const app = await _electron.launch({
  executablePath:path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:[root, '--disable-gpu'],
  cwd:root,
  env:{
    ...process.env,
    PYTHONIOENCODING:'utf-8',
    PYTHONUNBUFFERED:'1',
    THIMBLE_ALLOW_MULTI_INSTANCE:'1',
    THIMBLE_PORT:String(port),
    THIMBLE_PYTHON:python,
    THIMBLE_DATA_DIR:path.dirname(database),
    THIMBLE_DB_PATH:database,
    THIMBLE_USER_DATA_DIR:path.join(output, 'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output, 'exports'),
    THIMBLE_REPORT_DIR:path.join(output, 'reports'),
    THIMBLE_LOG_PATH:path.join(output, 'logs', 'server.log'),
  },
});

const page = await app.firstWindow();
page.setDefaultTimeout(30000);
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const isLight = color => {
  const match = String(color).match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  return Boolean(match && match.slice(1).every(value => Number(value) >= 220));
};
const surface = (selector, property = 'backgroundColor') =>
  page.locator(selector).first().evaluate((element, key) => getComputedStyle(element)[key], property);
const capture = async name => {
  const png = await app.evaluate(async ({BrowserWindow}) =>
    (await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output, name), Buffer.from(png, 'base64'));
};

try {
  await ensureLocalLogin(page);
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.evaluate(() => window.appAppearance.setTheme('dark'));
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');

  assert(!isLight(await surface('#workspace .toolbar')));
  assert(!isLight(await surface('#workspace .table-panel')));
  await capture('01-workbench-dark.png');

  await page.locator('[data-view="states"]').click();
  await page.locator('#states.active .state-scope').waitFor();
  assert.equal(await page.locator('#states .state-workspace-heading').count(), 0);
  assert.equal(await page.getByText('管子状态维护', {exact:true}).count(), 0);
  assert(!isLight(await surface('#states .state-scope')));
  assert(!isLight(await surface('#states .state-tube-grid button')));
  await capture('02-states-dark.png');

  await page.locator('[data-view="analytics"]').click();
  await page.locator('#analytics.active').waitFor();
  await page.waitForTimeout(1000);
  assert(!isLight(await surface('#analytics')));
  await capture('03-analytics-dark.png');

  await page.locator('[data-view="reports"]').click();
  await page.locator('#reports.active').waitFor();
  await page.locator('.report-center').waitFor();
  assert(!isLight(await surface('.report-center .rc-toolbar')));
  const sheet = page.locator('.report-sheet,.source-form').first();
  if (await sheet.count()) assert(isLight(await sheet.evaluate(element => getComputedStyle(element).backgroundColor)));
  await capture('04-reports-dark.png');

  await page.locator('[data-view="threeD"]').click();
  const frame = page.frameLocator('#threeModelFrame');
  await frame.locator('#loading.off').waitFor({timeout:45000});
  await frame.locator('html[data-theme="dark"]').waitFor();
  assert(!isLight(await frame.locator('header').evaluate(element => getComputedStyle(element).backgroundColor)));
  assert(!isLight(await frame.locator('#stage').evaluate(element => getComputedStyle(element).backgroundColor)));
  await capture('05-three-dimensional-dark.png');

  await page.evaluate(() => window.appAppearance.setTheme('light'));
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');
  await frame.locator('html[data-theme="light"]').waitFor();
  assert.equal(await frame.locator('html').getAttribute('data-theme'), 'light');
  assert(isLight(await frame.locator('#stage').evaluate(element => getComputedStyle(element).backgroundColor)));
  assert.deepEqual(errors, []);
  assert.equal(hash(source), before);
  console.log('PASS complete night mode covers workbench, state, analytics, report and 3D windows');
  console.log(`Evidence: ${output}`);
} finally {
  await app.close();
}
