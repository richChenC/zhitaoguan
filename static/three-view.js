import * as THREE from '/vendor/three.module.min.js';
import { OrbitControls } from '/vendor/OrbitControls.js';

const ODD = 'L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
const EVEN = 'B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 M5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ');
const P_LEVELS = {P1: 8.0, P2: 6.55, P3: 5.1, P4: 3.65, P5: 2.2, P6: 0.75};
const P_COLORS = {P1: 0x35b9e8, P2: 0x30c78f, P3: 0xf5c64a, P4: 0xf18262, P5: 0xd477c2, P6: 0x849cff};
const COLUMNS = 'RPNMLKJHGFEDCBA'.split('');

const host = document.querySelector('#threeCanvas');
const scopeText = document.querySelector('#threeScope');
const parityText = document.querySelector('#parityControl');
let renderer, scene, camera, controls, model, raycaster, pointer;
let tubeMeshes = [], defectMeshes = [], activeScope = null, activeRows = [];

function coordinate(position) {
  const match = String(position || '').match(/^([A-Z])(\d+)$/);
  if (!match) return {x: 0, z: 0};
  return {x: (COLUMNS.indexOf(match[1]) - 7) * 1.18, z: (+match[2] - 8) * 1.18};
}

function zoneOf(location) {
  const match = String(location || '').match(/(P[1-6])(?:\s*\+\s*([-+]?\d+(?:\.\d+)?))?/i);
  return {zone: (match?.[1] || 'P3').toUpperCase(), offset: Number(match?.[2] || 0)};
}

function defect(row) {
  return String(row.indication || '').trim().toUpperCase() !== 'NDD' && Boolean(String(row.indication || '').trim()) && Number(row.datapoint || 0) > 0;
}

function defectColor(percent) {
  const value = Number(percent || 0);
  return value >= 40 ? 0xe44c4c : value >= 20 ? 0xf19b38 : 0xf3d85c;
}

function label(text, color = '#ffffff', background = '#143c52') {
  const canvas = document.createElement('canvas');
  canvas.width = 128; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = background; ctx.beginPath(); ctx.roundRect(3, 3, 122, 58, 8); ctx.fill();
  ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.stroke();
  ctx.fillStyle = '#ffffff'; ctx.font = 'bold 28px Microsoft YaHei'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 64, 33);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false}));
  sprite.scale.set(0.72, 0.36, 1); sprite.renderOrder = 30;
  return sprite;
}

function init() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b1c25);
  scene.fog = new THREE.Fog(0x0b1c25, 30, 54);
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
  camera.position.set(21, 18, 25);
  renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  host.replaceChildren(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xe8fbff, 0x10242d, 2.1));
  const light = new THREE.DirectionalLight(0xffffff, 2.3); light.position.set(14, 24, 16); scene.add(light);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 4.5, 0); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.enablePan = true; controls.minDistance = 14; controls.maxDistance = 52;
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE; controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN; controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  raycaster = new THREE.Raycaster(); pointer = new THREE.Vector2();
  renderer.domElement.addEventListener('click', pick);
  new ResizeObserver(resize).observe(host); window.addEventListener('resize', resize);
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  resize();
}

function resize() {
  if (!renderer) return;
  const width = host.clientWidth, height = host.clientHeight || 600;
  renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
}

function clearModel() {
  if (model) scene.remove(model);
  model = new THREE.Group(); scene.add(model); tubeMeshes = []; defectMeshes = [];
}

function addPlate(y, name) {
  const board = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({color: 0x4c6d7b, transparent: true, opacity: 0.54, roughness: 0.72, metalness: 0.2});
  const edge = new THREE.LineBasicMaterial({color: 0x9cc3d2, transparent: true, opacity: 0.72});
  const widths = [3, 7, 9, 11, 13, 13, 15, 15, 15, 13, 13, 11, 9, 7, 3];
  widths.forEach((width, row) => {
    const start = Math.floor((15 - width) / 2);
    for (let offset = 0; offset < width; offset += 1) {
      const geometry = new THREE.BoxGeometry(1.14, 0.18, 1.14);
      const cell = new THREE.Mesh(geometry, material); cell.position.set((start + offset - 7) * 1.18, y, (row - 7) * 1.18); board.add(cell);
      const outline = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edge); outline.position.copy(cell.position); board.add(outline);
    }
  });
  board.name = name; model.add(board);
}

function addLayers() {
  Object.entries(P_LEVELS).forEach(([zone, y]) => {
    const color = P_COLORS[zone];
    const ring = new THREE.Mesh(new THREE.TorusGeometry(9.2, 0.035, 8, 72), new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.9}));
    ring.rotation.x = Math.PI / 2; ring.position.y = y; model.add(ring);
    const tag = label(zone, `#${color.toString(16).padStart(6, '0')}`, '#122a35'); tag.position.set(10.2, y, 0); tag.scale.set(0.82, 0.4, 1); model.add(tag);
  });
}

function addTubes(unit) {
  const map = unit % 2 ? ODD : EVEN;
  const tubeMaterial = new THREE.MeshStandardMaterial({color: 0x84a5b2, metalness: 0.35, roughness: 0.42});
  map.forEach((position, index) => {
    const {x, z} = coordinate(position);
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.14, 8.85, 14), tubeMaterial.clone());
    tube.position.set(x, 4.5, z); tube.userData = {type: 'tube', id: index + 1, position}; model.add(tube); tubeMeshes.push(tube);
    const cap = new THREE.Mesh(new THREE.TorusGeometry(0.22, 0.03, 8, 20), new THREE.MeshBasicMaterial({color: 0xd3e7ed})); cap.rotation.x = Math.PI / 2; cap.position.set(x, 9.15, z); model.add(cap);
    const number = label(String(index + 1)); number.position.set(x, 9.35, z); number.userData = {type: 'tube', id: index + 1, position}; model.add(number); tubeMeshes.push(number);
  });
}

function addDefects(rows) {
  const grouped = new Map();
  rows.filter(defect).forEach(row => {
    const {zone, offset} = zoneOf(row.location); const key = `${row.thimble_id}|${zone}|${offset}`;
    if (!grouped.has(key)) grouped.set(key, []); grouped.get(key).push(row);
  });
  grouped.forEach(records => {
    const row = records.reduce((best, item) => Number(item.percent || 0) > Number(best.percent || 0) ? item : best, records[0]);
    const {zone, offset} = zoneOf(row.location); const top = P_LEVELS[zone] || P_LEVELS.P3; const next = P_LEVELS[`P${Math.min(6, Number(zone.slice(1)) + 1)}`] || 0.25;
    const y = top - Math.min(1, Math.max(0, offset / 400)) * (top - next); const {x, z} = coordinate(row.position); const color = defectColor(row.percent);
    const point = new THREE.Mesh(new THREE.SphereGeometry(0.15 + Math.min(Number(row.percent || 0) / 500, 0.12), 20, 14), new THREE.MeshStandardMaterial({color, emissive: color, emissiveIntensity: 0.58}));
    point.position.set(x, y, z); point.userData = {type: 'defect', records, position: row.position, id: row.thimble_id}; model.add(point); defectMeshes.push(point);
    if (records.length > 1) { const count = label(`x${records.length}`, '#ffffff', '#b84141'); count.position.set(x + 0.35, y + 0.25, z); count.scale.set(0.48, 0.24, 1); model.add(count); }
  });
}

function showStats(rows, unit, outage) {
  const defects = rows.filter(defect), tubes = new Set(defects.map(row => row.thimble_id)); const max = defects.reduce((value, row) => Math.max(value, Number(row.percent || 0)), 0);
  document.querySelector('#threeStats').innerHTML = `<div><span>当前大修</span><strong>${outage || '-'}</strong></div><div><span>机组</span><strong>${unit || '-'}</strong></div><div><span>缺陷记录</span><strong>${defects.length}</strong></div><div><span>涉及管子</span><strong>${tubes.size}</strong></div><div><span>最大磨损</span><strong>${max}%</strong></div><div><span>结构层</span><strong>P1-P6</strong></div>`;
  document.querySelector('#threeDetail').className = 'three-detail empty'; document.querySelector('#threeDetail').textContent = '点击管子查看该管全部检测信息，点击缺陷点查看缺陷详情';
}

function showTube(id, position) {
  const records = activeRows.filter(row => Number(row.thimble_id) === id);
  const defects = records.filter(defect);
  document.querySelector('#threeDetail').className = 'three-detail';
  document.querySelector('#threeDetail').innerHTML = `<dl><dt>指套管</dt><dd>${id}号 · ${position}</dd><dt>检测记录</dt><dd>${records.length} 条</dd><dt>缺陷记录</dt><dd>${defects.length} 条</dd>${records.slice(0, 10).map(row => `<dt>${row.location || '无缺陷'}</dt><dd>${row.indication || 'NDD'} · ${row.percent ?? '-'}%</dd>`).join('')}</dl>`;
}

function pick(event) {
  const rect = renderer.domElement.getBoundingClientRect(); pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
  raycaster.setFromCamera(pointer, camera); const hit = raycaster.intersectObjects([...defectMeshes, ...tubeMeshes], false)[0]; if (!hit) return;
  const data = hit.object.userData;
  if (data.type === 'defect') { showTube(data.id, data.position); return; }
  if (data.type === 'tube') showTube(data.id, data.position);
}

async function load(scope) {
  activeScope = scope || activeScope || readWorkspaceScope(); const params = new URLSearchParams({page: '1', size: '200'});
  ['site', 'unit', 'outage'].forEach(key => { if (activeScope[key]) params.set(key, activeScope[key]); });
  const result = await fetch(`/api/findings?${params}`).then(response => response.json()); activeRows = result.items || [];
  const unit = Number(activeScope.unit || activeRows[0]?.unit_id || 0); const outage = activeScope.outage || activeRows[0]?.outage || '';
  scopeText.textContent = unit && outage ? `${outage} · ${unit}号机 · 工作台筛选数据` : '请先在数据工作台选择机组和大修';
  parityText.textContent = unit ? `${unit % 2 ? '奇数' : '偶数'}机组映射 · 50根指套管` : '工作台筛选驱动';
  clearModel(); addPlate(9, 'top-plate'); addPlate(0, 'bottom-plate'); addLayers(); if (unit) { addTubes(unit); addDefects(activeRows); } showStats(activeRows, unit, outage);
}

function readWorkspaceScope() { return {site: document.querySelector('#site')?.value || '', unit: document.querySelector('#unit')?.value || '', outage: document.querySelector('#outage')?.value || ''}; }

window.addEventListener('workspace-filter-changed', event => { activeScope = event.detail || readWorkspaceScope(); if (renderer) load(activeScope); });
window.addEventListener('three-focus-tube', event => { activeScope = {...(activeScope || readWorkspaceScope()), ...(event.detail || {})}; if (renderer) load(activeScope).then(() => { const detail = event.detail || {}; const map = Number(detail.unit) % 2 ? ODD : EVEN; showTube(Number(detail.thimble), map[Number(detail.thimble) - 1]); }); });
document.querySelector('[data-view="threeD"]').addEventListener('click', () => { if (!renderer) init(); load(activeScope || readWorkspaceScope()); });
