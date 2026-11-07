// ESM 语法检查：node --check 默认按 CommonJS 解析，遇到 import/export 会误报。
// 正确做法是 `node --check --input-type=module < file.js`（从 stdin 读入并指定模块类型）。
// 本脚本一次性检查桌面端 src/desktop-ui 下所有 ESM 模块。
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === 'vendor' || e.name === 'node_modules') continue;   // 第三方库跳过
      walk(p, out);
    } else if (e.name.endsWith('.js') || e.name.endsWith('.mjs')) {
      out.push(p);
    }
  }
  return out;
}

const files = [
  ...walk(path.join(root, 'src', 'desktop-ui')),
  ...walk(path.join(root, 'tests')),
].filter((f) => {
  const src = fs.readFileSync(f, 'utf8');
  return /(^|\n)\s*(import\s|export\s|import\()/.test(src);   // 只检查真正的 ESM
});

let bad = 0;
for (const f of files.sort()) {
  try {
    execFileSync(process.execPath, ['--check', '--input-type=module'],
                 { input: fs.readFileSync(f), stdio: ['pipe', 'pipe', 'pipe'] });
    console.log('  [OK]   ' + path.relative(root, f).replace(/\\/g, '/'));
  } catch (e) {
    bad++;
    const msg = (e.stderr?.toString() || e.message).split('\n').slice(0, 3).join(' ');
    console.log('  [FAIL] ' + path.relative(root, f).replace(/\\/g, '/') + '\n         ' + msg.trim());
  }
}
console.log('\n共检查 %d 个 ESM 文件，失败 %d 个', files.length, bad);
console.log(bad ? 'CHECK_ESM FAIL' : 'CHECK_ESM PASS');
process.exit(bad ? 1 : 0);
