import assert from 'node:assert/strict';
import fs from 'node:fs';

const app=fs.readFileSync('src/desktop-ui/app.js','utf8');
const source=fs.readFileSync('src/desktop-ui/visualizations/reference-thimble/defect-location.js','utf8');
const {resolveWorkspaceScope,filterScopeRows,canonicalSite}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

assert.ok(app.includes('const outages=available.map(x=>x.outage)'), 'Report outages must not be narrowed by a hidden unit selection');
assert.ok(app.includes("$('#reportOutage').addEventListener('change',refreshReportFilters)"),'Report outage changes must synchronize the unit');
const rows=[
  {id:1,site_code:'H',unit_id:2,outage:'H209',thimble_id:15},
  {id:2,site_code:'H',unit_id:2,outage:'H209',thimble_id:42},
  {id:3,site_code:'H',unit_id:1,outage:'H109',thimble_id:15},
  {id:4,site_code:'N',unit_id:2,outage:'H209',thimble_id:15},
  {id:5,site_code:'H',unit_id:2,outage:'H210',thimble_id:15},
];
for(const scope of [{},{site:'H'},{site:'H',unit:'2'},{site:'H',unit:'0',outage:'H209'},{unit:'1.5',outage:'H209'}]){
  assert.equal(resolveWorkspaceScope(scope).ok,false,'Ambiguous scope must not combine units or outages');
}
const resolved=resolveWorkspaceScope({},rows.slice(0,2));
assert.equal(resolved.ok,true);
assert.deepEqual(resolved.scope,{site:'H',unit:'2',outage:'H209',thimble:''});
assert.deepEqual(filterScopeRows(rows,resolved.scope).map(row=>row.id),[1,2]);
assert.deepEqual(filterScopeRows(rows,{...resolved.scope,thimble:'15'}).map(row=>row.id),[1]);
assert.equal(resolveWorkspaceScope({site:'N',unit:'2',outage:'H209'},rows.slice(0,2)).ok,false);
assert.equal(resolveWorkspaceScope({selectionBlocked:true},rows.slice(0,2)).ok,false);
for(const other of rows.slice(2)){
  const invalid=resolveWorkspaceScope({},[rows[0],other]);
  assert.equal(invalid.ok,false,'Mixed selected scopes must be rejected');
  assert.deepEqual(invalid.selectedItems,[],'Blocked selections must not survive in the overlay');
}
assert.deepEqual(filterScopeRows(rows,{site:'H',unit:'2',outage:'missing'}),[]);
const legacyRows=[rows[0],{...rows[1],id:6,site_code:'LHNP'}];
assert.equal(canonicalSite('LHNP'),'H');
assert.equal(resolveWorkspaceScope({},legacyRows).ok,true,'Legacy and canonical site codes must be treated as one plant');
assert.deepEqual(filterScopeRows(legacyRows,{site:'H',unit:'2',outage:'H209'}).map(row=>row.id),[1,6]);
console.log('Reference defect scopes preserve report controls and reject mixed sites, units, outages, or stale selections.');
