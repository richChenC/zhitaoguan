const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/../src/desktop-ui/date-format.js`, 'utf8');
const context = { window: {}, Intl, Date };
vm.runInNewContext(source, context);
const format = context.window.formatDateTime;

assert.equal(format('2026-11-03T18:45:38.094069'), '2026-11-03 18:45:38');
assert.equal(format('2026-11-03 18:45:38'), '2026-11-03 18:45:38');
assert.equal(format(''), '/');
assert.equal(format(null), '/');
assert.equal(format('not-a-date'), 'not-a-date');
console.log('date format checks passed');
