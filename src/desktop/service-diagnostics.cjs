const fs = require('node:fs');
const path = require('node:path');

const LOW_SPACE_BYTES = 128 * 1024 * 1024;

function availableBytes(location, statfs = fs.statfsSync) {
  if (!location || typeof statfs !== 'function') return null;
  let current = path.resolve(location);
  for (;;) {
    try {
      const {bavail, bsize} = statfs(current);
      const bytes = Number(bavail) * Number(bsize);
      return Number.isFinite(bytes) && bytes >= 0 ? bytes : null;
    } catch (error) {
      if (!['ENOENT', 'ENOTDIR'].includes(error.code)) return null;
      const parent = path.dirname(current);
      if (parent === current) return null;
      current = parent;
    }
  }
}

function startupFailureMessage(error, {userData, dataDirectory, tempDirectory, logPath, statfs} = {}) {
  const code = error?.code;
  const lines = ['本地数据服务启动失败。'];
  if (code === 'ENOSPC') {
    lines.push('磁盘空间不足，请释放空间后重新启动软件。');
  } else if (code === 'EACCES' || code === 'EPERM') {
    lines.push('无法访问所需目录，请检查当前用户的访问权限后重试。');
    if (error.path) lines.push(`目录或文件：${error.path}`);
  } else if (code === 'ENOTDIR' || code === 'EEXIST') {
    lines.push('数据目录路径不可用，请检查路径中是否有同名文件。');
    if (error.path) lines.push(`目录或文件：${error.path}`);
  } else if (code !== 'SERVICE_START_FAILED' && error?.message) {
    lines.push(error.message);
  } else {
    const locations = [
      ['临时目录', tempDirectory],
      ['数据目录', dataDirectory || userData]
    ];
    const low = locations.filter(([, location]) => {
      const bytes = availableBytes(location, statfs);
      return bytes !== null && bytes < LOW_SPACE_BYTES;
    });
    if (low.length) {
      lines.push('以下目录所在磁盘可用空间较少，可能影响启动，请释放空间后重试：');
      for (const [label, location] of low) lines.push(`${label}：${location}`);
    } else {
      lines.push('请检查临时目录及数据目录的可用空间和访问权限，然后重新启动软件。');
    }
  }
  if (logPath) lines.push(`启动日志（如已生成）：${logPath}`);
  return lines.join('\n');
}

module.exports = {availableBytes, startupFailureMessage, LOW_SPACE_BYTES};
