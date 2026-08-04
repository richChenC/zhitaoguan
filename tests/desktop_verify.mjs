import { _electron as electron } from 'file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/.pnpm/playwright@1.61.1/node_modules/playwright/index.mjs';
import fs from 'node:fs';

fs.mkdirSync('tmp/browser', { recursive: true });
const app = await electron.launch({
  executablePath: 'D:/指套管/软件部分/node_modules/electron/dist/electron.exe',
  args: ['D:/指套管/软件部分', '--disable-gpu', '--disable-gpu-compositing'],
  cwd: 'D:/指套管/软件部分'
});
const window = await app.firstWindow();
await window.waitForLoadState('networkidle');
const title = await window.title();
const chrome = await app.evaluate(({ BrowserWindow }) => {
  const current = BrowserWindow.getAllWindows()[0];
  return { menuVisible: current.isMenuBarVisible(), size: current.getSize(), title: current.getTitle() };
});
await window.getByRole('button', { name: '导入数据', exact: true }).first().click();
await window.locator('#importDialog').waitFor();
await window.locator('#importDialog button[value="cancel"]').click();
await window.getByRole('button', { name: '三维缺陷模型', exact: true }).click();
await window.locator('#threeCanvas canvas').waitFor();
await window.screenshot({ path: 'tmp/browser/desktop-app.png', fullPage: true });
console.log(JSON.stringify({ title, chrome, canvas: await window.locator('#threeCanvas canvas').count(), navHeight: await window.locator('.app-nav').evaluate(el=>el.getBoundingClientRect().height) }));
await app.close();
