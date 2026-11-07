import assert from 'node:assert/strict';
import fs from 'node:fs';
const source=fs.readFileSync(new URL('../src/desktop-ui/modules/analytics/visualization-model.js',import.meta.url),'utf8');
const {compareUnits,positionRows,positionSummary,channelFrequency,depthDistribution,replacementSummary,
  positionContributions,depthComparisons,replacementScope,replacementReconciliation,
  historicalDepthSnapshot}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const chartSource=fs.readFileSync(new URL('../src/desktop-ui/modules/analytics/chart-factory.js',import.meta.url),'utf8');
const {lineSegments,renderLineChart}=await import(`data:text/javascript;base64,${Buffer.from(chartSource).toString('base64')}`);
assert.deepEqual(['LF1','L2','P1','D2','L1','C1','D1'].sort(compareUnits),['D1','D2','L1','L2','P1','LF1','C1']);
const pos=(total,missing=0)=>({total,records:1,valid:missing?0:1,missing,tubes:1});
const rows=[
  {unit:'F1',order:1,outage:'F101',total:10,missing_depth:0,position_stats:{P1:pos(10)}},
  {unit:'F2',order:1,outage:'F201',total:null,missing_depth:1,position_stats:{P1:pos(null,1)}},
  {unit:'F1',order:2,outage:'F102',total:20,missing_depth:0,position_stats:{P2:pos(20)}}
];
const all=positionRows(rows);
assert.equal(all[0].total,10);assert.equal(all[0].contributors,2);assert.equal(all[0].incomplete,1);
assert.equal(all[0].position_stats.P1.missing,1);
assert.equal(positionRows(rows,'F2')[0].total,null);
assert.equal(positionSummary(rows).stats.P2.total,20);
assert.equal(positionSummary(rows).stats.P1.total,null);
assert.equal(positionSummary(rows,'F1','F101').stats.P1.total,10);
const partialRows=positionRows([{...rows[0],partial:true}]);
assert.equal(partialRows[0].total,10);
assert.equal(partialRows[0].incomplete,1,'Numeric totals with missing tubes must stay partial');
const snapshot={tubes:[
  {position:'B5',findings:[{indication:'WAR',depth:40},{indication:'WAR',depth:65},{indication:'NDD',depth:99}]},
  {position:'B7',findings:[{indication:'WAR',depth:20}]},
  {position:'B8',findings:[{indication:'WAR',depth:null},{indication:'WAR',depth:120}]}
]};
assert.deepEqual(channelFrequency([snapshot],40),[
  {position:'B5',count:1,inspections:1,max:65},{position:'B7',count:0,inspections:1,max:20}
]);
assert.equal(channelFrequency([snapshot,snapshot],65)[0].count,0);
const distribution=depthDistribution([{tubes:[
  {coverage:'NDD',max_depth:null}, {coverage:'defect',max_depth:0},
  {coverage:'defect',max_depth:19.9}, {coverage:'defect',max_depth:20},
  {coverage:'defect',max_depth:39.9}, {coverage:'defect',max_depth:40},
  {coverage:'defect',max_depth:null}, {coverage:'defect',max_depth:101},
  {coverage:'incomplete',max_depth:null}, {coverage:'missing',max_depth:null}
]}],20,40);
assert.deepEqual(distribution,{NDD:1,zero:1,low:1,mid:2,high:1,unquantified:2,incomplete:1,missing:1});
assert.equal(Object.values(distribution).reduce((sum,n)=>sum+n,0),10);
assert.equal(depthDistribution([{tubes:[{coverage:'defect',max_depth:20}]}],25,50).low,1);
assert.deepEqual(replacementSummary([
  {tubes:[{tube:1,replacements:0,lifetime_replacements:2},{tube:2,replacements:1,lifetime_replacements:1}]},
  {tubes:[{tube:1,replacements:2,lifetime_replacements:2},{tube:2,replacements:0,lifetime_replacements:1}]}
]),{tubeCount:2,eventCount:3},'Lifetime counts must not be summed again across outages');
assert.deepEqual(replacementSummary([{tubes:[{tube:1,lifetime_replacements:0}]}]),{tubeCount:0,eventCount:0});
assert.deepEqual(replacementSummary([{tubes:[{tube:1,replacements:4}]}]),{tubeCount:0,eventCount:0},
  'Cumulative-through-outage counts must not silently substitute for lifetime totals');
const allTubes=Array.from({length:50},(_,index)=>index+1);
const auditUnit={code:'D1',latest_order:4,history:[
  {outage:'D101',records:50,state_current_tubes:allTubes,
   state_sources:[{tube:1,outage:'D101',label:'堵管',source:'a'}],
   replacement_records:[{tube:1,outage:'D101',id:11}]},
  {outage:'D102',records:50,state_current_tubes:allTubes.slice(1),
   state_sources:[{tube:2,outage:'D102',label:'移位',source:'b'}],
   replacement_records:[{tube:2,outage:'D102',id:12}]},
  {outage:'D104',records:0,state_current_tubes:[1],
   state_sources:[{tube:1,outage:'D104',label:'正常',source:'c'}],
   replacement_records:[{tube:1,outage:'D104',id:14}]}
]};
const audit=replacementScope(auditUnit);
assert.equal(audit.chosen.length,4);
assert.equal(audit.eventCount,3);
assert.equal(audit.complete,false);
assert.equal(audit.completeOutages,1);
assert.equal(audit.missingRecords,100);
assert.deepEqual(audit.tubes[0].missingOutages,['D102','D103']);
assert.equal(audit.tubes[0].count,2);
assert.equal(audit.tubes[0].maintenance[0].label,'堵管');
assert.equal(audit.tubes[1].maintenance[0].label,'移位');
const firstOnly=replacementScope(auditUnit,new Set(['D101']));
assert.equal(firstOnly.complete,true);
assert.equal(firstOnly.eventCount,1,'Future events must not enter a selected outage');
assert.equal(firstOnly.tubes[1].count,0);
assert.equal(firstOnly.tubes[1].complete,true,'A complete maintenance scope can support zero');
assert.equal(replacementScope(auditUnit,new Set(['D103'])).hasData,false);
assert.equal(replacementScope(auditUnit,new Set()).complete,false);
const reconciled=replacementReconciliation([{tubes:[
  {tube:1,lifetime_replacements:2,lifetime_replacement_outages:['D101','D104']},
  {tube:2,lifetime_replacements:1,lifetime_replacement_outages:['D102']}
]}],auditUnit);
assert.equal(reconciled.lifetime.eventCount,3);
assert.equal(reconciled.all.eventCount,3);
assert.equal(reconciled.selected.eventCount,3);
assert.equal(reconciled.otherEventCount,0);
assert.equal(reconciled.unmatchedEventCount,0);
assert.equal(reconciled.reconciled,true);
const subset=replacementReconciliation([{tubes:[
  {tube:1,lifetime_replacements:2,lifetime_replacement_outages:['D101','D104']},
  {tube:2,lifetime_replacements:1,lifetime_replacement_outages:['D102']}
]}],auditUnit,new Set(['D101']));
assert.equal(subset.selected.eventCount,1);
assert.equal(subset.otherEventCount,2,'Excluded selectable outages stay separate from selected detail');
const unmatchable=replacementReconciliation([{tubes:[
  {tube:1,lifetime_replacements:2,lifetime_replacement_outages:['D101','D199']}
]}],auditUnit);
assert.equal(unmatchable.unmatchedEventCount,1);
assert.deepEqual(unmatchable.unscopedLifetimeOutages,['D199']);
assert.equal(unmatchable.reconciled,false,'Lifetime events absent from outage detail must be flagged');
const peak=historicalDepthSnapshot([
  {outage:'D103',order:3,tubes:[{tube:1,coverage:'defect',max_depth:20,records:1}]},
  {outage:'D101',order:1,tubes:[{tube:1,coverage:'defect',max_depth:60,records:1}]},
  {outage:'D102',order:2,tubes:[{tube:1,coverage:'defect',max_depth:40,records:1}]}
]);
assert.equal(peak.tubes[0].max_depth,60);
assert.equal(peak.tubes[0].depth_outage,'D101');
assert.equal(peak.tubes[0].records,3);
assert.equal(historicalDepthSnapshot([]),null);
const contributions=positionContributions([
  {position_stats:{P1:pos(10),P6:pos(5),未解析:pos(null,1)}},
  {position_stats:{P1:pos(20),未解析:pos(2)}}
]);
assert.equal(contributions.reduce((sum,row)=>sum+(row.total||0),0),37);
assert.equal(contributions.find(row=>row.key==='未解析').missing,1);
assert.equal(positionContributions([{position_stats:{P6:pos(null,1)}}])[0].total,null);
const points=[{x:1,y:10},{x:2,y:null},{x:3,y:0},{x:5,y:8},{x:6,y:''},{x:7,y:3}];
assert.deepEqual(lineSegments(points).map(segment=>segment.map(point=>point.x)),[[1],[3],[5],[7]]);
assert.deepEqual(lineSegments([{x:1,y:30},{x:2,y:0,breakBefore:true},{x:3,y:8}])
  .map(segment=>segment.map(point=>point.x)),[[1],[2,3]]);
const container={classList:{add(){},remove(){}},innerHTML:'',clientWidth:800};
const svg=renderLineChart(container,{width:800,height:360,tooltip:false,series:[{name:'D1',color:'#333',data:points}]});
assert(!svg.includes('data-x="2"') && !svg.includes('data-x="6"'));
assert(svg.includes('data-x="3"'),'A documented zero must remain visible');
const partialSvg=renderLineChart(container,{width:800,height:360,tooltip:false,
  series:[{name:'D1',color:'#333',data:[{x:1,y:10,partial:true}]}]});
assert(partialSvg.includes(' · 部分'));
const markerOnlySvg=renderLineChart(container,{width:800,height:360,tooltip:false,
  series:[{name:'tube-trends',color:'#f00',lineWidth:1.6,data:[{x:1,y:61},{x:2,y:57}]},
    {name:'斜率突变',color:'#f00',symbol:'diamond',pointR:5,lineWidth:0,
      data:[{x:3,y:61},{x:3,y:28}]}]});
const anomalyGroup=markerOnlySvg.match(/<g class="series" data-name="斜率突变"[\s\S]*?<\/g>/)?.[0];
assert(anomalyGroup,'Anomaly marker series should render');
assert(!anomalyGroup.includes('<path d='),'A zero-width anomaly series must not connect separate tube markers');
assert.equal((anomalyGroup.match(/class="cft-point"/g)||[]).length,2,'Both anomaly markers must remain visible');
const tube=(id,depth,extra={})=>({tube:id,position:'B5',coverage:'defect',max_depth:depth,...extra});
const past={unit:'F1',order:1,outage:'F101',tubes:[
  tube(1,20),tube(2,30),tube(3,null),tube(4,null,{coverage:'NDD'}),
  tube(5,60),tube(6,10),tube(7,0),tube(8,20,{offset_mm:null})
]};
const current={unit:'F1',order:2,outage:'F102',tubes:[
  tube(1,25),tube(2,40,{lifetime_replacements:1}),tube(3,50),tube(4,45),
  tube(5,35,{offset_mm:20}),tube(6,120),tube(7,5),tube(8,25)
]};
const comparisons=depthComparisons([current,past]);
const compared=id=>comparisons.find(row=>row.outage==='F102'&&row.tube===id);
assert.equal(compared(1).delta,5);
assert.equal(compared(2).delta,null);assert(compared(2).replaced);
assert.equal(compared(3).oldDepth,null);assert.equal(compared(3).delta,null);
assert(compared(4).reason.includes('前次NDD'));assert.equal(compared(4).delta,null);
assert(compared(5).shifted);assert.equal(compared(5).delta,null);
assert(!compared(6),'Invalid depths must not enter a numeric comparison');
assert.equal(compared(7).delta,5,'Measured zero is a valid previous value');
assert.equal(compared(8).delta,5,'Absent and null offsets both mean not recorded');
assert.equal(depthComparisons([past,{...current,order:3}]).find(row=>row.tube===1).delta,null);
assert(depthComparisons([past,{...current,order:3}]).find(row=>row.tube===1).reason.includes('中间缺少检查'));
assert.equal(depthComparisons([past,current])[0].order,2);
assert.equal(depthComparisons([{...past,tubes:[tube(1,45)]}],55).length,0);
assert.equal(depthComparisons([past,{...current,tubes:[tube(1,25,{current_events:['shifted']})]}])
  .find(row=>row.order===2).delta,null);
console.log('Visualization model passed: ordering, nulls, thresholds, WAR counting, lifetime counts and depth comparison exclusions.');
