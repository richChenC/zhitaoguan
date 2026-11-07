const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');

module.exports = async context => {
  if (context.electronPlatformName !== 'win32') return;
  const project = context.packager.projectDir;
  const source = path.resolve(project, process.env.THIMBLE_BUILD_DIST || 'build/backend', 'thimble-backend.exe');
  const target = path.join(context.appOutDir, 'resources', 'backend', 'thimble-backend.exe');
  let expected;
  try {
    expected = await fs.readFile(source);
  } catch (cause) {
    throw new Error(`未找到本次构建的后端，请先构建后端：${source}`, {cause});
  }
  if (expected.length < 2 || expected.subarray(0, 2).toString() !== 'MZ') {
    throw new Error(`后端不是有效的 Windows 可执行文件：${source}`);
  }
  await fs.mkdir(path.dirname(target), {recursive:true});
  await fs.copyFile(source, target);
  const hash = bytes => createHash('sha256').update(bytes).digest('hex');
  const digest = hash(expected);
  if (hash(await fs.readFile(target)) !== digest) {
    throw new Error('打包后端与本次构建不一致，已停止生成发布包。');
  }
  console.log(`Packaged backend SHA256: ${digest}`);
};
