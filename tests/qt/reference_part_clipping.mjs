// Execute the actual reference's explode and per-part clipping plane functions.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

const viewer = path.join(path.resolve(process.argv[2]), 'src/desktop-ui/visualizations/reference-thimble');
const THREE = await import(pathToFileURL(path.join(viewer, 'vendor/three.core.js')));
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const cutStart = source.indexOf('function applyCut()');
const cutEnd = source.indexOf('\n/*', cutStart);
const explodeStart = source.indexOf('function applyExplode()');
const explodeEnd = source.indexOf('\n/*', explodeStart);
if ([cutStart, cutEnd, explodeStart, explodeEnd].some(value => value < 0)) {
  throw new Error('Reference part clip function boundaries changed');
}
const meshes = new Map(['P01','P02','P03','P04','P05','P06'].map(key => {
  const mesh = new THREE.Mesh();
  mesh.visible = true;
  return [key, mesh];
}));
const context = {THREE, state:{}, partsMeshes:meshes, clearCaps(){},
  clipPlane:{}, PLANE_N:new THREE.Vector3(-1,0,0), sliceLoops:() => [],
  $:() => ({}), buildStations(){}, updateOverlay(){}, fitView(){}};
// applyExplode ends before the next section; use brace-balanced function extraction.
function functionText(start) {
  const brace = source.indexOf('{', start);
  let depth = 1, index = brace+1;
  for (; depth && index < source.length; index++) {
    if (source[index] === '{') depth++;
    if (source[index] === '}') depth--;
  }
  return source.slice(start, index);
}
vm.runInNewContext(functionText(cutStart) + '\n' + functionText(explodeStart), context);
const results = [];
for (const state of JSON.parse(process.argv[3])) {
  context.state = state;
  vm.runInNewContext('applyExplode(); applyCut();', context);
  results.push(Object.fromEntries([...meshes].map(([key, mesh]) => [key,
    {position:mesh.position.toArray(), planes:mesh.material.clippingPlanes.map(plane =>
      ({normal:plane.normal.toArray(), constant:plane.constant}))}])));
}
process.stdout.write(JSON.stringify(results));
