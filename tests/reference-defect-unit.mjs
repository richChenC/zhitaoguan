import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const source = await fs.readFile(new URL('../src/desktop-ui/visualizations/reference-thimble/defect-location.js', import.meta.url), 'utf8');
const { isNoDefect, isDefect, isPointVisible, pointPresentation, findingDetails, parseDefectLocation, defectPlacement, resolveWorkspaceScope, filterScopeRows, positionFor, thimbleForPosition, channelForFinding, canonicalSite } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

for (const mode of ['joint', 'full', 'socket']) {
  assert.equal(isPointVisible(mode, 15, 15), true);
  assert.equal(isPointVisible(mode, 42, 15), false);
}
assert.equal(isPointVisible('assembly', 42, 15), true);
assert.equal(isPointVisible('plate', 15, 15), false);
assert.equal(pointPresentation({mode:'assembly',cutPrv:true}, {x:1}, '').visible, false);
assert.equal(pointPresentation({mode:'assembly',cutPrv:true}, {x:-1}, '').visible, true);
assert.equal(pointPresentation({mode:'full',cut:true,cutPos:-5,fat:false}, {x:0}, '').visible, false);
assert.equal(pointPresentation({mode:'full',cut:true,cutPos:-5,fat:true}, {x:0}, '').visible, true);
assert.equal(pointPresentation({mode:'assembly',typeFilter:'II'}, {x:0,position:'N5',channel:{type:'I'}}, 'N5').faded, false);
assert.equal(pointPresentation({mode:'assembly',typeFilter:'II'}, {x:0,position:'N5',channel:{type:'I'}}, 'H1').faded, true);
assert.equal(isNoDefect({ indication: 'NDD', percent: 40, location: 'P1+30' }), true);
assert.equal(isDefect({ indication: 'NDD', percent: 40, location: 'P1+30' }), false);
assert.equal(isDefect({ indication: 'WAR', percent: null, location: 'P1' }), true);
assert.equal(isDefect({ indication: '', measurement_type: 'Vmax', location: 'P4+20' }), true);
assert.equal(isDefect({ indication: 'CAL', percent: 50, location: 'P1' }), false);
assert.equal(isDefect({ indication: 'Calibration', percent: 50, location: 'P1' }), false);
assert.equal(isDefect({ indication: 'WAR', percent: 50, filename: 'DIR999C003I004.ECT' }), false);
assert.equal(isDefect({ indication: 'WAR', percent: 50, filename: 'D:\\ECT\\DIR999C003I004.ECT' }), false);
assert.equal(isDefect({ indication: 'WAR', percent: 50, filename: '/ect/DIR999C003I004.ECT' }), false);
assert.equal(isDefect({ indication: 'WAR', location: 'P1', thimble_id: 1, channel: 'DIR999' }), false);
assert.equal(isDefect({ indication: 'WAR', location: 'P1', thimble_id: 1, channel: 'DIR999:CAL' }), false);
assert.equal(isDefect({ indication: 'WAR', location: 'P1', thimble_id: 1, channel_id: 'DIR999:CAL' }), false);
assert.equal(isDefect({ indication: 'WAR', location: 'P1', thimble_id: 1, channel: 'C3', channel_id: 'DIR999' }), false);
assert.equal(isDefect({ indication: '/', location: '/' }), false);
assert.equal(isDefect({ indication: 'NA', location: '' }), false);
assert.equal(isDefect({ indication: '/', location: 'P3' }), true);

assert.deepEqual(parseDefectLocation('P1 + -42 mm'), { zone: 'P1', offset_mm: -42 });
assert.deepEqual(parseDefectLocation('P4 - 12.5 mm'), { zone: 'P4', offset_mm: -12.5 });
assert.equal(parseDefectLocation('P10+20'), null);
assert.equal(parseDefectLocation(`P1+${'9'.repeat(400)}`),null);
const geometry = { length: 3000, topY: 1117.4, planes: [{name:'P1', y:1117.4, status:'确认'}, {name:'P5', y:-1280.1, status:'推定'}, {name:'P6', y:-1882.6, status:'确认'}] };
const placement = defectPlacement('P1-42', geometry);
assert.equal(placement.offset_mm, -42);
assert.equal(placement.y, 1159.4);
assert.equal(placement.offsetApplied, true);
assert.equal(placement.schematic, true);
assert.equal(defectPlacement('P6+20', geometry).y, -1902.6);
assert.equal(defectPlacement('P4', geometry), null);
assert.match(defectPlacement('P5', geometry).note, /推定/);
const shifted = defectPlacement('P1+20',geometry,{state:'shifted',offset_mm:50,offset_confirmed:1,note:'割管移位 +50 mm'});
assert.equal(shifted.y,1047.4);
assert.equal(shifted.maintenanceApplied,true);
assert.equal(shifted.effective_offset_mm,70);
assert.match(shifted.note,/维护后示意/);
assert.equal(defectPlacement('P1+20',geometry,{state:'shifted',offset_mm:-50}).y,1147.4);
const unsigned = defectPlacement('P1+20',geometry,{state:'shifted',offset_mm:50,offset_confirmed:0,unsigned_offset_mm:50});
assert.equal(unsigned.y,1097.4);
assert.equal(unsigned.maintenanceApplied,false);
assert.match(unsigned.note,/方向未确认/);
assert.equal(defectPlacement('P1+20',geometry,{state:'normal',offset_mm:50}).y,1097.4);
assert.equal(defectPlacement('P1+20',geometry,{state:'shifted',state_recorded:0,offset_mm:50}).y,1097.4);
assert.equal(defectPlacement('P1+20',geometry,{state:'shifted',offset_mm:null}).maintenanceApplied,false);

const row = { id: 1, site_code:'H', outage:'H209', unit_id:2, thimble_id:42, indication:'WAR', percent:43, location:'P1 + -42 mm', channel:'C3', analyst:'A', calgroup:'G1', report_path:'D:\\reports\\sample.RPT', comment:'original comment', analysis:'review' };
const details = new Map(findingDetails(row, placement));
assert.equal(details.get('磨损位置'), 'P1 + -42 mm');
assert.equal(details.get('磨损深度（壁厚%）'), '43%');
assert.equal(details.get('测量通道'), 'C3');
assert.equal(details.get('分析人员'), 'A');
assert.equal(details.get('RPT 报告文件'), 'sample.RPT');
assert.match(details.get('备注'), /original comment/);
assert.match(details.get('模型定位'), /示意/);
const maintenanceDetails = new Map(findingDetails({...row,state:'shifted',offset_mm:50,note:'割管移位 +50 mm',state_source:'维护台账 Sheet2 第3行'},shifted));
assert.match(maintenanceDetails.get('维护记录'),/割管移位/);
assert.match(maintenanceDetails.get('维护来源'),/Sheet2/);
const effectiveDetails = new Map(findingDetails(row,placement,{last_maintenance:'H208',state_label:'堵管 · 移位',shifted:true,cumulative_offset_mm:12}));
assert.equal(effectiveDetails.get('管子状态'),'堵管 · 移位');
assert.equal(effectiveDetails.get('移位距离'),'12 mm');
assert.equal(new Map(findingDetails(row,placement,null,'failed')).get('管子状态'),'管子状态加载失败');

assert.equal(positionFor(2, 42), 'N5');
assert.equal(positionFor(1, 15), 'N5');
for (let unit = 1; unit <= 120; unit++) {
  for (let tube = 1; tube <= 50; tube++) assert.equal(thimbleForPosition(unit, positionFor(unit, tube)), tube);
}
assert.equal(channelForFinding(row, [{pos:'N5', L:3010, V:300}]).L, 3010);
assert.equal(resolveWorkspaceScope({}, [row]).ok, true);
assert.equal(canonicalSite('LHNP'), 'H');
assert.deepEqual(filterScopeRows([row, {...row, id: 9, site_code: 'LHNP'}], {site: 'H', unit: 2, outage: 'H209'}).map(item => item.id), [1, 9]);
assert.equal(resolveWorkspaceScope({unit:2}, []).ok, false);
assert.equal(resolveWorkspaceScope({unit:0,outage:'H209'}, []).ok, false);
assert.equal(resolveWorkspaceScope({}, [row, {...row, unit_id:1}]).ok, false);
assert.equal(resolveWorkspaceScope({}, [row, {...row, outage:'H210'}]).ok, false);
assert.equal(resolveWorkspaceScope({unit:1,outage:'H209'}, [row]).ok, false);
assert.deepEqual(filterScopeRows([row, {...row,id:2,outage:'H210'}], {site:'H',unit:2,outage:'H209'}), [row]);
console.log('Reference defect business helpers passed.');
