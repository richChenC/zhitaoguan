import { chromium } from 'file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
import fs from 'node:fs';

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
