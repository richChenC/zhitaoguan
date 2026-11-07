const assert = require('node:assert/strict');
const { createWindowCloseGuard } = require('../src/desktop/window-close-guard.cjs');

async function run() {
  let prevented = 0;
  let prompts = 0;
  let closes = 0;
  let resolvePrompt;
  let discard = false;
  const promptGate = new Promise(resolve => { resolvePrompt = resolve; });
  const guard = createWindowCloseGuard({
    isDirty: async () => true,
    confirmDiscard: async () => { prompts++; return prompts === 1 ? promptGate : discard; },
    close: () => { closes++; }
  });
  const event = { preventDefault: () => { prevented++; } };

  const first = guard(event);
  await new Promise(resolve => setImmediate(resolve));
  const second = await guard(event);
  assert.equal(second, false);
  assert.equal(prompts, 1, 'repeated close clicks must not open duplicate dialogs');
  assert.equal(closes, 0);

  resolvePrompt(false);
  await first;
  assert.equal(closes, 0, 'choosing continue editing must keep the window open');
  discard = true;
  await guard(event);
  assert.equal(prompts, 2, 'a later close attempt can request confirmation again');
  assert.equal(closes, 1, 'confirming discard must close the window');
  assert.equal(await guard(event), true, 'the guarded close must be allowed through');
  assert.equal(closes, 1, 'the final native close must not recurse');

  const cleanClose = createWindowCloseGuard({
    isDirty: async () => false,
    confirmDiscard: async () => { throw new Error('clean close must not prompt'); },
    close: () => { closes++; }
  });
  await cleanClose(event);
  assert.equal(closes, 2, 'clean windows close without a confirmation prompt');
  assert.equal(prevented, 4, 'every pending close is prevented until explicitly allowed');
  console.log('PASS window close guard prevents duplicate prompts and protects dirty edits');
}

run().catch(error => { console.error(error); process.exitCode = 1; });
