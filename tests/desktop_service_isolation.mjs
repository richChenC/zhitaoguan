import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron} = await import(pathToFileURL(runtime).href);
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-service-isolation-'));
const python = path.join(root, '.venv/Scripts/python.exe');
const executablePath = path.join(root, 'node_modules/electron/dist/electron.exe');
const backend = fs.readFileSync(path.join(root, 'src/backend/server.py'), 'utf8');
const version = backend.match(/SERVICE_VERSION = "([^"]+)"/)[1];

for (const scenario of ['same-version-service', 'unrelated-service']) {
  const folder = path.join(temp, scenario);
  fs.mkdirSync(folder, {recursive: true});
  const database = path.join(folder, 'own.db');
  const otherDatabase = path.join(folder, 'other.db');
  let requests = 0;
  const listener = http.createServer((request, response) => {
    requests += 1;
    response.setHeader('Connection', 'close');
    if (request.url === '/api/health') {
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify({
        ok: true,
        service: scenario === 'same-version-service' ? 'thimble-local' : 'another-service',
        version,
        db_path: otherDatabase,
      }));
      return;
    }
    response.setHeader('Content-Type', 'text/html; charset=utf-8');
    response.end('<!doctype html><title>foreign service</title><p>foreign service</p>');
  });
  await new Promise((resolve, reject) => {
    listener.once('error', reject);
    listener.listen(0, '127.0.0.1', resolve);
  });
  const occupiedPort = listener.address().port;
  let app;
  try {
    app = await _electron.launch({
      executablePath,
      args: [root, '--disable-gpu'],
      cwd: root,
      env: {
        ...process.env,
        THIMBLE_ALLOW_MULTI_INSTANCE: '1',
        THIMBLE_PORT: String(occupiedPort),
        THIMBLE_PYTHON: python,
        THIMBLE_DB_PATH: database,
        THIMBLE_USER_DATA_DIR: path.join(folder, 'profile'),
        THIMBLE_OUTPUT_DIR: path.join(folder, 'exports'),
        THIMBLE_REPORT_DIR: path.join(folder, 'reports'),
        THIMBLE_LOG_PATH: path.join(folder, 'service.log'),
      },
    });
    const page = await app.firstWindow({timeout: 60000});
    await ensureLocalLogin(page);
    await page.waitForLoadState('domcontentloaded');
    const health = await page.evaluate(() => fetch('/api/health').then(response => response.json()));
    assert.equal(path.resolve(health.db_path), path.resolve(database), 'Desktop must not connect to another service or database');
    assert.notEqual(new URL(page.url()).port, String(occupiedPort), 'An occupied port must not be used');
    assert.equal(health.service, 'thimble-local');
    assert.equal(health.version, version);
    assert.match(health.desktop_instance, /^[0-9a-f]{48}$/);
    assert.equal(await page.locator('nav').count(), 1, 'Desktop UI should load from its own backend');
    assert.equal(requests, 0, 'Desktop must not use HTTP to identify or serve the occupied port');
    const desktopPort = new URL(page.url()).port;
    await app.close();
    app = null;
    const running = await fetch(`http://127.0.0.1:${desktopPort}/api/health`, {signal: AbortSignal.timeout(3000)})
      .then(() => true, () => false);
    assert.equal(running, false, 'The desktop backend must stop with its window');
    console.log('PASS', scenario, {occupiedPort, desktopPort, database: health.db_path});
  } finally {
    if (app) await app.close().catch(() => {});
    assert.equal(listener.listening, true, 'Closing the desktop must not stop the other service');
    await new Promise(resolve => listener.close(resolve));
  }
}
