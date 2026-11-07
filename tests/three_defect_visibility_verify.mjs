import assert from 'node:assert/strict';
import fs from 'node:fs';

const source=fs.readFileSync('src/desktop-ui/visualizations/reference-thimble/defect-location.js','utf8');
const {isPointVisible,isDefect}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
for(const mode of ['joint','full','socket']){
  for(let selected=1;selected<=50;selected++){
    for(let thimble=1;thimble<=50;thimble++){
      assert.equal(isPointVisible(mode,thimble,selected),thimble===selected,`${mode} tube ${thimble} selected ${selected}`);
    }
  }
}
for(let thimble=1;thimble<=50;thimble++){
  assert.equal(isPointVisible('assembly',thimble,1),true);
  assert.equal(isPointVisible('plate',thimble,thimble),false,'Plan view must not overlay projected 3D markers');
}
assert.equal(isDefect({indication:'WAR',percent:null,location:'P1'}),true,'Missing depth must not hide an indication');
assert.equal(isDefect({indication:'WAR',percent:0,location:'P1'}),true,'Reported zero must remain a real numeric value');
for(const row of [{indication:'NDD'},{indication:'NONE'},{indication:'CAL'},{filename:'DIR999.ect',indication:'WAR',location:'P1'}]){
  assert.equal(isDefect(row),false,'NDD and calibration records must not become defect markers');
}
console.log('Reference single-model visibility follows selected physical tubes across all modes; NDD and calibration never become markers.');
