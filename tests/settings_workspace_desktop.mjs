import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const outputRoot = process.env.THIMBLE_TEST_OUTPUT_ROOT || path.join(root, 'tmp');
const output = path.join(outputRoot, `settings-workspace-${Date.now()}`);
const source = path.join(root, 'data', 'thimble.db');
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const database = path.join(output, 'data', 'thimble.db');
const port = Number(process.env.THIMBLE_SETTINGS_TEST_PORT || 18836);
const evidence = {checks: [], errors: [], requests: [], sizes: []};
const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const before = hash(source);
fs.mkdirSync(path.dirname(database), {recursive: true});
await new Promise((resolve, reject) => {
  const listener = net.createServer();
  listener.once('error', reject);
  listener.listen(port, '127.0.0.1', () => listener.close(resolve));
});
execFileSync(python, ['-X', 'utf8', '-c', `import sqlite3,sys;from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`, source, database]);
const playwright = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(playwright).href);
const environment = {
  ...process.env,
  PYTHONIOENCODING: 'utf-8',
  PYTHONUNBUFFERED: '1',
  THIMBLE_ALLOW_MULTI_INSTANCE: '1',
  THIMBLE_PORT: String(port),
  THIMBLE_PYTHON: python,
  THIMBLE_DATA_DIR: path.dirname(database),
  THIMBLE_DB_PATH: database,
  THIMBLE_LOG_PATH: path.join(output, 'logs', 'server.log'),
  THIMBLE_USER_DATA_DIR: path.join(output, 'profile'),
  THIMBLE_OUTPUT_DIR: path.join(output, 'exports'),
  THIMBLE_REPORT_DIR: path.join(output, 'reports'),
};
let app;
let page;
let mainPage;

async function launch() {
  const packaged = process.env.THIMBLE_TEST_EXECUTABLE;
  app = await _electron.launch({
    executablePath: packaged || path.join(root, 'node_modules/electron/dist/electron.exe'),
    args: packaged ? ['--disable-gpu'] : [root, '--disable-gpu'],
    cwd: root,
    env: environment,
  });
  if (packaged) assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
  page = await app.firstWindow();
  await ensureLocalLogin(page);
  mainPage = page;
  page.setDefaultTimeout(25000);
  page.on('pageerror', error => evidence.errors.push(error.stack || error.message));
  page.on('request', request => {
    const url = request.url();
    if (/^https?:/.test(url) && !url.startsWith(`http://127.0.0.1:${port}/`)) evidence.requests.push(url);
  });
  await page.locator('#rows tr[data-i]').first().waitFor();
  await app.evaluate(({BrowserWindow}) => {
    const window = BrowserWindow.getAllWindows()[0];
    window.unmaximize();
    window.webContents.setZoomFactor(1);
  });
}

async function capture(name) {
  const image = await app.evaluate(async ({BrowserWindow}) =>
    (await (BrowserWindow.getAllWindows().find(window => window.webContents.getURL().includes('window=settings')) || BrowserWindow.getAllWindows()[0]).webContents.capturePage()).toPNG().toString('base64'));
  fs.writeFileSync(path.join(output, name), Buffer.from(image, 'base64'));
}

async function check(name, run) {
  await run();
  evidence.checks.push(name);
  console.log('PASS', name);
}

async function api(url, body) {
  return page.evaluate(async ({url, body}) => {
    const response = await fetch(url, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    return {status: response.status, body: await response.json()};
  }, {url, body});
}

async function settings() {
  if (page.url().includes('window=settings')) return;
  const opened = app.waitForEvent('window');
  await page.locator('[data-open-settings]').click();
  page = await opened;
  page.setDefaultTimeout(25000);
  page.on('pageerror', error => evidence.errors.push(error.stack || error.message));
  page.on('request', request => {
    if (/^https?:/.test(request.url()) && !request.url().startsWith(`http://127.0.0.1:${port}/`)) evidence.requests.push(request.url());
  });
  await page.locator('#settingsDataTab').waitFor();
}

async function pane(id) {
  const button = page.locator(`[data-settings-pane="${id}"]`);
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await page.locator(`#${id}`).waitFor({state: 'visible'});
}

async function saveProfile(button = '#saveSourceDirectory') {
  const pending = page.waitForResponse(response =>
    response.url().endsWith('/api/settings/data-source') && response.request().method() === 'POST');
  await page.locator(button).click();
  const response = await pending;
  return {status: response.status(), body: await response.json()};
}

try {
  await launch();
  await settings();
  await check('Settings categories contain their own controls and support keyboard navigation', async () => {
    await pane('settingsMaintenancePane');
    assert.equal(await page.locator('#settingsMaintenancePane #databaseDedup').count(), 1);
    assert.equal(await page.locator('#settingsMaintenancePane #backupPanel').count(), 1);
    assert.equal(await page.locator('#settings .settings-sections > .software-settings-panel').count(), 0);
    await pane('settingsDataPane');
    await page.locator('#settingsDataTab').focus();
    await page.keyboard.press('ArrowDown');
    assert.equal(await page.locator('#settingsPreferencesTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsPreferencesPane').isVisible());
    await page.keyboard.press('ArrowDown');
    assert.equal(await page.locator('#settingsImportTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsImportPane').isVisible());
    assert.equal(await page.locator('#settingsDocsTab,#settingsDocsPane,#softwareDocsPanel').count(), 0);
    await page.keyboard.press('End');
    assert.equal(await page.locator('#settingsMaintenanceTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsMaintenancePane').isVisible());
    await page.locator('#settingsMaintenanceTab').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#settingsDataTab').getAttribute('aria-selected'), 'true');
    await page.locator('[data-settings-jump="settingsImportPane"]').click();
    assert.equal(await page.locator('#settingsImportTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsImportPane').isVisible());
    await pane('settingsDataPane');
    await page.locator('[data-settings-jump="settingsRulesPane"]').click();
    assert.equal(await page.locator('#settingsRulesTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsRulesPane').isVisible());
    await pane('settingsDataPane');
    await page.locator('[data-settings-jump="settingsMaintenancePane"]').click();
    assert.equal(await page.locator('#settingsMaintenanceTab').getAttribute('aria-selected'), 'true');
    assert(await page.locator('#settingsMaintenancePane').isVisible());
    await pane('settingsDataPane');
    assert.equal(await page.locator('#settingsHeaderClose').count(), 0, 'Settings must use the native window controls');
  });
  await check('Interface and workflow preferences are professional, persistent and actionable', async () => {
    await pane('settingsPreferencesPane');
    assert.equal(await page.locator('[data-theme-choice="light"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-theme-choice="dark"]').click();
    await mainPage.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    assert.equal(await page.evaluate(() => localStorage.getItem('thimbleAppearance')), 'dark');
    assert.equal(await page.locator('[data-theme-choice="dark"]').getAttribute('aria-pressed'), 'true');
    assert.notEqual(await mainPage.locator('.table-panel').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(255, 255, 255)');
    await pane('settingsDataPane');
    const darkSettings = await page.evaluate(() => {
      const read = selector => {
        const node = document.querySelector(selector);
        const style = getComputedStyle(node);
        return {color: style.color, background: style.backgroundColor, border: style.borderColor};
      };
      return {
        heading: read('#settings .settings-window-heading h1'),
        subtitle: read('#settings .settings-window-heading p'),
        windowState: read('#settings .settings-window-state'),
        quick: read('#settings .settings-quick-actions'),
        quickCard: read('#settings .settings-quick-grid button'),
      };
    });
    assert.equal(darkSettings.heading.color, 'rgb(229, 238, 236)', JSON.stringify(darkSettings));
    assert.equal(darkSettings.subtitle.color, 'rgb(168, 184, 181)', JSON.stringify(darkSettings));
    assert.equal(darkSettings.quick.background, 'rgb(35, 47, 49)', JSON.stringify(darkSettings));
    assert.equal(darkSettings.quickCard.background, 'rgb(28, 37, 39)', JSON.stringify(darkSettings));
    await capture('appearance-dark.png');
    await page.reload();
    await page.locator('#rows tr[data-i]').first().waitFor({state: 'attached'});
    await pane('settingsPreferencesPane');
    assert.equal(await page.locator('[data-theme-choice="dark"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-theme-choice="light"]').click();
    await mainPage.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    assert.equal(await page.locator('#settingsDensity').inputValue(), 'standard');
    assert.equal(await page.locator('#settingsShiftDirection').inputValue(), '1');
    await page.locator('#settingsDensity').selectOption('compact');
    await page.locator('#settingsMotion').selectOption('reduced');
    await page.locator('#settingsStartupView').selectOption('states');
    await page.locator('#settingsRememberView').uncheck();
    await page.locator('#settingsShiftDirection').selectOption('-1');
    await page.evaluate(()=>window.statePreferences.settled());
    await page.locator('#settingsImportPolicy').selectOption('auto_latest');
    assert.equal(await page.evaluate(() => document.body.dataset.uiDensity), 'compact');
    assert.equal(await page.evaluate(() => document.body.dataset.reduceMotion), 'true');
    assert.equal(await page.evaluate(() => localStorage.getItem('thimble-state-default-shift-direction')), '-1');
    assert.equal(await page.locator('#reportPolicy').inputValue(), 'auto_latest');
    await page.reload();
    await page.locator('#rows tr[data-i]').first().waitFor({state: 'attached'});
    await settings();
    await pane('settingsPreferencesPane');
    assert.equal(await page.locator('#settingsDensity').inputValue(), 'compact');
    assert.equal(await page.locator('#settingsMotion').inputValue(), 'reduced');
    assert.equal(await page.locator('#settingsStartupView').inputValue(), 'states');
    assert.equal(await page.locator('#settingsRememberView').isChecked(), false);
    assert.equal(await page.locator('#settingsShiftDirection').inputValue(), '-1');
    await page.locator('#resetPreferences').click();
    if(await page.locator('.interaction-confirm').count())await page.locator('.interaction-confirm [value=ok]').click();
    await page.waitForFunction(() => document.querySelector('#settingsDensity').value === 'standard');
    assert.equal(await page.locator('#settingsRememberView').isChecked(), true);
    assert.equal(await page.evaluate(() => localStorage.getItem('thimble-state-default-shift-direction')), '1');
  });
  await check('Actual SQLite database is local and the original business file is not in use', async () => {
    const result = await api('/api/settings/data-source');
    assert.equal(result.status, 200);
    assert.equal(result.body.active.mode, 'local');
    assert.equal(result.body.active.engine, 'sqlite');
    assert.equal(path.resolve(result.body.active.path), database);
    assert.equal(result.body.active.exists, true);
    assert(result.body.active.size_bytes > 0);
    assert.equal(result.body.capabilities.local, true);
    assert.equal(result.body.capabilities.server, false);
    evidence.initial = result.body;
    await page.waitForFunction(() => document.querySelector('#dataSourcePath')?.textContent.includes('thimble.db'));
    assert((await page.locator('#settingsDataPane').textContent()).includes('SQLite'));
    assert((await page.locator('#dataSourceMode').textContent()).includes('本地使用中'));
    assert((await page.locator('#dataSourcePath').textContent()).includes('thimble.db'));
    assert.equal(await page.locator('#copyDataSourcePath').isEnabled(), true);
    assert.equal(await page.locator('#copyDataSourcePath').getAttribute('aria-label'), '复制数据库文件路径');
  });
  await check('Legacy online preference cannot simulate a remote connection', async () => {
    await page.evaluate(() => {
      localStorage.setItem('thimbleRuntimeMode', 'online');
      localStorage.setItem('thimbleStrictValidation', 'false');
    });
    await page.reload();
    await page.locator('#rows tr[data-i]').first().waitFor({state: 'attached'});
    await settings();
    await pane('settingsDataPane');
    assert.equal(await page.locator('#runtimeMode option[value="online"]:enabled').count(), 0);
    assert.notEqual(await page.evaluate(() => document.body.dataset.runtimeMode), 'online');
    assert.notEqual(await page.evaluate(() => localStorage.getItem('thimbleRuntimeMode')), 'online');
    assert.equal((await api('/api/settings/data-source')).body.active.mode, 'local');
    await pane('settingsImportPane');
    assert.equal(await page.locator('#strictValidation,#serverUrl,#serverTimeout,.server-profile-panel').count(), 0);
    assert.equal(await page.evaluate(() => localStorage.getItem('thimbleStrictValidation')), 'true');
  });
  await check('Existing Report selection and severity settings remain editable and persist', async () => {
    await page.locator('#reportPolicy').selectOption('auto_latest');
    await page.locator('#severityLowColor').evaluate(input => {
      input.value = '#138f48';
      input.dispatchEvent(new Event('input', {bubbles: true}));
    });
    await page.locator('#severityMidThreshold').fill('25');
    await page.locator('#severityHighThreshold').fill('45');
    await page.reload();
    await page.locator('#rows tr[data-i]').first().waitFor({state: 'attached'});
    await settings();
    await pane('settingsImportPane');
    assert.equal(await page.locator('#reportPolicy').inputValue(), 'auto_latest');
    assert.equal(await page.locator('#severityLowColor').inputValue(), '#138f48');
    assert.equal(await page.locator('#severityMidThreshold').inputValue(), '25');
    assert.equal(await page.locator('#severityHighThreshold').inputValue(), '45');
    assert.equal(await page.evaluate(() => localStorage.getItem('thimbleStrictValidation')), 'true');
  });
  await check('Comparison rules remain a compact configuration panel', async () => {
    await pane('settingsRulesPane');
    const text = await page.locator('#analysisRulesPanel').innerText();
    assert(text.includes('当前生效'));
    assert(text.includes('历史版本'));
    assert(text.includes('匹配容差'));
    assert(!text.includes('先看这里'));
    assert(!text.includes('按当前容差举例'));
    assert(!text.includes('什么时候才修改'));
    await capture('comparison-rules-compact.png');
  });
  await check('Saving a source directory preserves existing hidden server configuration without activating it', async () => {
    await pane('settingsDataPane');
    const original = (await api('/api/settings/data-source')).body.profile;
    const saved = await api('/api/settings/data-source', {profile: {...original, server_url: 'https://data.example.invalid/api', timeout_seconds: 12}});
    assert.equal(saved.status, 200, JSON.stringify(saved));
    assert.equal(saved.body.active.mode, 'local');
    assert.equal(saved.body.profile.server_url, 'https://data.example.invalid/api');
    assert.equal(saved.body.profile.timeout_seconds, 12);
    const verified = await api('/api/settings/data-source/validate', {
      target: 'server', profile: saved.body.profile,
    });
    assert.equal(verified.status, 200);
    assert.equal(verified.body.target, 'server');
    assert.equal(verified.body.connected, false);
    assert.equal(verified.body.active.mode, 'local');
    evidence.reservedServer = verified.body;
    await pane('settingsImportPane');
    await page.locator('#serverRoot').fill(output);
    const sourceSaved = await saveProfile('#saveSourceDirectory');
    assert.equal(sourceSaved.status, 200, JSON.stringify(sourceSaved));
    assert.equal(path.resolve(sourceSaved.body.profile.source_directory), output);
    assert.equal(sourceSaved.body.profile.server_url, saved.body.profile.server_url);
    evidence.savedProfile = sourceSaved.body.profile;
  });
  await check('Unsupported or unsafe server addresses cannot overwrite a valid profile', async () => {
    await pane('settingsDataPane');
    const original = (await api('/api/settings/data-source')).body.profile;
    for (const url of ['file:///C:/data/thimble.db', 'javascript:alert(1)', 'https://user:secret@example.invalid/api']) {
      const result = await api('/api/settings/data-source', {profile: {...original, server_url: url}});
      assert.equal(result.status, 400, JSON.stringify({url, result}));
      assert.deepEqual((await api('/api/settings/data-source')).body.profile, original);
    }
    assert.equal(await page.locator('#serverUrl,#saveDataSourceProfile').count(), 0);
  });
  await check('The active database can be checked through the settings interface', async () => {
    const pending = page.waitForResponse(response =>
      response.url().endsWith('/api/settings/data-source/validate'));
    await page.locator('#validateDataSource').click();
    const response = await pending;
    const result = await response.json();
    assert.equal(response.status(), 200);
    assert.equal(result.connected, true);
    assert.equal(result.target, 'local');
    assert.equal(result.active.mode, 'local');
    evidence.localValidation = result;
  });
  await check('A settings backup contains real business data and restore stays confirmation-gated', async () => {
    await pane('settingsMaintenancePane');
    const pending = page.waitForResponse(response =>
      response.url().endsWith('/api/backup') && response.request().method() === 'POST');
    await page.locator('#backupNow').click();
    const response = await pending;
    const backup = await response.json();
    assert.equal(response.status(), 200);
    assert(fs.existsSync(backup.path));
    assert(path.resolve(backup.path).startsWith(path.dirname(database) + path.sep));
    assert(fs.statSync(backup.path).size > 1000);
    const validated = await api('/api/backup-validate', {path: backup.path});
    assert.equal(validated.status, 200);
    assert(validated.body.findings > 0);
    await page.locator('.backup-restore').first().waitFor();
    await page.locator('.backup-restore').first().click();
    await page.waitForFunction(() => !document.querySelector('#restoreAck').disabled);
    assert(await page.locator('#restoreConfirm').isDisabled());
    await page.locator('#restoreAck').check();
    assert(!(await page.locator('#restoreConfirm').isDisabled()));
    await capture('restore-confirmation.png');
    await page.locator('#restoreCancel').click();
    assert(!(await page.locator('#restoreDialog').isVisible()));
    evidence.backup = {file: backup.path, findings: validated.body.findings};
  });
  await check('A committed restore with failed UI refresh remains visible without prompting another restore', async () => {
    await page.locator('.backup-restore').first().click();
    await page.waitForFunction(() => !document.querySelector('#restoreAck').disabled);
    await page.locator('#restoreAck').check();
    await page.route('**/api/restore', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({restored_from: evidence.backup.file, safety_backup: 'test-safety.db'}),
    }));
    await page.evaluate(() => {
      window.__savedWorkspaceRefresh = window.workspaceRefresh;
      window.workspaceRefresh = async () => {throw new Error('RESTORE_REFRESH_FAILURE')};
    });
    try {
      await page.locator('#restoreConfirm').click();
      await page.waitForFunction(() => !document.querySelector('#restoreDialog').open);
      await page.waitForFunction(() => document.querySelector('#feedbackHistory')?.textContent.includes('数据库已恢复，但界面刷新失败：RESTORE_REFRESH_FAILURE'));
      assert.match(await page.locator('#feedbackHistory').textContent(), /无需重复恢复/);
      assert(await page.locator('#backupNow').isEnabled());
      await capture('restore-refresh-warning.png');
    } finally {
      await page.unroute('**/api/restore');
      await page.evaluate(() => {
        window.workspaceRefresh = window.__savedWorkspaceRefresh;
        delete window.__savedWorkspaceRefresh;
      });
    }
  });
  await check('Settings survive a full native desktop and data-service restart', async () => {
    await app.close();
    app = null;
    await launch();
    await settings();
    await pane('settingsDataPane');
    const result = await api('/api/settings/data-source');
    assert.deepEqual(result.body.profile, evidence.savedProfile);
    assert.equal(result.body.active.mode, 'local');
    assert.equal(await page.locator('.server-profile-panel').count(), 0);
    await pane('settingsImportPane');
    assert.equal(await page.locator('#reportPolicy').inputValue(), 'auto_latest');
    assert.equal(await page.locator('#severityLowColor').inputValue(), '#138f48');
  });
  await check('All settings sections fit native window sizes and 125/150 percent display scaling', async () => {
    for (const size of [
      {w: 800, h: 600, z: 1}, {w: 1100, h: 720, z: 1}, {w: 1480, h: 960, z: 1},
      {w: 800, h: 600, z: 1.25}, {w: 1100, h: 720, z: 1.25}, {w: 1480, h: 960, z: 1.25},
      {w: 800, h: 600, z: 1.5}, {w: 1100, h: 720, z: 1.5}, {w: 1480, h: 960, z: 1.5},
    ]) {
      const content = await app.evaluate(({BrowserWindow}, size) => {
        const window = BrowserWindow.getAllWindows().find(window => window.webContents.getURL().includes('window=settings'));
        window.unmaximize();
        window.setSize(size.w, size.h);
        window.webContents.setZoomFactor(size.z);
        return window.getContentBounds();
      }, size);
      await page.waitForFunction(size =>
        Math.abs(innerWidth - size.width / size.z) < 3 &&
        Math.abs(innerHeight - size.height / size.z) < 3, {...content, z: size.z});
      await settings();
      for (const id of ['settingsDataPane', 'settingsPreferencesPane', 'settingsImportPane', 'settingsRulesPane', 'settingsMaintenancePane']) {
        await pane(id);
        await page.waitForTimeout(150);
        const metrics = await page.evaluate(id => {
          const main = document.querySelector('main');
          const section = document.querySelector('#' + id);
          const visible = node => node.getClientRects().length && !node.closest('[hidden]');
          const outside = [...section.querySelectorAll('button,select,input')].filter(visible).filter(node => {
            const rect = node.getBoundingClientRect();
            return rect.left < -1 || rect.right > innerWidth + 1;
          }).map(node => node.id || node.textContent.trim());
          const clippedButtons = [...section.querySelectorAll('button')].filter(visible).filter(node =>
            node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1
          ).map(node => ({id: node.id, text: node.textContent.trim(), width: node.clientWidth, scrollWidth: node.scrollWidth}));
          return {width: innerWidth, height: innerHeight, overflow: main.scrollWidth - main.clientWidth, outside, clippedButtons};
        }, id);
        evidence.sizes.push({size, pane: id, ...metrics});
        assert(metrics.overflow <= 1, JSON.stringify({size, id, metrics}));
        assert.deepEqual(metrics.outside, [], JSON.stringify({size, id, metrics}));
        assert.deepEqual(metrics.clippedButtons, [], JSON.stringify({size, id, metrics}));
        await capture(`${size.w}-${size.h}-${size.z}-${id}.png`);
      }
    }
  });
  await check('The settings native window can close without closing the main window', async () => {
    const closed = page.waitForEvent('close');
    await page.close();
    await closed;
    assert.equal(app.windows().length, 1);
    assert.equal(mainPage.url().includes('window=settings'), false);
    page = mainPage;
  });
  assert.deepEqual(evidence.errors, []);
  assert.deepEqual(evidence.requests, []);
  evidence.passed = true;
} catch (error) {
  evidence.failure = error.stack;
  if (page) await capture('failure.png').catch(() => {});
  throw error;
} finally {
  if (app) await app.close();
  evidence.sourceUnchanged = hash(source) === before;
  evidence.output = output;
  fs.writeFileSync(path.join(output, 'evidence.json'), JSON.stringify(evidence, null, 2));
  console.log('Evidence:', output);
  assert(evidence.sourceUnchanged, 'The original business database must remain unchanged');
}
