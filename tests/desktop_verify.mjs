import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const playwrightPath = process.env.PLAYWRIGHT_PATH || path.join(bundledNodeModules, 'playwright', 'index.mjs');
if (!fs.existsSync(playwrightPath)) {
  console.log(`desktop smoke skipped: Playwright not found at ${playwrightPath}`);
  process.exit(0);
}
const { _electron: electron } = await import(pathToFileURL(playwrightPath).href);
const executable = path.join(root, 'node_modules', 'electron', 'dist', process.platform === 'win32' ? 'electron.exe' : 'electron');
const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'thimble-desktop-'));
const app = await electron.launch({
  executablePath: executable,
  args: [root, '--disable-gpu', '--disable-gpu-compositing', `--user-data-dir=${path.join(tempRoot, 'user-data')}`],
  cwd: root,
  env: {...process.env, THIMBLE_PORT: '18766', THIMBLE_DB_PATH: path.join(tempRoot, 'thimble.db'), THIMBLE_OUTPUT_DIR: path.join(tempRoot, 'excel'), THIMBLE_LOG_PATH: path.join(tempRoot, 'service.log')}
});
try {
  const page = await app.firstWindow();
  await page.waitForLoadState('networkidle');
  await page.locator('[data-view="reports"]').click();
  await page.locator('#previewInspectionReport').waitFor();
  await page.locator('#previewCompareReport').waitFor();
  if (!await page.locator('#reportPreviewDialog').count()) throw new Error('report preview dialog is missing');
  await page.locator('[data-view="threeD"]').click();
  const frame = page.locator('#threeModelFrame');
  await frame.waitFor();
  const model = frame.contentFrame();
  await model.locator('.embedded-tools').waitFor();
  await model.locator('.inspector').waitFor();
  const layout = await page.evaluate(() => ({
    viewport: innerWidth,
    scope: document.querySelector('.three-scope-controls').getBoundingClientRect().toJSON(),
    frame: document.querySelector('#threeModelFrame').getBoundingClientRect().toJSON(),
  }));
  const innerLayout = await model.locator('body').evaluate(() => ({
    width: innerWidth,
    tools: document.querySelector('.embedded-tools').getBoundingClientRect().toJSON(),
    inspector: document.querySelector('.inspector').getBoundingClientRect().toJSON(),
    details: Boolean(document.querySelector('#selectedTubeDetails')),
  }));
  if (!(layout.scope.x < layout.viewport / 2)) throw new Error('3D scope controls are not on the left');
  if (!(innerLayout.tools.x > innerLayout.width / 2)) throw new Error('3D view controls are not on the right');
  if (!innerLayout.details) throw new Error('tube detail panel is missing');
  await page.screenshot({path: path.join(root, 'tmp', 'desktop-smoke.png'), fullPage: true});
  console.log(JSON.stringify({layout, innerLayout}));
} finally {
  await app.close();
}
