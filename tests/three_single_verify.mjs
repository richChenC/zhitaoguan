import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(
  process.env.USERPROFILE || '',
  '.cache',
  'codex-runtimes',
  'codex-primary-runtime',
  'dependencies',
  'node',
  'node_modules',
);
const { chromium } = await import(
  pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href
);

fs.mkdirSync('tmp/browser', { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
page.on('console', message => {
  if (message.type() === 'error') errors.push(message.text());
});

try {
  await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
  await page.locator('[data-view="threeD"]').click();

  const frameElement = page.locator('#threeModelFrame');
  await frameElement.waitFor({ state: 'visible' });
  const model = page.frames().find(frame => frame.url().includes('/visualizations/thimble/'));
  if (!model) throw new Error('3D model iframe did not load');
  await model.locator('#scene canvas').waitFor({ state: 'visible', timeout: 15000 });

  if (!await model.locator('#singleTubePicker').isVisible()) {
    throw new Error('Tube selector is not visible in overview mode');
  }
  await model.locator('#embeddedTubeSelect').evaluate(input => {
    input.value = '3';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(250);
  if (await model.locator('#embeddedTubeOutput').textContent() !== '03') {
    throw new Error('Overview tube selection was not retained');
  }
  await page.waitForTimeout(800);
  if (await model.locator('#embeddedTubeOutput').textContent() !== '03') {
    throw new Error('Async workspace synchronization reset the selected tube');
  }
  await page.locator('[data-view="workspace"]').click();
  await page.locator('[data-view="settings"]').click();
  await page.locator('[data-view="threeD"]').click();
  await page.waitForTimeout(400);
  if (await model.locator('#embeddedTubeOutput').textContent() !== '03') {
    throw new Error('Navigation reset the selected tube');
  }
  await model.locator('#embeddedTubeSelect').evaluate(input => {
    input.value = '4';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(800);
  if (await model.locator('#embeddedTubeOutput').textContent() !== '04') {
    throw new Error('Tube selector cannot retain a new value');
  }
  await page.locator('nav [data-view="workspace"]').click();
  await page.locator('nav [data-view="threeD"]').click();
  await page.waitForTimeout(400);
  if (await model.locator('#embeddedTubeOutput').textContent() !== '04') {
    throw new Error('Tube 04 was not retained after navigation');
  }

  await model.locator('[data-embedded-view="tube"]').click();
  await page.waitForTimeout(400);
  if (!await model.locator('[data-embedded-view="tube"]').evaluate(button => button.classList.contains('active'))) {
    throw new Error('Single-tube view did not activate');
  }

  const canvasSize = await model.locator('#scene canvas').evaluate(canvas => ({
    width: canvas.width,
    height: canvas.height,
  }));
  if (canvasSize.width < 300 || canvasSize.height < 300) {
    throw new Error(`3D canvas is too small: ${JSON.stringify(canvasSize)}`);
  }

  const detailValues = await model.locator('.inspection-record dd').all();
  for (const value of detailValues.slice(0, 8)) {
    const style = await value.evaluate(node => ({
      whiteSpace: getComputedStyle(node).whiteSpace,
      textOverflow: getComputedStyle(node).textOverflow,
    }));
    if (style.whiteSpace !== 'normal' || style.textOverflow === 'ellipsis') {
      throw new Error(`Inspection detail is truncated: ${JSON.stringify(style)}`);
    }
  }

  await page.screenshot({ path: 'tmp/browser/ui-single-tube-current.png', fullPage: true });
  await page.setViewportSize({ width: 760, height: 900 });
  await page.waitForTimeout(300);
  const dimensions = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  if (dimensions.scrollWidth > dimensions.clientWidth + 2) {
    throw new Error(`Narrow layout overflows: ${JSON.stringify(dimensions)}`);
  }

  console.log(JSON.stringify({ canvasSize, dimensions, errors }));
  if (errors.length) process.exitCode = 1;
} finally {
  await browser.close();
}
