import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../src/desktop-ui/modules/analytics/status-change-model.js',import.meta.url),'utf8');
const {statusChangeComparison, matchesChangeFilter, unitParity} =
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const tube = (id, depth, extra={}) => ({tube:id, position:`B${id}`, coverage:'defect',
  max_depth:depth, state_recorded:false, current_events:[], state_badges:[], ...extra});
const snapshot = (order,tubes,unit='D1') => ({unit,order,outage:`${unit}${String(order).padStart(2,'0')}`,tubes});
const old = snapshot(1,[
  tube(1,10),tube(2,30),tube(3,null,{coverage:'NDD'}),tube(4,null,{coverage:'missing'}),
  tube(5,40),tube(6,20),tube(7,20),tube(8,20),tube(9,0),tube(10,30),
  tube(11,15,{state_badges:['shifted'],offset_mm:10}),tube(12,null,{coverage:'NDD'}),
  tube(13,15,{lifetime_replacements:2}),tube(14,20,{missing_depth:1})
]);
const current = snapshot(2,[
  tube(1,15),tube(2,25),tube(3,10),tube(4,12),tube(5,20,{current_events:['replaced'],replacements:1}),
  tube(6,25,{current_events:['shifted'],offset_mm:10}),tube(7,25,{needs_review:true}),
  tube(8,25,{missing_depth:1}),tube(9,5),tube(10,30,{coverage:'defect'}),
  tube(11,20,{state_badges:['shifted'],offset_mm:10}),tube(12,null,{coverage:'NDD'}),
  tube(13,20,{lifetime_replacements:2}),tube(14,25)
]);
const result = statusChangeComparison([current,old], 'D1', 'D102', 30);
const row = id => result.rows.find(row => row.tube === id);
assert.equal(row(1).delta,5);
assert.equal(row(2).delta,-5);
assert(row(3).newWar);assert.equal(row(3).delta,null);
assert(!row(4).newWar,'Missing-to-WAR is not NDD-to-WAR');
assert.equal(row(4).delta,null);
assert(row(5).replaced);assert.equal(row(5).delta,null);
assert(row(6).shifted);assert.equal(row(6).delta,null);
assert.equal(row(7).delta,null);assert(row(7).review);
assert.equal(row(8).delta,null);assert(row(8).review);
assert.equal(row(9).delta,5,'Measured zero is comparable');
assert.equal(row(10).delta,0);assert(row(10).highDepth);
assert(!row(11).maintenance,'Inherited shifted status is not a current maintenance event');
assert.equal(row(11).delta,5,'An unchanged historical offset does not indicate new shifting');
assert.equal(row(12).delta,null,'NDD must not be converted to zero');
assert(row(12).stableNdd,'NDD to NDD retains its conclusion without inventing a depth');
assert(!row(12).changed);
assert.equal(row(13).delta,5,'Future lifetime replacements must not interrupt historical comparisons');
assert.equal(row(14).delta,null,'An incomplete previous maximum is not comparable');
assert.equal(result.counts.newWar,1);
assert.equal(result.counts.maintenance,2);
assert.equal(result.counts.up,4);
assert.equal(result.counts.review,2);
assert.equal(result.counts.all,14);
assert.equal(result.counts.stateMissing,14);
assert(matchesChangeFilter(row(3),'newWar'));
assert(!matchesChangeFilter(row(4),'newWar'));
assert(matchesChangeFilter(row(5),'maintenance'));
assert(matchesChangeFilter(row(2),'down'));
assert(matchesChangeFilter(row(10),'high'));
const gap = statusChangeComparison([old,{...current,order:3,outage:'D103'}],'D1','D103');
assert.equal(gap.counts.comparable,6,'An explicitly selected non-adjacent report pair supports eligible endpoint comparisons');
assert.equal(gap.rows.find(row=>row.tube===1).delta,5);
const noBaseline = statusChangeComparison([old,current],'D1','D102',50,'');
assert.equal(noBaseline.previous,undefined,'An empty baseline selection must not silently select the previous outage');
assert.equal(noBaseline.counts.comparable,0);
const middle = snapshot(2,[tube(1,12)]);
const selectedBaseline = statusChangeComparison([old,middle,{...current,order:3,outage:'D103'}],'D1','D103',50,'D101');
assert.equal(selectedBaseline.previous.outage,'D101');
assert.equal(selectedBaseline.rows[0].delta,5);
const shiftedMiddle = snapshot(2,[tube(1,12,{current_events:['shifted']})]);
const shiftedPair = statusChangeComparison([old,shiftedMiddle,{...current,order:3,outage:'D103'}],'D1','D103',50,'D101');
assert.equal(shiftedPair.rows[0].delta,null,'An intervening recorded shift invalidates the endpoint comparison');
assert.equal(shiftedPair.rows[0].exclusion,'对比期间移位，不计算差值');
const first = statusChangeComparison([old],'D1','D101');
assert.equal(first.previous,undefined);
assert.equal(first.counts.comparable,0);
assert.equal(first.counts.changed,0);
const empty = statusChangeComparison([],'','');
assert.equal(empty.current,undefined);assert.equal(empty.rows.length,0);
const mixed = statusChangeComparison([old,current,snapshot(1,[tube(1,99)],'D2')],'D2','D201');
assert.equal(mixed.rows[0].old,undefined,'Never compare across odd/even units');
assert.equal(unitParity('D1'),'奇数机组');assert.equal(unitParity('D2'),'偶数机组');
assert.equal(unitParity('LF12'),'偶数机组');
assert.equal(unitParity(''),'机组编号待核对');
const changedPosition = statusChangeComparison([old,snapshot(2,[tube(1,15,{position:'M1'})])],'D1','D102');
assert.equal(changedPosition.rows[0].delta,null);
assert.equal(changedPosition.rows[0].exclusion,'对比期间堆芯位置变化');
for(const pendingInCurrent of [true,false]){
  const mixedConclusion=statusChangeComparison([
    snapshot(1,[tube(1,20,{incomplete_records:pendingInCurrent?0:1})]),
    snapshot(2,[tube(1,20.0001,{incomplete_records:pendingInCurrent?1:0})])
  ],'D1','D102');
  assert.equal(mixedConclusion.rows[0].delta,null,'Partial conclusions cannot support a maximum-depth comparison');
  assert.equal(mixedConclusion.rows[0].exclusion,'存在待核对检测结论');
  assert.equal(mixedConclusion.rows[0].review,pendingInCurrent);
}
console.log('Status/change model passed: parity, baselines, coverage, exclusions, current maintenance and overlapping filters.');
