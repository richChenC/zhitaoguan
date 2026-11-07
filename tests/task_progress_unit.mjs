import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';

const source = fs.readFileSync(new URL('../src/desktop-ui/task-progress.js', import.meta.url), 'utf8');
const wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
function fixture(mode) {
  const stats = {polls: 0, updates: []};
  const window = {};
  const context = {window, crypto: webcrypto, AbortController, setTimeout,
    console: {warn() {}},
    fetch: async (url, options) => {
      if (url.includes('/api/import-progress?')) {
        stats.polls++;
        if (mode === 'unavailable') return {ok: false, status: 500};
        if (mode === 'pending') return {ok: true, json: async () => ({status: 'pending'})};
        return {ok: true, json: async () => ({status: 'running', stage: '读取数据',
          completed: stats.polls * 2, total: 10, unit: '行', percent: stats.polls * 20,
          elapsed_seconds: stats.polls, remaining_seconds: 2})};
      }
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve({ok: mode !== 'failure',
          json: async () => mode === 'failure' ? {error: '写入失败'} : {inserted: 10}}), 700);
        options.signal?.addEventListener('abort', () => {
          clearTimeout(timer);
          reject(new DOMException('Aborted', 'AbortError'));
        }, {once: true});
      });
    }};
  vm.runInNewContext(source, context);
  return {window, stats, update: value => stats.updates.push(value)};
}

const success = fixture('success');
assert.equal((await success.window.runImportRequest('/api/import-excel', {}, success.update)).inserted, 10);
assert(success.stats.updates.length >= 2);
assert.deepEqual(success.stats.updates.map(value => value.percent), [20, 40, 100]);
assert.equal(success.stats.updates.at(-1).status, 'succeeded');
const count = success.stats.polls;
await wait(400);
assert.equal(success.stats.polls, count, 'No polling after completion');

const failure = fixture('failure');
await assert.rejects(failure.window.runImportRequest('/api/import-excel', {}, failure.update), /写入失败/);
assert(!failure.stats.updates.some(value => value.status === 'succeeded'));

const cancelled = fixture('success');
const controller = new AbortController();
const aborted = cancelled.window.runImportRequest('/api/import-excel', {}, cancelled.update, {signal: controller.signal});
controller.abort();
await assert.rejects(aborted, {name: 'AbortError'});
assert.equal(cancelled.stats.polls, 0, 'Cancelling the read also stops progress polling');

const pending = fixture('pending');
await pending.window.runImportRequest('/api/import-excel', {}, pending.update);
assert.equal(pending.stats.updates.length, 1, 'Only the authoritative completed request may report completion');
assert.equal(pending.stats.updates[0].percent, 100);

const unavailable = fixture('unavailable');
assert.equal((await unavailable.window.runImportRequest('/api/import-excel', {}, unavailable.update)).inserted, 10);
assert.equal(unavailable.stats.updates[0].percent, null);
assert.equal(unavailable.window.importProgressDetails(unavailable.stats.updates[0]).meta, '等待本机返回处理结果');
console.log('PASS live progress, cleanup, cancellation, failure and unavailable monitoring');
