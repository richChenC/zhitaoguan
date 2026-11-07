const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { test } = require('node:test');
const { loadWindowPage } = require('../src/desktop/window-loading.cjs');

function fixture(load) {
  const state = {calls:0, stops:0, destroyed:false, log:[]};
  const window = Object.assign(new EventEmitter(), {
    isDestroyed:() => state.destroyed,
    loadURL:async url => { state.calls++; return load(state, url); },
    webContents:{stop:() => { state.stops++; }}
  });
  const options = {pause:async () => {}, log:message => state.log.push(message)};
  return {state, window, options};
}

test('transient loading failure retries and succeeds in the same window', async () => {
  const {state,window,options} = fixture(async (state, url) => {
    assert.equal(url, 'http://127.0.0.1:18767/');
    if (state.calls === 1) throw new Error('ERR_ABORTED');
  });
  assert.equal(await loadWindowPage(window, 'http://127.0.0.1:18767/', options), true);
  assert.equal(state.calls, 2);
  assert.equal(state.log.length, 1);
});

test('persistent failures are bounded and preserve the final error', async () => {
  const error = new Error('ERR_CONNECTION_REFUSED');
  const {state,window,options} = fixture(async () => { throw error; });
  await assert.rejects(loadWindowPage(window, '/', options), failure => failure === error);
  assert.equal(state.calls, 3);
  assert.equal(state.log.length, 3);
});

test('closing during navigation cancels retry', async () => {
  const {state,window,options} = fixture(async state => {
    state.destroyed = true; window.emit('closed');
    throw new Error('Window closed');
  });
  assert.equal(await loadWindowPage(window, '/', options), false);
  assert.equal(state.calls, 1);
});

test('stalled navigation stops before retry and eventually reports timeout', async () => {
  const {state,window,options} = fixture(() => new Promise(() => {}));
  await assert.rejects(loadWindowPage(window, '/', {...options, timeout:10}), /timed out/);
  assert.equal(state.calls, 3);
  assert.equal(state.stops, 3);
});

test('already closed windows do not navigate', async () => {
  const {state,window,options} = fixture(async () => {});
  state.destroyed = true;
  assert.equal(await loadWindowPage(window, '/', options), false);
  assert.equal(state.calls, 0);
});
