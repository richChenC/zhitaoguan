import path from 'node:path';
import { pathToFileURL } from 'node:url';

const modules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(modules, 'playwright', 'index.mjs')).href);
const browser = await chromium.launch({headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
const page = await browser.newPage({viewport: {width: 900, height: 900}});
try {
  await page.goto('http://127.0.0.1:8765/visualizations/thimble/index.html?embedded=1', {waitUntil: 'networkidle'});
  await page.locator('#scene canvas').waitFor({timeout: 15000});
  await page.locator('[data-embedded-view="tube"]').click();
  await page.waitForTimeout(600);
  await page.screenshot({path: 'tmp/single-model-redesign.png', fullPage: true});
  const canvasSize = await page.locator('#scene canvas').evaluate(canvas => ({width: canvas.width, height: canvas.height}));
  if (canvasSize.width < 300 || canvasSize.height < 300) throw new Error(`单管模型画布尺寸异常: ${JSON.stringify(canvasSize)}`);
  console.log(JSON.stringify(canvasSize));
} finally {
  await browser.close();
}
