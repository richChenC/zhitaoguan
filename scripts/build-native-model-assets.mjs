/** Offline conversion only. The desktop runtime consumes these meshes in Qt. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as THREE from "../src/desktop-ui/visualizations/reference-thimble/vendor/three.module.js";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const source = path.join(root, "src/desktop-ui/visualizations/reference-thimble/data/vessel_layout.json");
const layout = JSON.parse(fs.readFileSync(source, "utf8"));
const parts = [];
function add(id, geometry, meta = {}) {
  const mesh = geometry;
  const positions = Array.from(mesh.attributes.position.array, v => +v.toFixed(4));
  const normals = Array.from(mesh.attributes.normal.array, v => +v.toFixed(5));
  const indices = mesh.index ? Array.from(mesh.index.array) : positions.filter((_, i) => i % 3 === 0).map((_, i) => i);
  parts.push({ id, positions, normals, indices, ...meta });
}
const holes = new Map();
function hole(x, z, r) {
  const key = `${x.toFixed(3)},${z.toFixed(3)}`;
  if (!holes.has(key) || holes.get(key).r < r) holes.set(key, { x, z, r });
}
const structure = layout.structure;
for (const channel of layout.channels) hole(channel.x, channel.z, structure.platePenetration?.tubeHoleRadius || 6.35);
for (const column of structure.columns) {
  if (column.type.startsWith("core")) hole(column.x, column.z, column.od / 2 + (structure.platePenetration?.columnHoleClearance || 6));
}
for (const key of ["ucsPlate", "secondaryGrid"]) {
  const plate = structure[key];
  const shape = new THREE.Shape();
  shape.absarc(0, 0, plate.outerR, 0, Math.PI * 2, false);
  let count = 0;
  for (const h of holes.values()) {
    if (Math.hypot(h.x, h.z) + h.r >= plate.outerR - 4) continue;
    const opening = new THREE.Path();
    opening.absarc(h.x, h.z, h.r, 0, Math.PI * 2, true);
    shape.holes.push(opening);
    count++;
  }
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: plate.thickness, bevelEnabled: false, curveSegments: 20 });
  geometry.rotateX(Math.PI / 2);
  geometry.translate(0, plate.y + plate.thickness, 0);
  add(key, geometry, { holeCount: count });
}
for (const [i, column] of structure.columns.entries()) {
  const height = column.yTop - column.yBottom;
  let geometry;
  if (column.bore > 0) {
    const shape = new THREE.Shape();
    shape.absarc(0, 0, column.od / 2, 0, Math.PI * 2, false);
    const opening = new THREE.Path();
    opening.absarc(0, 0, column.bore / 2, 0, Math.PI * 2, true);
    shape.holes.push(opening);
    geometry = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false, curveSegments: 5 });
    geometry.rotateX(Math.PI / 2);
    geometry.translate(column.x, column.yTop, column.z);
  } else {
    geometry = new THREE.CylinderGeometry(column.od / 2, column.od / 2, height, 18);
    geometry.translate(column.x, (column.yTop + column.yBottom) / 2, column.z);
  }
  add(`column-${i}`, geometry, { type: column.type, bore: column.bore || 0 });
}
const vessel = layout.vessel;
const profile = [];
for (let i = 0; i <= 36; i++) {
  const angle = i / 36 * Math.PI / 2;
  profile.push(new THREE.Vector2(vessel.outerRadius * Math.sin(angle), -vessel.outerRadius * Math.cos(angle)));
}
profile.push(new THREE.Vector2(vessel.outerRadius, vessel.cylinderTopY));
profile.push(new THREE.Vector2(vessel.innerRadius, vessel.cylinderTopY));
for (let i = 36; i >= 0; i--) {
  const angle = i / 36 * Math.PI / 2;
  profile.push(new THREE.Vector2(vessel.innerRadius * Math.sin(angle), -vessel.innerRadius * Math.cos(angle)));
}
add("vessel", new THREE.LatheGeometry(profile, 96), { schematic: true });
const target = path.join(root, "qt_shell/model_assets");
fs.mkdirSync(target, { recursive: true });
fs.writeFileSync(path.join(target, "structure.json"), JSON.stringify({
  source: "vessel_layout.json; same Three.js Shape/Extrude/Lathe geometry as the reference viewer",
  units: "mm", parts,
}));
console.log(JSON.stringify({ parts: parts.length, holes: parts.filter(p => p.holeCount).map(p => [p.id, p.holeCount]) }));
