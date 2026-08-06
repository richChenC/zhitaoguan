import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const bundledNodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(bundledNodeModules, 'playwright', 'index.mjs')).href);

const base = 'http://127.0.0.1:8765';
const out = 'tmp/browser';
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
const errors = [];
for (const viewport of [{name:'desktop',width:1440,height:960},{name:'mobile',width:390,height:844}]) {
  const page = await browser.newPage({ viewport });
  page.on('console', msg => { if (msg.type() === 'error') errors.push(`${viewport.name}: ${msg.text()}`); });
  page.on('pageerror', err => errors.push(`${viewport.name}: ${err.message}`));
  page.on('response', response => { if (response.status() >= 400) errors.push(`${viewport.name}: ${response.status()} ${response.url()}`); });
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.screenshot({ path: `${out}/${viewport.name}.png`, fullPage: true });
  if (viewport.name === 'desktop') {
    await page.locator('#site').selectOption('N');
    await page.locator('#searchBtn').click();
    await page.waitForFunction(() => [...document.querySelectorAll('#rows tr[data-i] td:nth-child(2)')].every(cell => cell.textContent.startsWith('N')));
    await page.locator('#resetBtn').click();
    await page.locator('#importBtn').click();
    await page.locator('#selectFolderBtn').click();
    if (await page.locator('#importPath').evaluate(input => input.readOnly)) throw new Error('browser fallback folder input did not unlock');
    await page.locator('#importPath').fill('D:\\指套管\\测试数据');
    await page.locator('#scanReports').click();
    await page.locator('#reportOptions input').first().waitFor({ timeout: 15000 });
    for (const radio of await page.locator('#reportOptions input[type="radio"]').all()) {
      const name = await radio.getAttribute('name');
      if (!await page.locator(`#reportOptions input[name="${name}"]:checked`).count()) await radio.check();
    }
    await page.locator('#exportFolderExcel').click();
    await page.locator('#importStatus a').waitFor({ timeout: 15000 });
    if (!String(await page.locator('#importStatus a').textContent()).endsWith('.xlsx')) throw new Error('folder Excel export did not produce xlsx');
    await page.locator('#importDialog button[value="cancel"]').click();
    const combinedMarkerCount = await page.locator('#coreMap .path-marker').count();
    await page.getByRole('button', { name: '偶数机组', exact: true }).first().click();
    const evenMarkerCount = await page.locator('#coreMap .path-marker').count();
    if (combinedMarkerCount !== 50 || evenMarkerCount !== 50) throw new Error(`reference grid must contain exactly 50 physical paths: ${combinedMarkerCount}/${evenMarkerCount}`);
    if (await page.locator('#coreMap .path-marker[data-odd-pos="N5"][data-even-pos="M5"]').count() !== 1) { const pairs=await page.locator('#coreMap .path-marker').evaluateAll(nodes=>nodes.map(node=>[node.dataset.oddPos,node.dataset.evenPos]).filter(pair=>pair.includes('N5')||pair.includes('M5'))); throw new Error(`special N5/M5 path pairing incorrect: ${JSON.stringify(pairs)}`); }
    await page.getByRole('button', { name: '综合显示' }).click();
    await page.locator('#coreMap .even-path').filter({ hasText: '1' }).first().click();
    await page.locator('.path-detail').waitFor();
    await page.screenshot({ path: `${out}/core-even-full.png`, fullPage: true });
    await page.locator('#rows tr[data-i]').first().click();
    await page.locator('.path-marker.selected').waitFor();
    await page.getByRole('button', { name: '历史大修对比' }).click();
    await page.locator('#compareBtn').click();
    if (await page.locator('#oldOutage option').count() > 2) await page.locator('#compareSummary .summary-box').first().waitFor();
    else await page.locator('#toast.show').waitFor();
    await page.screenshot({ path: `${out}/compare.png`, fullPage: true });
    await page.getByRole('button', { name: '三维缺陷模型' }).click();
    await page.locator('#threeCanvas canvas').waitFor({ timeout: 5000 }).catch(() => { throw new Error(`3D canvas missing: ${JSON.stringify(errors)}`); });
    if (await page.locator('.three-scale span').count() !== 6) throw new Error('P1-P6 scale is incomplete');
    if (await page.getByRole('button', { name: '奇数机组' }).isDisabled()) throw new Error('odd/even controls must remain interactive');
    const oddCount = await page.locator('#threeStats strong').first().textContent();
    await page.getByRole('button', { name: '偶数机组' }).click();
    await page.waitForTimeout(1500);
    const debugStats = await page.locator('#threeStats').innerText();
    const totalFindings = Number(await page.locator('#mFindings').textContent());
    if (totalFindings > 0 && (await page.locator('#threeStats strong').first().textContent()) === '0') throw new Error(`even scene stayed empty: ${debugStats}; ${JSON.stringify(errors)}`);
    const evenCount = await page.locator('#threeStats strong').first().textContent();
    const canvas = page.locator('#threeCanvas canvas');
    for (const name of ['俯视管板','等轴视图','适应窗口','隐藏外壳','显示外壳']) {
      const control = page.getByRole('button', { name, exact: true });
      await control.waitFor();
      await control.click();
    }
    const beforeRotate = await canvas.screenshot();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * .55, box.y + box.height * .55);
    await page.mouse.down();await page.mouse.move(box.x + box.width * .7, box.y + box.height * .5,{steps:8});await page.mouse.up();
    const afterRotate = await canvas.screenshot();
    if (Buffer.compare(beforeRotate,afterRotate)===0) throw new Error('whole model did not rotate after drag');
    if (await page.locator('#autoRotateBtn').count()) throw new Error('rotation control should not exist');
    await page.locator('#tubeFocusSelect').selectOption('1');
    await page.locator('#focusTubeBtn').click();
    await page.locator('#resetViewBtn').waitFor();
    const visibleRootObjects = await page.locator('#threeCanvas canvas').evaluate(() => document.querySelector('#resetViewBtn').hidden ? 0 : 1);
    if (!visibleRootObjects) throw new Error('single tube focus did not activate');
    await page.screenshot({ path: `${out}/three-tube-focus.png`, fullPage: true });
    await page.locator('#resetViewBtn').click();
    const canvasCheck = await page.locator('#threeCanvas canvas').evaluate(canvas => {
      const ctx = canvas.getContext('webgl2') || canvas.getContext('webgl');
      const pixels = new Uint8Array(4 * canvas.width * canvas.height);
      ctx.readPixels(0, 0, canvas.width, canvas.height, ctx.RGBA, ctx.UNSIGNED_BYTE, pixels);
      let varied = false;
      for (let i = 0; i < pixels.length; i += 160) if (pixels[i] > 35 || pixels[i + 1] > 35 || pixels[i + 2] > 35) { varied = true; break; }
      return { nonBlank: varied, width: canvas.width, height: canvas.height };
    });
    console.log(JSON.stringify({ threeD: { oddCount, evenCount, canvasCheck } }));
    await page.screenshot({ path: `${out}/three-even.png`, fullPage: true });
  }
  const bodyWidth = await page.evaluate(() => ({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));
  console.log(JSON.stringify({ viewport: viewport.name, title: await page.title(), bodyWidth }));
  await page.close();
}
await browser.close();
console.log(JSON.stringify({ errors }));
if (errors.length) process.exitCode = 1;
