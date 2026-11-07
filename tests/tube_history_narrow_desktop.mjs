import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const source = fs.readFileSync('src/desktop-ui/modules/analytics/tube-history-view.js', 'utf8');
const css = fs.readFileSync('src/desktop-ui/modules/analytics/analytics.css', 'utf8');
const {renderTubeHistory} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const runtime = path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {chromium} = await import(pathToFileURL(runtime).href);
const browser = await chromium.launch({headless:true});
try {
  for (const width of [320, 390, 800]) {
    const page = await browser.newPage({viewport:{width,height:800}});
    const html = renderTubeHistory({tube:1, position:'A1', series:[
      {outage:'N101', generation:1, conclusion:'WAR', records:2,
        findings:[{indication:'WAR', location:'P1+' + '1234567890'.repeat(15), percent:20},
          {indication:'WAR', location:'P4', percent:35}],
        current_events:['shifted'], maintenance_note:'记录'.repeat(100)},
      {outage:'N102', generation:2, records:0, findings:[], current_events:['replaced'], replaced:true},
    ]}, 'N1');
    await page.setContent(`<style>*{box-sizing:border-box}body{margin:0}#analytics{padding:12px}${css}</style><main id="analytics"><div class="official-viz">${html}</div></main>`);
    const result = await page.locator('.tube-history-view').evaluate(node => {
      const box = node.getBoundingClientRect();
      const elements = [...node.querySelectorAll('.tube-history-round, .tube-history-finding, .tube-history-maintenance')];
      return {pageWidth:document.documentElement.scrollWidth, viewport:innerWidth,
        outliers:elements.filter(item => {
          const rect = item.getBoundingClientRect();
          return rect.left < box.left - 1 || rect.right > box.right + 1 || item.scrollWidth > item.clientWidth + 1;
        }).map(item => item.className)};
    });
    assert.equal(result.pageWidth, result.viewport, `page overflow at ${width}px`);
    assert.deepEqual(result.outliers, [], `history content overflow at ${width}px`);
    await page.close();
  }
  console.log('Tube history fits 320px, 390px and 800px viewports.');
} finally {
  await browser.close();
}
