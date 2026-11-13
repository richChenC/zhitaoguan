// Execute the reference's actual legend and group toggle handlers read-only.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const viewer = path.join(path.resolve(process.argv[2]), 'src/desktop-ui/visualizations/reference-thimble');
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const layout = JSON.parse(fs.readFileSync(path.join(viewer, 'data/vessel_layout.json'), 'utf8'));
const start = source.indexOf('function toggleColumnGroup(type)');
const end = source.indexOf('/** 型号图例', start);
const colorsStart = source.indexOf('const COL_COLOR =');
const colorsEnd = source.indexOf('};', colorsStart) + 2;
if (start < 0 || end < 0 || colorsStart < 0 || colorsEnd < 2) {
  throw new Error('Reference column handler boundaries changed');
}
const legend = {children:[], appendChild(element) { this.children.push(element); }};
const columns = Object.fromEntries(layout.structure.columnGroups.map(group =>
  [group.id, layout.structure.columns.filter(column => column.type === group.id).map(() => ({visible:true}))]));
const context = {state:{colVis:{}}, asmG:{colByType:columns}, vessel:layout,
  $:() => legend, document:{createElement:() => ({style:{}})}};
vm.runInNewContext(source.slice(colorsStart, colorsEnd) + '\n' + source.slice(start, end) +
  '\nfillColumnLegend();', context);
const initial = legend.children.map(element => ({html:element.innerHTML, title:element.title}));
const states = [];
for (const index of [0, 1, 2, 3, 0, 1, 2, 3, 0, 0]) {
  legend.children[index].onclick();
  states.push({index, visibility:{...context.state.colVis},
    visibleCounts:Object.fromEntries(Object.entries(columns).map(([kind, meshes]) =>
      [kind, meshes.filter(mesh => mesh.visible).length])),
    opacity:legend.children.map(element => Number(element.style.opacity ?? 1))});
}
process.stdout.write(JSON.stringify({initial, states}));
