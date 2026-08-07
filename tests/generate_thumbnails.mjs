import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const nodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nodeModules, 'playwright', 'index.mjs')).href);

const output = 'output/thumbnails';
fs.mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
await page.getByRole('button', { name: '三维缺陷图' }).click();
await page.locator('#threeCanvas canvas').waitFor();
await page.getByRole('button', { name: '偶数机组', exact: true }).click();
await page.waitForTimeout(500);

for (const [button, file] of [
  ['等轴视图', '01-isometric.png'],
  ['俯视管板', '02-top.png'],
  ['仰视管板', '03-bottom.png'],
  ['分层视图', '04-layers.png'],
]) {
  await page.getByRole('button', { name: button, exact: true }).click();
  await page.waitForTimeout(500);
  await page.locator('.three-stage').screenshot({ path: `${output}/${file}` });
}

await browser.close();
console.log(output);
