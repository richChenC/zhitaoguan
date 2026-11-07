const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {test} = require('node:test');
const {saveArtifact} = require('../src/desktop/artifact-save.cjs');

async function fixture(t) {
  const base = await fs.realpath(process.env.THIMBLE_TEST_OUTPUT_ROOT || os.tmpdir());
  const directory = await fs.mkdtemp(path.join(base, 'artifact-save-'));
  t.after(async () => {
    const resolved = await fs.realpath(directory);
    assert.equal(path.dirname(resolved), base);
    await fs.rm(resolved, {recursive:true, force:true});
  });
  const target = path.join(directory, '原有图表.png');
  await fs.writeFile(target, 'previous complete artifact');
  return {directory, target};
}

test('successful save replaces a confirmed target without leftover temporary files', async t => {
  const {directory,target} = await fixture(t);
  await saveArtifact(target, Buffer.from('new complete artifact'));
  assert.equal(await fs.readFile(target, 'utf8'), 'new complete artifact');
  assert.deepEqual(await fs.readdir(directory), [path.basename(target)]);
});

test('partial disk-full write preserves the existing file and permits a retry', async t => {
  const {directory,target} = await fixture(t);
  const original = fs.writeFile;
  fs.writeFile = async (file, content, options) => {
    await original(file, 'partially written', options);
    throw Object.assign(new Error('disk full'), {code:'ENOSPC'});
  };
  try {
    await assert.rejects(saveArtifact(target, 'replacement'), error => error.code==='ENOSPC' && /磁盘空间不足/.test(error.message));
  } finally { fs.writeFile = original; }
  assert.equal(await fs.readFile(target, 'utf8'), 'previous complete artifact');
  assert.deepEqual(await fs.readdir(directory), [path.basename(target)]);
  await saveArtifact(target, 'retried complete artifact');
  assert.equal(await fs.readFile(target, 'utf8'), 'retried complete artifact');
});

test('locked destination leaves the original intact and cleans the staged file', async t => {
  const {directory,target} = await fixture(t);
  const original = fs.rename;
  fs.rename = async () => { throw Object.assign(new Error('locked'), {code:'EPERM'}); };
  try {
    await assert.rejects(saveArtifact(target, 'replacement'), /文件被占用或没有写入权限/);
  } finally { fs.rename = original; }
  assert.equal(await fs.readFile(target, 'utf8'), 'previous complete artifact');
  assert.deepEqual(await fs.readdir(directory), [path.basename(target)]);
});

test('missing directory reports a clear recovery action', async t => {
  const {directory} = await fixture(t);
  await assert.rejects(saveArtifact(path.join(directory,'removed','report.json'), '{}'), /重新选择保存位置/);
});
