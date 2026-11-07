import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';

const filename = fileURLToPath(new URL('../src/desktop-ui/modules/report-draft-editor.js', import.meta.url));
const {ReportDraft, draftText} = await import('data:text/javascript;base64,' + fs.readFileSync(filename).toString('base64'));
const draft = new ReportDraft();
draft.load([
  {key:'numeric', label:'磨损深度', value:0, type:'number'},
  {key:'note', label:'备注', value:'割管移位 20 mm\n原文不删减', type:'text'},
  {key:'position', label:'测量通道', value:'M1:4-6', type:'text'}
]);
assert.equal(draftText(null), '/');
assert.equal(draftText(0), '0');
assert.equal(draftText(-2.5), '-2.5');
draft.change('numeric', '-2.5');
assert.deepEqual(draft.payload(), [{key:'numeric',value:-2.5}]);
assert.equal(draft.cells.get('numeric').value, 0);
assert.equal(draft.undo(), true);
assert.deepEqual(draft.payload(), []);
assert.equal(draft.undo(), false);
draft.change('numeric', '-2.5');
assert.throws(() => draft.change('numeric', '20%'), /有效数字/);
assert.throws(() => draft.change('numeric', 'Infinity'), /有效数字/);
draft.change('numeric', '/');
assert.deepEqual(draft.payload(), [{key:'numeric',value:null}]);
assert.equal(draft.undo(), true);
assert.deepEqual(draft.payload(), [{key:'numeric',value:-2.5}]);
draft.change('numeric', '0');
assert.deepEqual(draft.payload(), []);
const rawNote = '  割管移位-待复核\n保留原文、标点、空格  ';
draft.change('note', rawNote);
assert.equal(draft.payload()[0].value, rawNote);
draft.load([{key:'note', label:'备注', value:rawNote, source_value:'割管移位 20 mm\n原文不删减', type:'text'}]);
assert.equal(draft.sourceValue(draft.cells.get('note')), '割管移位 20 mm\n原文不删减');
draft.restore('note');
assert.deepEqual(draft.payload(), []);
assert.equal(draft.undo(), true);
assert.deepEqual(draft.payload(), [{key:'note',value:rawNote}]);
draft.change('note', '更改');
draft.reset();
assert.deepEqual(draft.payload(), []);
assert.equal(draft.undo(), true);
assert.deepEqual(draft.payload(), [{key:'note',value:'更改'}]);
draft.clear();
assert.equal(draft.undo(), false);
assert.throws(() => draft.change('missing', 'x'), /单元格已变化/);
console.log('Report draft: numeric validation, verbatim text, source provenance, restore, undo and context reset passed.');
