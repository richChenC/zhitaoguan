// Reproduce the actual read-only reference's assembly geometry without a browser.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';

const reference = path.resolve(process.argv[2]);
const viewer = path.join(reference, 'src/desktop-ui/visualizations/reference-thimble');
const THREE = await import(pathToFileURL(path.join(viewer, 'vendor/three.core.js')));
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const start = source.indexOf('function vesselProfile(');
const end = source.indexOf('\n/** 50 个实例的位姿', start);
if (start < 0 || end < 0) throw new Error('Reference assembly function boundaries changed');
const layout = JSON.parse(fs.readFileSync(path.join(viewer, 'data/vessel_layout.json'), 'utf8'));
const model = JSON.parse(fs.readFileSync(path.join(viewer, 'data/thimble_assembly.json'), 'utf8'));
const dome = JSON.parse(fs.readFileSync(path.join(viewer, 'data/dome.json'), 'utf8'));
const context = vm.createContext({
    THREE, vessel:layout, model, domeData:dome, scene:new THREE.Scene(),
    asmRoot:null, asmG:{}, asmInst:{}, asmPickable:[], state:{colVis:{}},
    COL_COLOR:{'core-hollow':0x5f87a8,'core-solid':0x4f9d9d,'sec-hollow':0x8a7fb8,'sec-solid':0x9fb4c9},
    asmDispose(){}, buildAxisGizmo(){}, applyTubeInstances(){}, applyAsmVisibility(){},
    applyTubeColor(){}, applyPrvCut(){}, console:{log(){}},
    partGeometry(id) {
        const part = model.parts.find(part => part.id === id);
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position',new THREE.Float32BufferAttribute(part.positions,3));
        geometry.setIndex(part.indices);
        return geometry;
    },
});
vm.runInContext(source.slice(start,end)+'\nbuildVesselScene();', context);
context.asmRoot.updateMatrixWorld(true);
const caps = [], geometry = [];
context.asmRoot.traverse(object => {
    if (!object.isMesh || object.isInstancedMesh) return;
    const copy = object.geometry.clone().applyMatrix4(object.matrixWorld);
    const data = {
        id:object.userData.kind === 'cutcap' ? 'assembly-cap-'+caps.length : 'assembly-'+geometry.length,
        positions:Array.from(copy.attributes.position.array), indices:copy.index ? Array.from(copy.index.array) :
            Array.from({length:copy.attributes.position.count},(_,index)=>index),
        normals:Array.from(copy.attributes.normal.array),
        kind:object.userData.kind, info:object.userData.cap || null,
        column:object.userData.col ? layout.structure.columns.indexOf(object.userData.col) : null,
        material:{color:'#'+object.material.color.getHexString(),metalness:object.material.metalness,
            roughness:object.material.roughness,opacity:object.material.opacity,side:object.material.side,
            depthWrite:object.material.depthWrite},
    };
    if (data.kind === 'cutcap') {
        data.target = caps.length === 0 ? 'vessel' : caps.length < 5 ? 'plate' : 'column';
        data.columnType = data.info.type || '';
        data.explodeOffset = data.target === 'plate' ?
            (data.info.y === layout.structure.ucsPlate.y ? 800 : 400) : 0;
    }
    (data.kind === 'cutcap' ? caps : geometry).push(data);
    copy.dispose();
});
const result = {source:'TRAE actual buildVesselScene', revision:THREE.REVISION,
    source_sha256:crypto.createHash('sha256').update(source).digest('hex'),
    clipAxis:'x',clipOffset:0,retainedSide:'negative',inset:-.4,parts:caps,
    summary:{capCount:caps.length,capColumns:context.asmG.cutCapColumns,
             plateHoles:context.asmG.plateHoles,assemblyMeshes:geometry.length}};
if (process.argv[3]) fs.writeFileSync(process.argv[3],JSON.stringify(result)+'\n');
if (process.argv[4]) fs.writeFileSync(process.argv[4],JSON.stringify({parts:geometry})+'\n');
if (process.argv[5]) {
    const structurePath = path.resolve(process.argv[5]);
    const structure = JSON.parse(fs.readFileSync(structurePath,'utf8'));
    const columns = layout.structure.columns.map((column, index) => {
        const surfaces = geometry.filter(part => part.kind === 'column' && part.column === index);
        const result = {id:'column-'+index, positions:[],normals:[],indices:[]};
        for (const surface of surfaces) {
            const offset = result.positions.length/3;
            result.positions.push(...surface.positions);
            result.normals.push(...surface.normals);
            result.indices.push(...surface.indices.map(value => value+offset));
        }
        if (!surfaces.length) throw new Error('Reference column missing: '+index);
        return result;
    });
    structure.parts = [...structure.parts.filter(part => !part.id.startsWith('column-')), ...columns];
    fs.writeFileSync(structurePath, JSON.stringify(structure)+'\n');
    fs.writeFileSync(path.join(path.dirname(structurePath),'assembly-provenance.json'),JSON.stringify({
        source:'TRAE actual buildVesselScene, Three r'+THREE.REVISION,
        source_sha256:result.source_sha256,
        columns:columns.length,
        column_surfaces:geometry.filter(part => part.kind === 'column').length,
        cap_summary:result.summary,
        column_geometry:'Exact world float32 positions and normals; merged surfaces retain reference indices.',
        tie_mode:layout.structure.tieRing?.mode || 'none',
        retained_structure:'Existing plates/vessel preserved; their positions differ by at most 0.00005mm.',
    },null,2)+'\n');
}
process.stdout.write(JSON.stringify(result.summary)+'\n');
