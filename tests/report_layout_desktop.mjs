import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const output = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp'), `report-layout-${Date.now()}`);
const source = path.join(root, 'data/thimble.db');
const db = path.join(output, 'test.db');
const python = path.join(root, '.venv/Scripts/python.exe');
const hash = () => createHash('sha256').update(fs.readFileSync(source)).digest('hex');
const before = hash();
fs.mkdirSync(output, {recursive:true});
execFileSync(python, ['-c', `import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`, source, db]);
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules');
const {_electron} = await import(pathToFileURL(path.join(runtime, 'playwright/index.mjs')).href);
const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
const app = await _electron.launch({
  executablePath:packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
  args:packaged ? ['--disable-gpu'] : [root, '--disable-gpu'], cwd:root,
  env:{...process.env, THIMBLE_ALLOW_MULTI_INSTANCE:'1', THIMBLE_PORT:'18845',
    THIMBLE_PYTHON:python, THIMBLE_DB_PATH:db, THIMBLE_USER_DATA_DIR:path.join(output,'profile'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'), THIMBLE_REPORT_DIR:path.join(output,'reports'),
    THIMBLE_LOG_PATH:path.join(output,'service.log')},
});
const evidence = {checks:[],errors:[]};
let page;
try {
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  page.setDefaultTimeout(40000);
  page.on('pageerror', error => evidence.errors.push(error.message));
  await page.locator('#rows tr[data-i]').first().waitFor();
  await page.locator('[data-view="reports"]').click();
  await page.waitForFunction(() => document.querySelector('#rcSite')?.options.length > 1);
  await page.locator('#rcSite').selectOption('N');
  await page.locator('#rcUnit').selectOption('1');
  const outage = await page.locator('#rcOutage').evaluate(select => [...select.options].filter(option => option.value).at(-1).value);
  await page.locator('#rcOutage').selectOption(outage);
  await page.locator('#rcPreview .report-sheet').first().waitFor();
  for (const [width,height] of [[1920,1080],[1366,768],[1280,720],[820,900],[390,844]]) {
    await app.evaluate(({BrowserWindow},{width,height}) => {
      const window = BrowserWindow.getAllWindows()[0];
      window.unmaximize();window.setMinimumSize(320,480);window.setContentSize(width,height);
    }, {width,height});
    for (const editor of ['closed','open']) {
      if (await page.locator('#rcDocumentLayout').getAttribute('data-editor') !== editor) await page.locator('#rcToggleEditor').click();
      await page.waitForTimeout(200);
      const metrics = await page.evaluate(() => {
        const main = document.querySelector('main'), section = document.querySelector('#reports');
        const visible = node => node.getClientRects().length && !node.closest('[hidden]');
        const outside = [...section.querySelectorAll('button,select')].filter(visible).filter(node => {
          const rect = node.getBoundingClientRect();
          return rect.left < -1 || rect.right > innerWidth + 1;
        }).map(node => node.id || node.textContent.trim());
        const clipped = [...section.querySelectorAll('.rc-viewbar button,.rc-topbar button')].filter(visible)
          .filter(node => node.scrollWidth > node.clientWidth + 1).map(node => node.id || node.textContent.trim());
        return {overflow:main.scrollWidth-main.clientWidth,outside,clipped};
      });
      evidence.checks.push({width,height,editor,...metrics});
      assert(metrics.overflow <= 1, JSON.stringify(evidence.checks.at(-1)));
      assert.deepEqual(metrics.outside, [], JSON.stringify(evidence.checks.at(-1)));
      assert.deepEqual(metrics.clipped, [], JSON.stringify(evidence.checks.at(-1)));
      await page.screenshot({path:path.join(output,`${width}-${editor}.png`)});
    }
  }
  assert.deepEqual(evidence.errors, []);
  evidence.passed = true;
  console.log('PASS report preview layouts at 1920, 1366, 1280, 820 and 390 pixels');
} catch (error) {
  evidence.failure = error.stack;
  if (page) await page.screenshot({path:path.join(output,'failure.png')}).catch(() => {});
  throw error;
} finally {
  await app.close();
  evidence.sourceUnchanged = hash() === before;
  fs.writeFileSync(path.join(output,'evidence.json'), JSON.stringify(evidence,null,2));
  console.log('Evidence:', output);
  assert(evidence.sourceUnchanged, 'The original database must remain unchanged');
}
