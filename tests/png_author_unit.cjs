'use strict';
const assert = require('node:assert/strict');
const {withPngAuthor} = require('../src/desktop/png-author.cjs');

const input = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg==', 'base64');
const first = withPngAuthor(input, 'zs');
const second = withPngAuthor(first, 'li');
assert.ok(first.includes(Buffer.from('Author\0zs')));
assert.ok(second.includes(Buffer.from('Author\0li')));
assert.ok(!second.includes(Buffer.from('Author\0zs')));
assert.throws(() => withPngAuthor(input.subarray(0, -1), 'zs'));
assert.throws(() => withPngAuthor(input, '伪造'));
console.log('PNG author metadata tests passed');
