const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function allowedURL(value, base) {
  try {
    const url = new URL(value);
    if (url.protocol === 'data:' || value === 'about:blank') return true;
    if (url.protocol === 'blob:') return url.origin === new URL(base).origin;
    return url.protocol === 'http:' && url.origin === new URL(base).origin;
  } catch { return false; }
}

function protectDirectory(directory) {
  const resolved = path.resolve(directory);
  if (resolved === path.parse(resolved).root) throw new Error('用户数据目录不能是磁盘根目录');
  fs.mkdirSync(resolved, {recursive:true,mode:0o700});
  if (process.platform !== 'win32') {fs.chmodSync(resolved, 0o700);return;}
  const system = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32');
  const user = spawnSync(path.join(system,'whoami.exe'), ['/user','/fo','csv','/nh'], {encoding:'utf8',windowsHide:true,timeout:5000});
  const sid = user.stdout?.match(/S-1-5-[0-9-]+/)?.[0];
  if(user.status !== 0 || !sid) throw new Error('无法识别当前 Windows 用户以保护数据目录');
  const result=spawnSync(path.join(system,'icacls.exe'), [resolved,'/grant:r',`*${sid}:(OI)(CI)F`,'*S-1-5-18:(OI)(CI)F','/inheritance:r'], {encoding:'utf8',windowsHide:true,timeout:10000});
  if(result.status!==0) throw new Error('无法设置用户数据目录访问权限，请检查目录权限');
}

module.exports = {allowedURL,protectDirectory};
