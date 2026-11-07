const fs = require('node:fs/promises');
const path = require('node:path');
const { randomBytes } = require('node:crypto');

async function saveArtifact(filePath, content) {
  const temporary = path.join(path.dirname(filePath), `.thimble-export-${randomBytes(12).toString('hex')}.tmp`);
  try {
    await fs.writeFile(temporary, content, {flag:'wx', mode:0o600});
    await fs.rename(temporary, filePath);
  } catch (cause) {
    const messages = {
      ENOSPC:'保存失败：磁盘空间不足，请释放空间或选择其他磁盘后重试。',
      EACCES:'保存失败：文件被占用或没有写入权限，请关闭文件或更换位置后重试。',
      EPERM:'保存失败：文件被占用或没有写入权限，请关闭文件或更换位置后重试。',
      ENOENT:'保存失败：目标文件夹不存在，请重新选择保存位置。',
      EISDIR:'保存失败：目标路径是文件夹，请重新选择文件名。',
    };
    const error = new Error(messages[cause.code] || '文件保存失败，请检查保存位置后重试。', {cause});
    error.code = cause.code;
    throw error;
  } finally {
    await fs.unlink(temporary).catch(error => {
      if (error.code !== 'ENOENT') console.warn('Unable to remove export temporary file:', temporary, error.code);
    });
  }
}

module.exports = {saveArtifact};
