import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';

const filename=fileURLToPath(new URL('../src/desktop-ui/modules/report-scope.js',import.meta.url));
const {parseOutage,historicalOutages,validateReportScope}=await import('data:text/javascript;base64,'+fs.readFileSync(filename).toString('base64'));

assert.deepEqual(parseOutage('N109'),{site:'N',unit:1,sequence:9});
assert.deepEqual(parseOutage('LF101'),{site:'LF',unit:1,sequence:1});
assert.equal(parseOutage('N109x'),null);
assert.deepEqual(historicalOutages(['N105','N104','D116','N204','N110','N105'],'N109'),['N105','N104']);
validateReportScope({site:'LF',unit:1,outage:'LF101'},'LF100');
assert.throws(()=>validateReportScope({site:'N',unit:1,outage:'N109'},'D105'),/同一基地/);
assert.throws(()=>validateReportScope({site:'N',unit:2,outage:'N109'}),/一致的基地/);

console.log('Report scope validation: station, unit and chronological history passed.');
