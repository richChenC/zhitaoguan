// 编码探针：确认合并后的 CSS 均为合法 UTF-8，中文内容未被解码成替换字符
// 背景：原 interaction.css 实为 GBK 编码且无 @charset 声明，浏览器会按 UTF-8 解码。
//       其 .core-panel .detail:before{content:'综合结论'} 因被后续 content:none!important
//       覆盖而未显现乱码，但属于隐患；合并时已统一转为 UTF-8。
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const nm = process.env.CODEX_NODE_MODULES
  || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes',
               'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium } = await import(pathToFileURL(path.join(nm, 'playwright', 'index.mjs')).href);

let browser;
let bad = 0;
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage();
  await page.addInitScript(() => { window.desktopAPI = { getApiToken: () => 'dev-verify-20260828' }; });
  await page.goto('http://127.0.0.1:8765/', { waitUntil: 'domcontentloaded' });

  const files = ['/app.css', '/shell.css', '/polish.css',
                 '/modules/analytics/analytics.css', '/modules/three-d/main-view.css'];
  for (const f of files) {
    const txt = await page.evaluate(async (u) => (await fetch(u)).text(), f);
    const hasReplacement = txt.includes('\uFFFD');
    // GBK 中文被当 UTF-8 解码后的典型特征字
    const hasMojibake = /缁|悎|撹|鏄|锛/.test(txt);
    const ok = !hasReplacement && !hasMojibake;
    if (!ok) bad++;
    const note = hasReplacement ? '含替换字符 U+FFFD' : (hasMojibake ? '疑似 GBK 乱码' : 'UTF-8 正常');
    console.log('  ' + (ok ? '[OK]  ' : '[BAD] ') + f.padEnd(38) + txt.length + ' 字符  ' + note);
  }
} catch (e) {
  bad++;
  console.log('  [BAD] 执行异常: ' + (e && e.message ? e.message : String(e)));
} finally {
  // 注意：本环境下 await browser.close() 会让进程被直接终止（退出码 1 且后续日志不输出），
  // 因此这里不等待关闭，直接给出结论并显式退出。浏览器进程由 Playwright 自行回收。
  if (browser) { try { browser.close(); } catch (_) { /* 忽略 */ } }
}
console.log('\n' + (bad ? 'ENCODING FAIL' : 'ENCODING PASS'));
process.exit(bad ? 1 : 0);
