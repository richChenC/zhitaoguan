const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {observeDownloads} = require('../src/desktop/download-feedback.cjs');

const session = new EventEmitter();
observeDownloads(session);
const events = [];
let destroyed = false;
const contents = {
  isDestroyed: () => destroyed,
  send: (channel, payload) => events.push({channel, ...payload}),
};
function start(filename) {
  const item = new EventEmitter();
  item.getFilename = () => filename;
  session.emit('will-download', {}, item, contents);
  return item;
}
const complete = start('台账.xlsx');
complete.emit('updated', {}, 'progressing');
complete.emit('done', {}, 'completed');
assert.deepEqual(events.pop(), {channel:'desktop-download-status', state:'completed', filename:'台账.xlsx'});
const interrupted = start('报告.docx');
interrupted.emit('updated', {}, 'interrupted');
interrupted.emit('updated', {}, 'interrupted');
interrupted.emit('done', {}, 'interrupted');
assert.deepEqual(events, [{channel:'desktop-download-status', state:'interrupted', filename:'报告.docx'}]);
events.length = 0;
const cancelled = start('图片.png');
cancelled.emit('done', {}, 'cancelled');
assert.equal(events.pop().state, 'cancelled');
const resumed = start('重试.xlsx');
resumed.emit('updated', {}, 'interrupted');
resumed.emit('done', {}, 'completed');
assert.deepEqual(events.map(event => event.state), ['interrupted', 'completed']);
events.length = 0;
destroyed = true;
start('关闭窗口.xlsx').emit('done', {}, 'completed');
assert.deepEqual(events, []);
console.log('download feedback unit: passed');
