import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync('src/desktop-ui/visualizations/reference-thimble/defect-location.js','utf8');
const {defectPlacement}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const planes=[['P1',1.35],['P6',-5.85]];
assert.equal(defectPlacement('',planes),null);
assert.equal(defectPlacement('unknown P1',planes),null);
assert.equal(defectPlacement('P10',planes),null);
assert.equal(defectPlacement('P2',planes),null);
assert.equal(defectPlacement('P1+42',planes).offset_mm,42);
assert.equal(defectPlacement('P1 - 42 mm',planes).offset_mm,-42);
assert.equal(defectPlacement('P1 + -42 mm',planes).offset_mm,-42);
assert.equal(defectPlacement('P1 + 42 mm',planes).y,1.35-42);
assert.equal(defectPlacement('P1 - 42 mm',planes).y,1.35+42);
assert.equal(defectPlacement('P6',planes).y,-5.85);
assert.equal(defectPlacement('Point 1',planes).y,1.35);
assert.equal(defectPlacement('Point 4',planes),null);
assert.equal(defectPlacement('ＰＯＩＮＴ　１＋４２毫米',planes).offset_mm,42);
assert.equal(defectPlacement('Ｐ１＋４２毫米',planes).offset_mm,42);
assert.equal(defectPlacement('P1 − 42 mm',planes).offset_mm,-42);
assert.equal(defectPlacement('PI+168',planes),null);
assert.equal(defectPlacement('M1a4-6',planes),null);
const geometry={
  topY:1117.4,
  length:3000,
  planes:[
    {name:'P1',y:1117.4,status:'drawing',basis:'reference P1 datum'},
    {name:'P6',y:-1882.6,status:'source-length',basis:'individual channel length'},
  ],
};
assert.equal(defectPlacement('unparsed',geometry),null);
assert.equal(defectPlacement('P2',geometry),null);
assert.equal(defectPlacement('P6',geometry).y,-1882.6);
for(const [location,offset] of [['P1+42',42],['P1 - 42 mm',-42],['P1 + -42 mm',-42]]){
  const placement=defectPlacement(location,geometry);
  assert.equal(placement.offset_mm,offset);
  assert.equal(placement.y,1117.4-offset);
  assert.equal(placement.offsetApplied,true);
  assert.equal(placement.calibrated,false);
  assert.equal(placement.schematic,true);
  assert.ok(placement.basis);
}
console.log('Reference model locations preserve signed offsets, explicit baselines, and unresolved positions without inventing calibration.');
