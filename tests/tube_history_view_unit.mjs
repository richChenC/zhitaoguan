import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('src/desktop-ui/modules/analytics/tube-history-view.js', 'utf8');
const {renderTubeHistory} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

const tube = {tube: 7, position: 'A1', series: [
  {outage:'N101', generation:1, conclusion:'WAR', records:3, findings:[
    {indication:'WAR', location:'P1', percent:20, channel:'M1', source:'report'},
    {indication:'WAR', location:'P4+42', percent:null},
    {indication:'NDD', location:'', percent:null},
  ], current_events:['shifted'], maintenance_unsigned_offset_mm:42, maintenance_note:'待核对 <script>alert(1)</script>'},
  {outage:'N103', generation:2, conclusion:'WAR', records:1, findings:[
    {indication:'WAR', location:'P1+42', percent:35},
  ], current_events:['replaced'], replaced:true},
  {outage:'N104', generation:2, conclusion:'无检测记录', records:0, findings:[],
    current_events:['plugged'], plugged:true},
]};
const outages = ['N101','N102','N103','N104'].map(outage => ({outage}));
const html = renderTubeHistory(tube, 'N1', outages);
assert.equal((html.match(/class="tube-history-round"/g) || []).length, 4);
assert.equal((html.match(/class="tube-history-finding"/g) || []).length, 4);
for (const text of ['N1 · 7号管', 'P1', 'P4+42', 'WAR 2 条', '20%', '深度未记录',
  '距离 42 mm（方向未确认）', 'N102', '无检测记录', '换管', '检测记录的管子代次须核对',
  '堵管', '截至本次有效状态：堵管', '不自动推断缺陷一一对应']) assert.ok(html.includes(text), text);
assert.ok(html.indexOf('N101') < html.indexOf('N102') && html.indexOf('N102') < html.indexOf('N103'));
assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
assert.ok(!html.includes('<script>'));
assert.ok(!renderTubeHistory(null, 'N1'));
assert.ok(renderTubeHistory({tube:1, position:'', series:[]}, 'N1').includes('暂无检测或维护记录'));
const missing = renderTubeHistory({tube:1, series:[
  {outage:'N101', order:1, records:1, conclusion:'NDD', findings:[{indication:'NDD'}]},
  {outage:'N104', order:4, records:0, current_events:['plugged'], findings:[]},
  {outage:'N105', order:5, records:2},
]}, 'N1', [{outage:'N101',order:1},{outage:'N104',order:4},{outage:'N105',order:5}]);
assert.ok(missing.includes('第 2 至 3 次大修：当前机组数据中未找到检测或维护记录'));
assert.equal((missing.match(/WAR 数量未知/g) || []).length, 2);
assert.equal((missing.match(/WAR 0 条/g) || []).length, 1);
assert.ok(missing.includes('检测明细未提供'));
assert.ok(!missing.includes('data-history-records="N104"'));
assert.ok(missing.includes('data-history-records="N105"'));
const singleGap = renderTubeHistory({tube:1,series:[]}, 'N1', [{outage:'N101',order:1},{outage:'N103',order:3}]);
assert.ok(singleGap.includes('第 2 次大修：'));
assert.ok(!singleGap.includes('N102'));
console.log('Tube history renders all findings, missing rounds, maintenance and escaped text.');
