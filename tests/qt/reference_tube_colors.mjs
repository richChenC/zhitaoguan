// Read-only execution of the reference's actual color functions, without a browser.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

const reference = path.resolve(process.argv[2]);
const viewer = path.join(reference, 'src/desktop-ui/visualizations/reference-thimble');
const THREE = await import(pathToFileURL(path.join(viewer, 'vendor/three.core.js')));
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const colorStart = source.indexOf('const TUBE_BASE_COLOR =');
const colorEnd = source.indexOf('let selectedTubeHighlight', colorStart);
const typeStart = source.indexOf('function typeColorHex(type)');
const typeEnd = source.indexOf('/**', typeStart);
if ([colorStart, colorEnd, typeStart, typeEnd].some(index => index < 0)) {
  throw new Error('Reference color function boundaries changed');
}
const functions = source.slice(colorStart, colorEnd) + source.slice(typeStart, typeEnd);
const specs = JSON.parse(fs.readFileSync(path.join(viewer, 'data/tube_specs.json'), 'utf8'));
let input = '';
for await (const chunk of process.stdin) input += chunk;
const cases = JSON.parse(input);
const outputs = [];
for (const item of cases) {
  const colors = [];
  const context = {
    THREE, Number, String, Math, Map, Set,
    state: {mode: 'assembly', lenColor: item.mode === 'length', typeColor: item.mode === 'type',
      depthColor: item.mode === 'depth', typeFilter: item.type_filter || null},
    asmInst: {TUBES: {instanceColor: {}, material: {color: new THREE.Color()},
      setColorAt(index, color) { colors[index] = '#' + color.getHexString(); }}},
    vessel: {channels: item.tubes.map(tube => ({L: tube.length, type: tube.type,
      serialOdd: tube.tube, serialEven: tube.tube}))},
    TYPE_COLOR: Object.fromEntries(specs.models.map(model => [model.type, model.color])),
    HOLLOW_COLOR: '#8d8d8d', asmSelectedSet: new Set(), asmSelected: -1,
    syncSelectedTubeHighlight() {},
    window: {__thimbleDefects: {rows: item.records, scope: {unit: 2}},
      appSettings: {severity: () => ({midThreshold: item.levels[0], highThreshold: item.levels[1],
        low: item.colors[0], mid: item.colors[1], high: item.colors[2]})}},
    $: () => null,
  };
  vm.runInNewContext(functions + '\napplyTubeColor();', context);
  outputs.push(colors);
}
process.stdout.write(JSON.stringify({revision: THREE.REVISION, outputs}));
