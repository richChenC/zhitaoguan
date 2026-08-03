import * as THREE from '/vendor/three.module.min.js';
import { OrbitControls } from '/vendor/OrbitControls.js';

const ODD = 'L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
const EVEN = 'B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 M5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ');
const P_LEVELS = {P1: 7.8, P2: 6.5, P3: 5.2, P4: 3.9, P5: 2.6, P6: 1.3};
const P_COLORS = {P1: 0x35b9e8, P2: 0x30c78f, P3: 0xf5c64a, P4: 0xf18262, P5: 0xd477c2, P6: 0x849cff};
const COLUMNS = 'RPNMLKJHGFEDCBA'.split('');

const host = document.querySelector('#threeCanvas');
const scopeText = document.querySelector('#threeScope');
const parityText = document.querySelector('#parityControl');
let renderer, scene, camera, controls, model, raycaster, pointer;
let tubeMeshes = [], defectMeshes = [], activeScope = null, activeRows = [], defectsOnly = false, externalPathGroup = null;
let threeCameraMode='overview', autoScan=false, scanTimer=null, selectedTubeId=0;

function ensureEngineeringViews() {
  host.classList.add('single-model-view');
}

function renderAuxiliaryViews(unit, rows) {
  return;
  const map = unit % 2 ? ODD : EVEN;
  const defects = new Map(rows.filter(defect).map(row => [Number(row.thimble_id), row]));
  const markers = map.map((position, index) => {
    const {x, z} = coordinate(position), row = defects.get(index + 1);
    return `<button class="plan-tube ${row ? 'has-defect' : ''}" style="--x:${(x + 9) / 18 * 100}%;--y:${(z + 9) / 18 * 100}%" data-tube="${index + 1}" title="${index + 1}号管 · ${position}">${index + 1}</button>`;
  }).join('');
  const orientation = '<span class="orientation north">180° / 北</span><span class="orientation south">0° / 南</span><span class="orientation east">90° / 东</span><span class="orientation west">270° / 西</span>';
  ['threeTopView','threePlanView'].forEach((id, index) => { const view = document.querySelector(`#${id}`); view.innerHTML = `${orientation}<div class="plan-disc ${index ? 'wireframe' : ''}">${markers}</div><span class="view-caption">${index ? '管板定位图' : '完美俯视图'}</span>`; });
  const layer = document.querySelector('#threeLayerView');
  layer.innerHTML = `<div class="layer-stack"><div class="layer-plate"></div>${Object.entries(P_COLORS).reverse().map(([zone,color]) => `<div class="layer-ring" style="--layer-color:#${color.toString(16).padStart(6,'0')}"><b>${zone}</b><span>${rows.filter(row => zoneOf(row.location).zone === zone && defect(row)).length}处</span></div>`).join('')}<div class="layer-base"></div></div><span class="view-caption">分层解析图</span>`;
  document.querySelectorAll('.plan-tube').forEach(button => button.onclick = () => showTube(Number(button.dataset.tube), map[Number(button.dataset.tube) - 1]));
}

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
  const indication=String(row.indication||'').trim().toUpperCase();
  return Boolean(indication)&&indication!=='NDD'&&(Number(row.datapoint||0)>0||Number(row.percent||0)>0);
}

function defectColor(percent) {
  const value = Number(percent || 0);
  return value >= 40 ? 0xe45b4e : value >= 20 ? 0xd9a441 : 0xd7ef4a;
}

function label(text, color = '#d7ef4a', background = '#111716') {
  const canvas = document.createElement('canvas');
  canvas.width = 128; canvas.height = 64;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = background; ctx.fillRect(3,3,122,58);
  ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.strokeRect(3,3,122,58);
  ctx.fillStyle = '#eef2ed'; ctx.font = 'bold 28px Microsoft YaHei'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(text, 64, 33);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false}));
  sprite.scale.set(0.72, 0.36, 1); sprite.renderOrder = 30;
  return sprite;
}

function init() {
  ensureEngineeringViews();
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x080b0c);
  scene.fog = null;
  camera = new THREE.PerspectiveCamera(38, 1, 0.1, 140);
  camera.position.set(43, 20, 48);
  renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2;
  host.replaceChildren(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xdce9e2, 0x202623, 2.8));
  const light = new THREE.DirectionalLight(0xffffff, 2.6); light.position.set(14, 24, 16); scene.add(light);
  const fill=new THREE.DirectionalLight(0xc9d8d1,1.8);fill.position.set(-12,10,12);scene.add(fill);
  const rim=new THREE.DirectionalLight(0xd7ef4a,.55);rim.position.set(-16,8,-14);scene.add(rim);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(9, 1, 0); controls.enableDamping = true; controls.dampingFactor = 0.07;
  controls.enablePan = true; controls.minDistance = 12; controls.maxDistance = 72;
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE; controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN; controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  raycaster = new THREE.Raycaster(); pointer = new THREE.Vector2();
  renderer.domElement.addEventListener('click', pick);
  renderer.domElement.addEventListener('dblclick', resetTopView);
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
  model = new THREE.Group(); scene.add(model); tubeMeshes = []; defectMeshes = []; externalPathGroup = null;
}

function addThreeControls() {
  const legend = document.querySelector('.p-legend');
  if (legend && !legend.querySelector('.p6')) legend.insertAdjacentHTML('beforeend', '<span><i class="p6"></i>P6</span>');
}

function setThreeCamera(mode){if(!camera)return;threeCameraMode=mode;const views={overview:{p:[22,11,25],t:[0,2,0]},section:{p:[20,4,22],t:[0,-.4,0]},rack:{p:[31,-.5,13],t:[27,-2,0]},tube:{p:[38,12,40],t:[9,1,0]}};const view=views[mode]||views.overview;if(externalPathGroup)externalPathGroup.visible=mode==='rack'||mode==='tube';model?.traverse(object=>{if(object.userData?.role==='coreTube')object.visible=mode!=='tube'||!selectedTubeId||Number(object.userData.id)===selectedTubeId;if(object.userData?.role==='coreAssembly')object.visible=mode!=='tube'});camera.up.set(0,1,0);camera.position.set(...view.p);controls.target.set(...view.t);controls.update();document.querySelectorAll('[data-three-camera]').forEach(b=>b.classList.toggle('active',b.dataset.threeCamera===mode))}

const engineeringMetal = () => new THREE.MeshStandardMaterial({color:0x9ba8a2,metalness:.82,roughness:.28});
const engineeringDark = () => new THREE.MeshStandardMaterial({color:0x39433f,metalness:.74,roughness:.34});
const guideMaterial = () => new THREE.MeshPhysicalMaterial({color:0x82918b,metalness:.55,roughness:.22,transparent:true,opacity:.34,side:THREE.DoubleSide,depthWrite:false});

function addEngineeringCore() {
  const fuelMaterial=new THREE.MeshStandardMaterial({color:0x53615b,metalness:.18,roughness:.65,transparent:true,opacity:.1,depthWrite:false});
  const widths=[3,7,9,11,13,13,15,15,15,13,13,11,9,7,3];
  widths.forEach((width,row)=>{const start=Math.floor((15-width)/2);for(let i=0;i<width;i++){const assembly=new THREE.Mesh(new THREE.BoxGeometry(1.06,8.2,1.06),fuelMaterial);assembly.position.set((start+i-7)*1.18,5.2,(row-7)*1.18);assembly.userData.role='coreAssembly';model.add(assembly)}});
}

function addEngineeringStructures() {
  const dark=engineeringDark(),metal=engineeringMetal();
  const lowerGrid=new THREE.Mesh(new THREE.CylinderGeometry(9.05,9.05,.22,72),dark);lowerGrid.position.y=.9;model.add(lowerGrid);
  const supportPlate=new THREE.Mesh(new THREE.CylinderGeometry(8.65,8.65,.5,72),metal);supportPlate.position.y=-.05;model.add(supportPlate);
  for(let i=0;i<12;i++){const a=i/12*Math.PI*2,column=new THREE.Mesh(new THREE.CylinderGeometry(.24,.24,2.5,16),dark);column.position.set(Math.cos(a)*6.7,-1.55,Math.sin(a)*6.7);model.add(column)}
  const gridPlate=new THREE.Mesh(new THREE.CylinderGeometry(8.05,8.05,.24,72),metal);gridPlate.position.y=-2.78;model.add(gridPlate);
  const shellMaterial=new THREE.MeshPhysicalMaterial({color:0x9aa8a2,metalness:.35,roughness:.3,transparent:true,opacity:.055,side:THREE.DoubleSide,depthWrite:false});
  const wall=new THREE.Mesh(new THREE.CylinderGeometry(10,10,8.2,72,1,true,Math.PI*.18,Math.PI*1.42),shellMaterial);wall.position.y=-.25;model.add(wall);
  const head=new THREE.Mesh(new THREE.SphereGeometry(10,72,28,Math.PI*.18,Math.PI*1.42,Math.PI/2,Math.PI/2),shellMaterial);head.scale.y=.48;head.position.y=-4.4;model.add(head);
}

function addPointMarkers() {
  const descriptions={P1:'下栅格板',P2:'支撑板上表面',P3:'支撑板下表面',P4:'支撑柱与格架板',P5:'支撑柱与RPV管座',P6:'RPV管座与导向管'};
  Object.entries(P_LEVELS).forEach(([zone,y])=>{const color=P_COLORS[zone],line=new THREE.Mesh(new THREE.BoxGeometry(2,.025,.025),new THREE.MeshBasicMaterial({color}));line.position.set(9.6,y,0);model.add(line);const tag=label(zone,`#${color.toString(16).padStart(6,'0')}`,'#122a35');tag.position.set(10.9,y,0);tag.userData.description=descriptions[zone];model.add(tag)});
}

function pathTube(points,radius,material){return new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),64,radius,14,false),material)}
function horizontalCylinder(radius,length,material){const mesh=new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,length,22),material);mesh.rotation.z=Math.PI/2;return mesh}
function addExternalValve(group,x,automatic=false){const body=horizontalCylinder(.42,1,engineeringDark());body.position.set(x,-5.6,0);group.add(body);[-.5,.5].forEach(offset=>{const flange=horizontalCylinder(.58,.16,engineeringMetal());flange.position.set(x+offset,-5.6,0);group.add(flange)});const stem=new THREE.Mesh(new THREE.CylinderGeometry(.12,.12,.65,14),engineeringMetal());stem.position.set(x,-5.05,0);group.add(stem);const actuator=new THREE.Mesh(new THREE.BoxGeometry(automatic?1.05:.7,automatic?.75:.18,.7),engineeringDark());actuator.position.set(x,automatic?-4.5:-4.68,0);group.add(actuator)}

function addDistributionRack(group,selectedId) {
  const frame=engineeringDark(),rail=engineeringMetal(),map=Number(activeScope?.unit||activeRows[0]?.unit_id||1)%2?ODD:EVEN;
  [-1,1].forEach(side=>{const post=new THREE.Mesh(new THREE.BoxGeometry(.18,7.4,.18),frame);post.position.set(27,-2.15,side*4.6);group.add(post)});
  [1.55,-.55,-2.65,-5.75].forEach(y=>{const beam=new THREE.Mesh(new THREE.BoxGeometry(.18,.18,9.4),rail);beam.position.set(27,y,0);group.add(beam)});
  const portMaterial=new THREE.MeshStandardMaterial({color:0x778b93,metalness:.7,roughness:.3});
  const activeMaterial=new THREE.MeshStandardMaterial({color:0xd7ef4a,emissive:0x718500,emissiveIntensity:1.1,metalness:.45,roughness:.25});
  let selectedPort=null;
  for(let id=1;id<=50;id++){const row=Math.floor((id-1)/17),col=(id-1)%17,count=row===2?16:17,z=-4+col*(8/(count-1)),y=.72-row*2.1;
    const port=new THREE.Mesh(new THREE.CylinderGeometry(.17,.17,.22,16),id===selectedId?activeMaterial:portMaterial);port.rotation.z=Math.PI/2;port.position.set(26.88,y,z);port.userData={type:'tube',id,position:map[id-1]};group.add(port);tubeMeshes.push(port);
    const number=label(String(id),id===selectedId?'#d7ef4a':'#d5f1fa','#102c38');number.position.set(26.72,y+.34,z);number.scale.set(.36,.18,1);number.userData=port.userData;group.add(number);tubeMeshes.push(number);if(id===selectedId)selectedPort=new THREE.Vector3(26.75,y,z);
  }
  const cabinetTag=label('50路分配选择架','#d7ef4a','#102c38');cabinetTag.position.set(27,2.05,0);cabinetTag.scale.set(2.2,.42,1);group.add(cabinetTag);return selectedPort;
}

function addExternalSystem(id,position) {
  if(externalPathGroup)model.remove(externalPathGroup);externalPathGroup=new THREE.Group();model.add(externalPathGroup);
  const{x,z}=coordinate(position),points=[new THREE.Vector3(x,-4.55,z),new THREE.Vector3(x,-5.1,z),new THREE.Vector3(x+.55,-5.6,z*.65),new THREE.Vector3(11,-5.6,0),new THREE.Vector3(23,-5.6,0)];
  externalPathGroup.add(pathTube(points,.28,guideMaterial()));externalPathGroup.add(pathTube(points,.1,new THREE.MeshStandardMaterial({color:0xd7ef4a,emissive:0x718500,emissiveIntensity:.8,metalness:.55,roughness:.25})));
  addExternalValve(externalPathGroup,13.2);const seal=horizontalCylinder(.52,2.2,engineeringDark());seal.position.set(16.2,-5.6,0);externalPathGroup.add(seal);addExternalValve(externalPathGroup,19.2);addExternalValve(externalPathGroup,22.1,true);
  const selectedPort=addDistributionRack(externalPathGroup,id);if(selectedPort){const flexible=pathTube([new THREE.Vector3(23,-5.6,0),new THREE.Vector3(24,-5.25,0),new THREE.Vector3(25.8,selectedPort.y-.45,selectedPort.z*.7),selectedPort],.1,new THREE.MeshStandardMaterial({color:0xd7ef4a,emissive:0x718500,emissiveIntensity:.8}));externalPathGroup.add(flexible)}
}

function addRackOverview(){externalPathGroup=new THREE.Group();model.add(externalPathGroup);addDistributionRack(externalPathGroup,0);externalPathGroup.visible=false}

function addPlate(y, name) {
  const board = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({color: 0x487483, roughness: 0.5, metalness: 0.24});
  const edge = new THREE.LineBasicMaterial({color: 0xb1d9e5, transparent: true, opacity: 0.68});
  const widths = [3, 7, 9, 11, 13, 13, 15, 15, 15, 13, 13, 11, 9, 7, 3];
  widths.forEach((width, row) => {
    const start = Math.floor((15 - width) / 2);
    for (let offset = 0; offset < width; offset += 1) {
      const geometry = new THREE.BoxGeometry(1.12, 0.19, 1.12);
      const cell = new THREE.Mesh(geometry, material);
      cell.position.set((start + offset - 7) * 1.18, y, (row - 7) * 1.18); board.add(cell);
      const outline = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edge);
      outline.position.copy(cell.position); board.add(outline);
    }
  });
  [['180', 0, -10.1], ['0', 0, 10.1], ['90', -10.1, 0], ['270', 10.1, 0]].forEach(([text, x, z]) => {
    const angle = label(`${text}°`, '#d5f1fa', '#102c38'); angle.position.set(x, y + 0.28, z); angle.scale.set(0.54, 0.27, 1); board.add(angle);
  });
  board.name = name; model.add(board);
}

function resetTopView() {
  camera.up.set(0, 1, 0); camera.position.set(21, 17, 24); controls.target.set(0, 4.5, 0); controls.update();
}

function addLayers() {
  Object.entries(P_LEVELS).forEach(([zone, y]) => {
    const color = P_COLORS[zone];
    const plane = new THREE.Mesh(new THREE.CircleGeometry(9, 72), new THREE.MeshBasicMaterial({color, transparent:true, opacity:.035, side:THREE.DoubleSide, depthWrite:false}));
    plane.rotation.x = -Math.PI / 2; plane.position.y = y; model.add(plane);
    const edge = new THREE.Mesh(new THREE.TorusGeometry(9, .018, 8, 72), new THREE.MeshBasicMaterial({color, transparent:true, opacity:.62}));
    edge.rotation.x = Math.PI / 2; edge.position.y = y; model.add(edge);
    const tag = label(zone, `#${color.toString(16).padStart(6, '0')}`, '#102c38'); tag.position.set(9.7, y, 0); tag.scale.set(.62, .31, 1); model.add(tag);
  });
}

function addVessel() {
  const shell = new THREE.Mesh(new THREE.CylinderGeometry(9.45, 9.45, 9.2, 72, 1, true), new THREE.MeshPhysicalMaterial({color: 0x718a94, transparent: true, opacity: 0.16, roughness: 0.22, metalness: 0.45, side: THREE.DoubleSide, depthWrite: false}));
  shell.position.y = 4.5; model.add(shell);
  [0, 9].forEach(y => { const flange = new THREE.Mesh(new THREE.TorusGeometry(9.45, 0.2, 12, 96), new THREE.MeshStandardMaterial({color: 0x9babb1, metalness: 0.72, roughness: 0.28})); flange.rotation.x = Math.PI / 2; flange.position.y = y; model.add(flange); });
  [-1, 1].forEach(side => { const support = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, 8.5, 16), new THREE.MeshStandardMaterial({color: 0x718995, metalness: 0.55, roughness: 0.35})); support.position.set(side * 9.7, 4.3, 0); model.add(support); });
}

function addTubes(unit) {
  const map = unit % 2 ? ODD : EVEN;
  const tubeMaterial = new THREE.MeshStandardMaterial({color:0xc7d1cc,emissive:0x18201c,emissiveIntensity:.1,metalness:.68,roughness:.28});
  map.forEach((position, index) => {
    const {x, z} = coordinate(position);
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 8.7, 18), tubeMaterial.clone());
    tube.position.set(x, 4.5, z); tube.userData = {type:'tube',role:'coreTube',id:index+1,position}; model.add(tube); tubeMeshes.push(tube);
    const number = label(String(index + 1)); number.position.set(x, 9.35, z); number.userData = {type:'tube',role:'coreTube',id:index+1,position}; number.scale.set(.42,.21,1); model.add(number); tubeMeshes.push(number);
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
    const {zone, offset} = zoneOf(row.location); const base = P_LEVELS[zone] ?? P_LEVELS.P3;
    const next = P_LEVELS[`P${Math.min(6, Number(zone.slice(1)) + 1)}`] ?? .45;
    const y = base - Math.min(1, Math.max(0, offset / 400)) * (base - next); const {x, z} = coordinate(row.position); const color = defectColor(row.percent);
    const point = new THREE.Mesh(new THREE.SphereGeometry(.13, 18, 12), new THREE.MeshStandardMaterial({color, emissive: color, emissiveIntensity: .72}));
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
  selectedTubeId=id;
  const records = activeRows.filter(row => Number(row.thimble_id) === id);
  const defects = records.filter(defect);
  document.querySelector('#threeDetail').className = 'three-detail';
  document.querySelector('#threeDetail').innerHTML = `<dl><dt>指套管</dt><dd>${id}号 · ${position}</dd><dt>检测记录</dt><dd>${records.length} 条</dd><dt>缺陷记录</dt><dd>${defects.length} 条</dd>${records.slice(0, 10).map(row => `<dt>${row.location || '无缺陷'}</dt><dd>${row.indication || 'NDD'} · ${row.percent ?? '-'}%</dd>`).join('')}</dl>`;
  model.traverse(mesh=>{if(mesh.userData?.role!=='coreTube'||!mesh.material)return;const active=Number(mesh.userData.id)===id;if(mesh.material.color)mesh.material.color.setHex(active?0xd7ef4a:0xc7d1cc);if(mesh.material.emissive)mesh.material.emissive.setHex(active?0x718500:0x111614)});
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
  const selectedRows = Array.isArray(activeScope.selectedItems) ? activeScope.selectedItems : [];
  const unit = Number(activeScope.unit || 0); const outage = activeScope.outage || '';
  scopeText.textContent = unit && outage ? `${outage} · ${unit}号机 · 工作台筛选数据` : '请先在数据工作台选择机组和大修';
  parityText.textContent = unit ? `${unit % 2 ? '奇数' : '偶数'}机组映射 · 50根指套管` : '工作台筛选驱动';
  clearModel(); addPlate(9, 'top-plate'); addPlate(0, 'bottom-plate'); addLayers(); addTubes(unit || 1);
  if (unit && outage) addDefects(selectedRows.length ? selectedRows : activeRows);
  showStats(unit && outage ? activeRows : [], unit, outage); resetTopView();
}

function readWorkspaceScope() { return {site: document.querySelector('#site')?.value || '', unit: document.querySelector('#unit')?.value || '', outage: document.querySelector('#outage')?.value || ''}; }

window.addEventListener('workspace-filter-changed', event => { activeScope = event.detail || readWorkspaceScope(); if (renderer) load(activeScope); });
window.addEventListener('three-focus-tube', event => { activeScope = {...(activeScope || readWorkspaceScope()), ...(event.detail || {})}; if (renderer) load(activeScope).then(() => { const detail = event.detail || {}; const map = Number(detail.unit) % 2 ? ODD : EVEN; showTube(Number(detail.thimble), map[Number(detail.thimble) - 1]); }); });
document.querySelector('[data-view="threeD"]').addEventListener('click', () => { if (!renderer) init(); load(activeScope || readWorkspaceScope()); });
addThreeControls();
