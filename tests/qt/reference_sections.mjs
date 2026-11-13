// Execute the reference viewer's actual slicing and ShapeGeometry functions with its Three r180.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

const viewer = path.join(path.resolve(process.argv[2]), 'src/desktop-ui/visualizations/reference-thimble');
const THREE = await import(pathToFileURL(path.join(viewer, 'vendor/three.core.js')));
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const start = source.indexOf('function sliceLoops('), end = source.indexOf('\nconst capMatCache', start);
if (start < 0 || end < 0) throw new Error('Reference slice function boundaries changed');
const context = vm.createContext({THREE});
vm.runInContext('const SEG_EPS=1e-6, KEY_Q=1000;\n' + source.slice(start, end), context);
const parts = JSON.parse(fs.readFileSync(path.join(viewer, 'data/thimble_assembly.json'), 'utf8')).parts;
const results = [];
for (const state of JSON.parse(process.argv[3])) {
    const part = parts.find(part => part.id === state.part);
    const axes = state.axis === 'x' ? [0,1,2] : state.axis === 'y' ? [1,2,0] : [2,0,1];
    const original = new Float32Array(part.positions), positions = new Float32Array(original.length);
    // Keep float64 scaling in matrixWorld, like the reference scene.
    for (let i=0; i<positions.length; i+=3) {
        for (let k=0; k<3; k++) positions[i+k] = original[i+axes[k]];
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions,3));
    geometry.setIndex(part.indices);
    context.geometry = geometry;
    context.matrix = new THREE.Matrix4().makeScale(...axes.map(i => state.scale[i]));
    context.offset = state.offset;
    const cap = vm.runInContext('loopsToGeometry(sliceLoops(geometry,matrix,offset))', context);
    results.push({positions:cap ? Array.from(cap.attributes.position.array) : [],
                  indices:cap ? Array.from(cap.index.array) : []});
    cap?.dispose();
    geometry.dispose();
}
process.stdout.write(JSON.stringify(results));
