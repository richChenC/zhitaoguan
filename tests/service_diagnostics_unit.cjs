const assert = require('node:assert/strict');
const path = require('node:path');
const {test} = require('node:test');
const {availableBytes, startupFailureMessage, LOW_SPACE_BYTES} = require('../src/desktop/service-diagnostics.cjs');

const failed = {code:'SERVICE_START_FAILED'};
const options = {tempDirectory:path.resolve('temp'), dataDirectory:path.resolve('data'), logPath:'service.log'};

test('low temporary space is a possible cause, not a definitive diagnosis', () => {
  const message = startupFailureMessage(failed, {...options, statfs:location =>
    ({bavail:location === options.tempDirectory ? 0 : LOW_SPACE_BYTES * 2, bsize:1})});
  assert.match(message, /临时目录所在磁盘|以下目录所在磁盘/);
  assert.match(message, /可能影响启动/);
  assert.match(message, /临时目录/);
  assert.doesNotMatch(message, /数据目录：/);
  assert.match(message, /启动日志（如已生成）/);
});

test('inaccessible filesystem falls back to general guidance', () => {
  const message = startupFailureMessage(failed, {...options, statfs:() => { throw Object.assign(new Error(), {code:'EACCES'}); }});
  assert.match(message, /可用空间和访问权限/);
  assert.doesNotMatch(message, /空间较少/);
});

test('a missing data directory checks its existing parent', () => {
  const child = path.join(path.parse(process.cwd()).root, 'missing', 'data');
  const parent = path.dirname(child);
  const checked = [];
  assert.equal(availableBytes(child, location => {
    checked.push(location);
    if (location === child) throw Object.assign(new Error(), {code:'ENOENT'});
    return {bavail:4, bsize:4096};
  }), 16384);
  assert.deepEqual(checked, [child, parent]);
});

test('explicit filesystem errors get actionable, distinct messages', () => {
  assert.match(startupFailureMessage({code:'ENOSPC'}), /磁盘空间不足/);
  assert.match(startupFailureMessage({code:'EACCES', path:'profile'}), /访问权限[\s\S]*profile/);
  assert.match(startupFailureMessage({code:'ENOTDIR', path:'profile'}), /同名文件[\s\S]*profile/);
  assert.match(startupFailureMessage(new Error('本地数据服务端口设置无效。')), /端口设置无效/);
});

test('invalid capacity results do not produce a low-space diagnosis', () => {
  assert.equal(availableBytes(options.tempDirectory, () => ({bavail:NaN, bsize:4096})), null);
  assert.doesNotMatch(startupFailureMessage(failed, {...options, statfs:() => ({bavail:NaN, bsize:1})}), /空间较少/);
});
