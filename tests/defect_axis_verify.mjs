import assert from 'node:assert/strict';
import fs from 'node:fs';

const source=fs.readFileSync('src/desktop-ui/visualizations/reference-thimble/defect-location.js','utf8');
const {positionFor,thimbleForPosition,channelForFinding}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const {channels}=JSON.parse(fs.readFileSync('src/desktop-ui/visualizations/reference-thimble/data/vessel_layout.json','utf8'));

assert.equal(channels.length,50);
assert.equal(new Set(channels.map(channel=>channel.pos)).size,50);
for(let unit=1;unit<=120;unit++){
  for(let thimble=1;thimble<=50;thimble++){
    const expected=positionFor(unit,thimble);
    // Stored coordinates can be stale. Physical identity and current unit parity own the axis.
    const row={unit_id:unit,thimble_id:thimble,position:'M5'};
    const channel=channelForFinding(row,channels,unit);
    assert.ok(channel,`Missing axis for unit ${unit}, tube ${thimble}`);
    assert.equal(channel.pos,expected);
    assert.equal(thimbleForPosition(unit,channel.pos),thimble);
    assert.equal(channel.x,channels.find(candidate=>candidate.pos===expected).x);
    assert.equal(channel.z,channels.find(candidate=>candidate.pos===expected).z);
  }
}
assert.equal(positionFor(1,15),'N5');
assert.equal(positionFor(2,42),'N5');
assert.equal(positionFor(2,27),'J15');
for(const thimble of [0,51,999,-1,1.5]){
  assert.equal(channelForFinding({unit_id:2,thimble_id:thimble,position:'N5'},channels,2),null);
}
console.log('All 6,000 tube axes use official parity mapping and reference geometry, never stale stored coordinates.');
