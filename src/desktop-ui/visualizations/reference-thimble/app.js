/**
 * 指套管三维查看器
 * ---------------------------------------------------------------------------
 * 数据：./data/thimble_assembly.json（参数化零件 + 原始 STEP 精确三角化的螺纹管座）
 *      ./data/p1p6_channels.json（50 通道 P1→P6 真实长度）
 *      ./data/p1p6_stations.json（P1–P6 轴向标记位置及其依据）
 *      ./data/dimensions.json（尺寸清单与溯源）
 * 技术：原生 ESM + three.js（本地 vendor，无构建、无联网）
 */
import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';
import { PlateOverlay } from './plate-overlay.js';
// RoomEnvironment 已弃用：它是彩色摄影棚，会把金属件反射染青绿，改用自绘中性环境（见 makeNeutralEnv）

const $ = (id) => document.getElementById(id);
const TAU = Math.PI * 2;
const state = {
  mode: 'joint',
  channel: null,
  L: 3000,
  ghost: true,
  dims: true,
  stations: true,
  axis: false,
  fat: false,
  cut: false,
  cutPos: 0,
  explode: 0,
  spin: false,
  fatAuto: false,
  selected: null,
  colVis: {},         // 各 type 支承柱显隐（图例点击切换），默认全显
  prv: true,          // PRV 包络
  struct: true,       // 下部支承结构（含三类支承柱，默认开）
  penetrations: true,
  dome: true,         // RPV 下封头（半球形封头，真实 STL 网格）
  axes: true,         // XYZ 坐标轴
  lenColor: false,    // 按管长着色
  typeColor: false,   // 按型号着色（与按管长着色互斥，二者只生效一个，避免颜色打架）
  depthColor: false,  // 按检测数据着色：每根管取当前范围的最大磨损深度套「低/中/高」色阶（与型号/管长着色互斥）
  typeFilter: null,   // 型号图例点击筛选：只显示该型号（null = 不过滤，其余管淡出保留空间感）
  cutPrv: false,      // 剖切（切掉 +X 半边，整场景一起切）
  view: 'iso',        // 当前视角名
  ortho: false,       // 是否处于正交对齐（正视/侧视/俯视）；仅正交时封头才压淡到 0.07
  topPlate: false,
};

let model, channels, stations, dims;
let specs = null;      // tube_specs.json（型号色值 + 16 档 V 排位），启动后异步载入
// 型号 → 着色色值：直接取自 tube_specs.json 的 models[].color；空心柱位不在 models 里，单独给灰
const TYPE_COLOR = {};
let HOLLOW_COLOR = '#8d8d8d';
// V（规格化长度）→ 规格档序（1 基，共 16 档）；空心柱无 V，不入表
const V_RANK = new Map();
let domeData = null;   // RPV 下封头网格（data/dome.json），启动时异步载入
let renderer, scene, camera, perspCam, orthoCam, controls, envTex;
let root, tubeMesh, tubeMat;
const partsMeshes = new Map();
const clipPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
let referenceSelectionSilent = false;
let referenceReady = false;
let renderDirty = true, lastRenderTime = 0;
const invalidateModel = () => { renderDirty = true; };

/* ----------------------------------------------------------------- 截面工具（与 Python 一致） */
function filletPts(p0, p1, p2, radius, steps = 10) {
  const ax = p0[0] - p1[0], ay = p0[1] - p1[1];
  const bx = p2[0] - p1[0], by = p2[1] - p1[1];
  const la = Math.hypot(ax, ay), lb = Math.hypot(bx, by);
  if (la < 1e-9 || lb < 1e-9) return [[p1[0], p1[1], 'c']];
  const ux = ax / la, uy = ay / la, vx = bx / lb, vy = by / lb;
  const cosang = Math.max(-1, Math.min(1, ux * vx + uy * vy));
  const ang = Math.acos(cosang);
  if (ang < 1e-3 || Math.abs(ang - Math.PI) < 1e-3) return [[p1[0], p1[1], 'c']];
  let t = radius / Math.tan(ang / 2);
  t = Math.min(t, la * 0.5, lb * 0.5);
  const r = t * Math.tan(ang / 2);
  const s0 = [p1[0] + ux * t, p1[1] + uy * t];
  const s1 = [p1[0] + vx * t, p1[1] + vy * t];
  let mx = ux + vx, my = uy + vy;
  const lm = Math.hypot(mx, my);
  if (lm < 1e-9) return [[p1[0], p1[1], 'c']];
  mx /= lm; my /= lm;
  const d = r / Math.sin(ang / 2);
  const cx = p1[0] + mx * d, cy = p1[1] + my * d;
  const a0 = Math.atan2(s0[1] - cy, s0[0] - cx);
  const a1 = Math.atan2(s1[1] - cy, s1[0] - cx);
  let da = (a1 - a0 + Math.PI) % TAU - Math.PI;
  const out = [];
  for (let i = 1; i <= steps; i++) {
    const a = a0 + da * i / steps;
    out.push([cx + r * Math.cos(a), cy + r * Math.sin(a), 'a']);
  }
  return out;
}

function tubeProfile(L, g) {
  const ro = g.tube_od / 2, ri = g.tube_id / 2;
  const tipR = g.tip_radius, fil = g.tip_fillet, ch = g.end_chamfer;
  const ang = g.tip_cone_half_angle * Math.PI / 180;
  const yCone = L - tipR - (ro - tipR) / Math.tan(ang);
  const loop = [];
  loop.push([ro, 0, 'c']);
  loop.push([ro, yCone - fil, 'c']);
  for (const p of filletPts([ro, yCone - fil], [ro, yCone], [ro - 0.02, yCone + 0.02], fil, 8)) loop.push(p);
  loop.push([tipR, L - tipR, 'a']);
  const n = 16;
  for (let i = 1; i <= n; i++) {
    const a = Math.PI / 2 * i / n;
    loop.push([0 + tipR * Math.cos(a), (L - tipR) + tipR * Math.sin(a), 'a']);
  }
  loop.push([ri, L - tipR, 'c']);
  loop.push([ri, ch, 'c']);
  loop.push([ri + ch, 0, 'c']);
  return loop;
}

function revolve(loop, segs) {
  let n = loop.length;
  const first = loop[0], last = loop[n - 1];
  if (Math.hypot(first[0] - last[0], first[1] - last[1]) < 1e-9) { loop = loop.slice(0, n - 1); n = n - 1; }
  const segN = [];
  for (let i = 0; i < n; i++) {
    const p = loop[i], q = loop[(i + 1) % n];
    const dr = q[0] - p[0], dy = q[1] - p[1];
    const L = Math.hypot(dr, dy);
    segN.push(L < 1e-12 ? [0, 0] : [dy / L, -dr / L]);
  }
  const nodeN = [];
  for (let i = 0; i < n; i++) {
    const prev = segN[(i - 1 + n) % n], cur = segN[i];
    if (loop[i][2] === 'a') {
      let vx = prev[0] + cur[0], vy = prev[1] + cur[1];
      const l = Math.hypot(vx, vy);
      nodeN.push(l > 1e-9 ? [vx / l, vy / l] : cur);
    } else nodeN.push(cur);
  }
  const pos = [], nrm = [], idx = [], rings = [];
  for (let i = 0; i < n; i++) {
    const r = loop[i][0], y = loop[i][1];
    const [nr, ny] = nodeN[i];
    if (r < 1e-9) {
      const base = pos.length / 3;
      pos.push(0, y, 0); nrm.push(0, ny > 0 ? 1 : -1, 0);
      rings.push(['apex', base]);
    } else {
      const base = pos.length / 3;
      for (let k = 0; k < segs; k++) {
        const th = TAU * k / segs, c = Math.cos(th), s = Math.sin(th);
        pos.push(r * c, y, r * s);
        const nx = nr * c, nz = nr * s;
        const l = Math.hypot(nx, ny, nz) || 1;
        nrm.push(nx / l, ny / l, nz / l);
      }
      rings.push(['ring', base]);
    }
  }
  for (let i = 0; i < n; i++) {
    const a = rings[i], b = rings[(i + 1) % n];
    if (a[0] === 'apex' && b[0] === 'apex') continue;
    if (a[0] === 'apex') {
      for (let k = 0; k < segs; k++) { const k2 = (k + 1) % segs; idx.push(a[1], b[1] + k2, b[1] + k); }
    } else if (b[0] === 'apex') {
      for (let k = 0; k < segs; k++) { const k2 = (k + 1) % segs; idx.push(a[1] + k, a[1] + k2, b[1]); }
    } else {
      for (let k = 0; k < segs; k++) {
        const k2 = (k + 1) % segs;
        idx.push(a[1] + k, a[1] + k2, b[1] + k2);
        idx.push(a[1] + k, b[1] + k2, b[1] + k);
      }
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  geo.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  geo.setIndex(idx);
  return geo;
}

/* ----------------------------------------------------------------- 场景 */
function initScene() {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, stencil: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setSize(Math.max(1, innerWidth), Math.max(1, innerHeight));
  renderer.localClippingEnabled = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  $('stage').appendChild(renderer.domElement);

  scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  envTex = makeNeutralEnv(pmrem);
  scene.environment = envTex;
  pmrem.dispose();

  /* 两套相机：轴测/自由旋转用透视，正视/侧视/俯视用正交。
     正交不是"锦上添花"——指套管长 2.7 m、直径 8.6 mm，长径比 300:1。
     俯视时透视相机必须靠一点倾斜避开 lookAt 退化，可哪怕只偏 2.4°，
     2.7 m 长的管子也会在画面上拉出 40 px 的斜条纹，96 个格位全糊成一片放射纹。
     正交相机视线可以严格沿 -Y、up=(0,0,-1)，管口投影就是直径 3 px 的圆点。 */
  perspCam = new THREE.PerspectiveCamera(38, Math.max(1, innerWidth) / Math.max(1, innerHeight), 0.5, 40000);
  perspCam.position.set(210, 150, 260);

  orthoCam = new THREE.OrthographicCamera(-1000, 1000, 700, -700, 1, 60000);
  orthoCam.position.set(0, 5000, 0);

  camera = perspCam;

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  // 中键按住拖动模型，右键继续平移；滚轮只负责缩放。
  controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
  controls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
  controls.minDistance = 12;
  controls.maxDistance = 12000;
  controls.minZoom = 0.25;          // 正交下 dolly 改的是 zoom，给个上下限免得缩飞
  controls.maxZoom = 8;
  controls.target.set(0, 70, 0);
  const rotateLeft = controls._rotateLeft.bind(controls);
  controls._rotateLeft = angle => rotateLeft(camera.isOrthographicCamera && camera.left > camera.right ? -angle : angle);

  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(1.4, 2.2, 1.6);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xdce9f7, 1.1);
  fill.position.set(-1.8, 0.6, -1.2);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffffff, 0.7);
  rim.position.set(0.2, -1.5, 0.8);
  scene.add(rim);
  scene.add(new THREE.AmbientLight(0xffffff, 0.35));

  root = new THREE.Group();
  scene.add(root);
  window.__scene = scene; window.__root = root; window.__state = state; window.__THREE = THREE;
  window.__camera = camera; window.__controls = controls; window.__renderer = renderer;

  addEventListener('resize', () => {
    // Hidden workspace frames have no viewport; keep their last valid camera.
    if (innerWidth <= 0 || innerHeight <= 0) return;
    perspCam.aspect = innerWidth / innerHeight;
    perspCam.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
    // 正交视锥是按窗口尺寸算出来的，尺寸变了必须整体重构，否则模型会被拉伸
    if (camera === orthoCam) setView(state.view); else updateOverlay();
    ensureFit(null, false);          // 窗口变矮时自动收起次要组，左栏始终不用滚
  });
  renderer.domElement.addEventListener('pointerdown', onPointerDown);
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute('aria-label', '三维模型');
  function resetView(view) {
    state.spin = false;
    controls.autoRotate = false;
    document.querySelector('[data-view="spin"]')?.classList.remove('on');
    const damping = controls.enableDamping;
    // Clear pending orbit/pan deltas before assigning the default camera.
    controls.enableDamping = false;
    controls.update();
    perspCam.zoom = 1;
    orthoCam.zoom = 1;
    perspCam.updateProjectionMatrix();
    orthoCam.updateProjectionMatrix();
    setView(view);
    controls.enableDamping = damping;
    document.querySelectorAll('[data-view]').forEach(button => {
      if (button.dataset.view !== 'spin') button.classList.toggle('on', button.dataset.view === view);
    });
  }
  renderer.domElement.addEventListener('dblclick', event => {
    if (event.button === 0) resetDefaultView();
    else if (event.button === 1) resetView('top');
  });
  let lastMiddleClick = null, middlePress = null;
  renderer.domElement.addEventListener('pointerdown', event => {
    if (event.button === 1) middlePress = {x: event.clientX, y: event.clientY};
    else lastMiddleClick = null;
  });
  // OrbitControls suppresses compatibility mouse events during middle-button
  // panning, so use pointer releases rather than relying on auxclick.
  renderer.domElement.addEventListener('pointerup', event => {
    if (event.button !== 1) return;
    event.preventDefault();
    const dragged = middlePress && Math.hypot(event.clientX - middlePress.x, event.clientY - middlePress.y) > 6;
    middlePress = null;
    if (dragged) { lastMiddleClick = null; return; }
    const now = event.timeStamp;
    if (lastMiddleClick && event !== lastMiddleClick.event && now >= lastMiddleClick.time && now - lastMiddleClick.time < 500 &&
        Math.hypot(event.clientX - lastMiddleClick.x, event.clientY - lastMiddleClick.y) < 6) {
      lastMiddleClick = null;
      resetView('top');
    } else lastMiddleClick = {time: now, x: event.clientX, y: event.clientY, event};
  });
  renderer.domElement.addEventListener('pointercancel', () => { middlePress = null; lastMiddleClick = null; });
  controls.addEventListener('change', () => { invalidateModel(); updateOverlay(); });
  for (const event of ['resize', 'click', 'input', 'change', 'pointerdown', 'wheel',
    'message', 'visibilitychange', 'reference-tube-focused', 'workspace-tubes-selected']) {
    window.addEventListener(event, invalidateModel, {capture:true, passive:true});
  }
}

/* ---------- 中性环境贴图 ----------
 * 原来用 three 自带的 RoomEnvironment：它是个摄影棚，6 块面光源亮度悬殊（100/50/50/43/20/17），
 * 金属件（metalness 0.72~0.85）反射几乎全是这些色块，管座/贯穿管的本色谱被带偏，
 * 画面上出现一圈青绿色（实测 165°~195° 色相的像素占 6.3%，而零件基色应集中在 210° 附近）。
 * 这里自己画一张 equirect 环境代替：只给「明度层次」，不引入任何色相——
 * 底色是上白下灰的垂直渐变，三块柔光全是纯白（aussian 径向渐变），
 * 金属该有的高光与纵深都在，颜色则由 scene 的方向灯和基色决定，不会再被环境染色。
 * 代价是不再显示 RoomEnvironment 的房间背景（我们本来就用纯色背景，不影响）。 */
function makeNeutralEnv(pmrem) {
  const c = document.createElement('canvas');
  c.width = 1024; c.height = 512;
  const g = c.getContext('2d');

  // 天地渐变：饱和度压到 0.04 以内，只留冷灰，不参与染色
  const grad = g.createLinearGradient(0, 0, 0, c.height);
  grad.addColorStop(0.00, '#fcfdfe');
  grad.addColorStop(0.42, '#e9eef3');
  grad.addColorStop(0.54, '#dbe3ea');
  grad.addColorStop(1.00, '#b7c2cd');
  g.fillStyle = grad;
  g.fillRect(0, 0, c.width, c.height);

  const blob = (cx, cy, r, a) => {
    const rg = g.createRadialGradient(cx, cy, 0, cx, cy, r);
    rg.addColorStop(0, `rgba(255,255,255,${a})`);
    rg.addColorStop(0.55, `rgba(255,255,255,${a * 0.42})`);
    rg.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = rg;
    g.fillRect(cx - r, cy - r, r * 2, r * 2);
  };
  blob(c.width * 0.50, c.height * 0.14, c.width * 0.34, 0.95);   // 顶灯：给管子顶面一道主高光
  blob(c.width * 0.14, c.height * 0.40, c.width * 0.24, 0.40);   // 左前弱侧光
  blob(c.width * 0.86, c.height * 0.44, c.width * 0.24, 0.28);   // 右后更弱：留出明暗差

  const tex = new THREE.CanvasTexture(c);
  tex.mapping = THREE.EquirectangularReflectionMapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  const env = pmrem.fromEquirectangular(tex).texture;
  tex.dispose();
  return env;
}

function makeMat(color, metalness) {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(color),
    metalness: metalness ?? 0.8,
    roughness: 0.34,
    envMapIntensity: 1.0,
    side: THREE.DoubleSide,
    clippingPlanes: [],
    clipShadows: false,
  });
}

/* ----------------------------------------------------------------- 装配 */
function buildTubeGeometry() {
  const g = model.geometry || {
    tube_od: 8.6, tube_id: 5.2, tip_radius: 2.0, tip_cone_half_angle: 30,
    tip_fillet: 0.8, end_chamfer: 0.5,
  };
  return revolve(tubeProfile(state.L, g), 128);
}

function buildAssembly() {
  partsMeshes.clear();
  while (root.children.length) {
    const c = root.children.pop();
    c.geometry?.dispose();
  }

  const tubeMeta = model.parts.find((p) => p.id === 'P01');
  tubeMat = makeMat(TUBE_BASE_COLOR, tubeMeta.metalness);
  tubeMesh = new THREE.Mesh(buildTubeGeometry(), tubeMat);
  tubeMesh.userData = tubeMeta;
  tubeMesh.name = 'P01';
  root.add(tubeMesh);
  partsMeshes.set('P01', tubeMesh);

  for (const p of model.parts) {
    if (p.id === 'P01') continue;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(p.positions, 3));
    if (p.normals && p.normals.length) geo.setAttribute('normal', new THREE.Float32BufferAttribute(p.normals, 3));
    else geo.computeVertexNormals();
    geo.setIndex(p.indices);
    const mat = makeMat(p.color, p.metalness);
    const mesh = new THREE.Mesh(geo, mat);
    mesh.name = p.id;
    mesh.userData = p;
    mesh.visible = !p.hidden;
    if (p.id === 'P04') mesh.position.x = 96;   // 关联接口件：偏置展示，避免与管座重叠
    if (p.id === 'P05' || p.id === 'P06') mesh.userData.isContext = true;
    root.add(mesh);
    partsMeshes.set(p.id, mesh);
  }
  applyGhost();
  buildTree();      // 会隐藏 P04，必须在建模板组之前跑
  applyExplode();
  applyCut();       // 可见性与位姿都定下来之后再建封盖，否则会留下幽灵封盖
  buildStations();
  updateOverlay();
}

function applyGhost() {
  for (const [id, mesh] of partsMeshes) {
    const p = mesh.userData;
    const isCtx = p.kind === 'context';
    const m = mesh.material;
    m.transparent = isCtx && state.ghost;
    m.opacity = isCtx && state.ghost ? 0.22 : 1;
    m.depthWrite = !(isCtx && state.ghost);
    m.metalness = p.metalness ?? 0.8;
    m.needsUpdate = true;
  }
}

/* 剖切封盖（网格切片）
 * ---------------------------------------------------------------------------
 * 为什么不用模板(stencil)奇偶法：
 *   那套算法依赖"视线穿过被切开的表面"，对细长件无效 —— 指套管沿 Y 轴，
 *   剖切面是 YZ 平面、视线沿 X，射线整段都在材料内部，前后面的增减恒为 0，
 *   结果封盖只剩边界细缝，还会在轮廓外漏一圈。实测溢出面占 71%。
 *
 * 改为真切片：把每个零件的三角形与剖切面求交得到交线段，缝合成闭环，
 * 判定外环/内孔后交给 three 的 ShapeGeometry（内部用 earcut）三角化。
 * 与视角无关，得到的是真正的材料截面。
 */
let capState = { caps: [] };
const PLANE_N = new THREE.Vector3(-1, 0, 0);   // 剖切面法向：保留 x < px 的一半
const SEG_EPS = 1e-6;
const KEY_Q = 1000;                            // 顶点合并量化：0.001 mm

function clearCaps() {
  for (const c of capState.caps) {
    if (c.parent) c.parent.remove(c);
    c.geometry?.dispose?.();       // 材质走 capMatCache 复用，不能在这里 dispose
  }
  capState = { caps: [] };
}

/** 把网格按世界平面 x = px 切开，返回若干闭环（世界 y,z 坐标）。 */
function sliceLoops(geo, matrixWorld, px) {
  const pos = geo.attributes.position;
  const index = geo.index;
  const n = pos.count;
  const P = new Float64Array(n * 3);
  const v = new THREE.Vector3();
  for (let i = 0; i < n; i++) {
    v.fromBufferAttribute(pos, i).applyMatrix4(matrixWorld);
    P[i * 3] = v.x; P[i * 3 + 1] = v.y; P[i * 3 + 2] = v.z;
  }

  const triCount = index ? index.count / 3 : n / 3;
  const vi = (t, k) => (index ? index.getX(t * 3 + k) : t * 3 + k);

  // 1) 三角形 × 平面 → 交线段
  //
  // 关键坑：回转体的母线顶点正好落在剖切面上（角度 0 与 π 处 x = r·sinθ = 0），
  // 于是跨面三角形几乎都是"一个顶点在面上、另两个分居两侧"的形态，
  // 只算严格穿越的边只能得到 1 个交点，永远凑不成线段 —— 之前封盖全空就是这个原因。
  // 所以顶点落在面上的情形必须一并收集。
  const segs = [];                              // [y1,z1,y2,z2]
  for (let t = 0; t < triCount; t++) {
    const a = vi(t, 0), b = vi(t, 1), c = vi(t, 2);
    const da = P[a * 3] - px, db = P[b * 3] - px, dc = P[c * 3] - px;
    const na = da > SEG_EPS, nb = db > SEG_EPS, nc = dc > SEG_EPS;
    const la = da < -SEG_EPS, lb = db < -SEG_EPS, lc = dc < -SEG_EPS;
    if ((na && nb && nc) || (la && lb && lc)) continue;   // 整块在某一侧

    const pts = [];
    const pushV = (i) => {
      const y = P[i * 3 + 1], z = P[i * 3 + 2];
      for (const q of pts) if (Math.abs(q[0] - y) < 1e-6 && Math.abs(q[1] - z) < 1e-6) return;
      pts.push([y, z]);
    };
    const edge = (i, j, di, dj) => {
      const oi = Math.abs(di) <= SEG_EPS, oj = Math.abs(dj) <= SEG_EPS;
      if (oi) pushV(i);                       // 顶点就在面上
      if (oj) pushV(j);
      if (oi || oj) return;
      if ((di > 0) !== (dj > 0)) {            // 严格穿越
        const s = di / (di - dj);
        const y = P[i * 3 + 1] + (P[j * 3 + 1] - P[i * 3 + 1]) * s;
        const z = P[i * 3 + 2] + (P[j * 3 + 2] - P[i * 3 + 2]) * s;
        for (const q of pts) if (Math.abs(q[0] - y) < 1e-6 && Math.abs(q[1] - z) < 1e-6) return;
        pts.push([y, z]);
      }
    };
    edge(a, b, da, db); edge(b, c, db, dc); edge(c, a, dc, da);

    if (pts.length === 2) segs.push([pts[0][0], pts[0][1], pts[1][0], pts[1][1]]);
    else if (pts.length > 2) {
      // 退化情形（顶点在面上又有一边穿越）：取距离最远的两点
      let best = null, bestD = -1;
      for (let m = 0; m < pts.length; m++) {
        for (let k = m + 1; k < pts.length; k++) {
          const d = Math.hypot(pts[m][0] - pts[k][0], pts[m][1] - pts[k][1]);
          if (d > bestD) { bestD = d; best = [pts[m], pts[k]]; }
        }
      }
      if (best && bestD > 1e-6) segs.push([best[0][0], best[0][1], best[1][0], best[1][1]]);
    }
  }
  if (!segs.length) return [];

  // 2) 去重：落在剖切面内的边会被相邻两个三角形各报一次（方向相反），
  //    不去重的话缝合出来是 A→B→A 的退化闭环，面积恒为 0。
  const key = (y, z) => `${Math.round(y * KEY_Q)}|${Math.round(z * KEY_Q)}`;
  const seen = new Set();
  const uniq = [];
  for (const g of segs) {
    const d = Math.hypot(g[2] - g[0], g[3] - g[1]);
    if (d < 1e-6) continue;                       // 零点线段
    const k1 = key(g[0], g[1]), k2 = key(g[2], g[3]);
    const sig = k1 < k2 ? k1 + '>' + k2 : k2 + '>' + k1;
    if (seen.has(sig)) continue;
    seen.add(sig);
    uniq.push(g);
  }
  if (!uniq.length) return [];
  segs.length = 0;
  for (const g of uniq) segs.push(g);

  // 3) 端点量化后缝合成闭环
  const byKey = new Map();
  const used = new Uint8Array(segs.length);
  segs.forEach((s, i) => {
    for (const [y, z] of [[s[0], s[1]], [s[2], s[3]]]) {
      const k = key(y, z);
      if (!byKey.has(k)) byKey.set(k, []);
      byKey.get(k).push(i);
    }
  });

  const loops = [];
  for (let i = 0; i < segs.length; i++) {
    if (used[i]) continue;
    used[i] = 1;
    const s0 = segs[i];
    const loop = [[s0[0], s0[1]], [s0[2], s0[3]]];
    let curKey = key(s0[2], s0[3]);
    const startKey = key(s0[0], s0[1]);
    for (let guard = 0; guard < segs.length + 4; guard++) {
      if (curKey === startKey) break;
      const cands = byKey.get(curKey) || [];
      let next = -1;
      for (const c of cands) if (!used[c]) { next = c; break; }
      if (next < 0) break;                       // 断口：材料被切成开链，丢弃尾段
      used[next] = 1;
      const s = segs[next];
      const fwd = key(s[0], s[1]) === curKey;
      const py = fwd ? s[2] : s[0], pz = fwd ? s[3] : s[1];
      loop.push([py, pz]);
      curKey = key(py, pz);
    }
    if (loop.length > 2) loops.push(loop);
  }
  return loops;
}

const area2 = (loop) => {
  let a = 0;
  for (let i = 0, n = loop.length; i < n; i++) {
    const [y1, z1] = loop[i], [y2, z2] = loop[(i + 1) % n];
    a += y1 * z2 - y2 * z1;
  }
  return a / 2;
};

const pointInLoop = (pt, loop) => {
  let inside = false;
  const [py, pz] = pt;
  for (let i = 0, j = loop.length - 1; i < loop.length; j = i++) {
    const [yi, zi] = loop[i], [yj, zj] = loop[j];
    if ((zi > pz) !== (zj > pz) && py < ((yj - yi) * (pz - zi)) / (zj - zi) + yi) inside = !inside;
  }
  return inside;
};

/** 去掉相邻重复点与首尾重复点：量化后极易产生零长边，earcut 会算出 NaN。 */
function cleanLoop(loop) {
  const near = (a, b) => Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4;
  const out = [];
  for (const pt of loop) {
    if (out.length && near(out[out.length - 1], pt)) continue;
    out.push(pt);
  }
  while (out.length > 1 && near(out[0], out[out.length - 1])) out.pop();
  return out;
}

/** 把若干闭环转成带孔的 ShapeGeometry（平面坐标系 u=z, v=y）。 */
function loopsToGeometry(loops) {
  const items = [];
  for (const l of loops) {
    const cl = cleanLoop(l);
    if (cl.length < 3) continue;
    const a = area2(cl);
    if (Math.abs(a) < 1e-2) continue;            // 0.01 mm² 以下的碎片（螺纹牙缝）丢掉
    items.push({ loop: cl, sign: Math.sign(a), area: Math.abs(a) });
  }
  if (!items.length) return null;

  const ring = (it, outerSign) => {
    const pts = it.loop.map(([y, z]) => new THREE.Vector2(z, y));
    // earcut 要求内外环绕向相反，否则孔洞会被当成实心
    if (outerSign && it.sign === outerSign) pts.reverse();
    return pts;
  };
  items.sort((a, b) => b.area - a.area);

  const shapes = [];
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.used) continue;
    it.used = true;
    const shape = new THREE.Shape(ring(it, 0));
    for (let j = i + 1; j < items.length; j++) {
      const h = items[j];
      if (h.used || h.area >= it.area) continue;
      if (pointInLoop(h.loop[0], it.loop)) {     // 被本外环包含 → 内孔
        h.used = true;
        shape.holes.push(new THREE.Path(ring(h, it.sign)));
      }
    }
    shapes.push(shape);
  }
  if (!shapes.length) return null;

  const geos = shapes.map((s) => new THREE.ShapeGeometry(s));
  for (const g of geos) {
    const arr = g.attributes.position.array;
    for (let k = 0; k < arr.length; k++) {
      if (!Number.isFinite(arr[k])) { g.dispose(); return null; }   // 三角化出 NaN 就整件放弃
    }
  }
  if (geos.length === 1) return geos[0];

  // 多个外环（断开的多块截面）合并成一个几何
  let vCount = 0, iCount = 0;
  for (const g of geos) { vCount += g.attributes.position.count; iCount += g.index ? g.index.count : 0; }
  const pos = new Float32Array(vCount * 3);
  const idx = new Uint32Array(iCount);
  let vo = 0, io = 0;
  for (const g of geos) {
    pos.set(g.attributes.position.array, vo * 3);
    const gi = g.index.array;
    for (let k = 0; k < gi.length; k++) idx[io + k] = gi[k] + vo;
    vo += g.attributes.position.count;
    io += gi.length;
    g.dispose();
  }
  const merged = new THREE.BufferGeometry();
  merged.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  merged.setIndex(new THREE.BufferAttribute(idx, 1));
  merged.computeVertexNormals();
  return merged;
}

const capMatCache = new Map();
function capMaterial(color) {
  const k = new THREE.Color(color).getHexString();
  const hit = capMatCache.get(k);
  if (hit) return hit;
  const mat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(color),
    metalness: 0.1,
    roughness: 0.85,
    side: THREE.DoubleSide,
    polygonOffset: true,          // 与零件表面共面时避免 Z 打架
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
  });
  capMatCache.set(k, mat);
  return mat;
}

function applyCut() {
  clearCaps();
  const on = state.cut;
  clipPlane.constant = state.cutPos;

  for (const [id, mesh] of partsMeshes) {
    if (!on) {
      mesh.material.clippingPlanes = [];
      mesh.material.side = THREE.DoubleSide;
      mesh.material.needsUpdate = true;
      continue;
    }
    // 剖切面跟着零件自身的显示偏置走（螺母偏置 ≠ 0，共用世界面会被整件切掉）
    const px = state.cutPos + mesh.position.x;
    mesh.material.clippingPlanes = [new THREE.Plane(PLANE_N.clone(), px)];
    mesh.material.side = THREE.FrontSide;
    mesh.material.needsUpdate = true;
    if (!mesh.visible) continue;

    mesh.updateMatrixWorld(true);
    const loops = sliceLoops(mesh.geometry, mesh.matrixWorld, px);
    if (!loops.length) continue;
    const geo = loopsToGeometry(loops);
    if (!geo) continue;

    const isCtx = mesh.userData.kind === 'context';
    const base = new THREE.Color(mesh.userData.color || '#9aa8b8');
    const tint = base.lerp(new THREE.Color(isCtx ? '#c9d4e1' : '#8c9bab'), isCtx ? 0.72 : 0.62);

    const cap = new THREE.Mesh(geo, capMaterial(tint));
    cap.rotation.y = -Math.PI / 2;               // 平面 (u=z, v=y) → 世界 YZ 平面，法向 -X
    cap.position.x = px;
    cap.renderOrder = 4;
    root.add(cap);
    capState.caps.push(cap);
  }

  $('cutVal').textContent = on ? state.cutPos.toFixed(1) + ' mm' : '关';
}

function applyExplode() {
  for (const [id, mesh] of partsMeshes) {
    const k = state.explode / 100;
    if (id === 'P01') mesh.position.set(0, k * state.L * 0.055, 0);
    else if (id === 'P02') mesh.position.set(0, 0, k * 78);
    else if (id === 'P04') mesh.position.set(96 + k * 60, k * 26, 0);
    else if (id === 'P05') mesh.position.set(0, -k * 120, 0);
    else if (id === 'P06') mesh.position.set(0, -k * 220, 0);
    else if (id === 'P03') mesh.position.set(0, k * 130, 0);
  }
  if (state.cut) applyCut();
  updateOverlay();
}

/* ----------------------------------------------------------------- 零件树 */
function buildTree() {
  const tree = $('tree');
  tree.innerHTML = '';
  for (const p of model.parts) {
    const el = document.createElement('div');
    el.className = 'item';
    el.dataset.id = p.id;
    const src = p.kind === 'step' ? 'STEP' : (p.kind === 'context' ? '环境' : '参数化');
    el.innerHTML = `<span class="dot" style="background:${p.color}"></span>
      <span>${p.cn}</span><span class="src">${src}</span>
      <span class="eye">${partsMeshes.get(p.id)?.visible ? '●' : '○'}</span>`;
    el.onclick = () => {
      const mesh = partsMeshes.get(p.id);
      if (!mesh) return;
      /* 整体布置模式下 root（单件）是隐藏的：此时点零件树只有信息卡换字、画面一像素不动，
         用户会当成"点了没生效"。零件组的标题写的是「点击查看」，那就必须真看得见——
         自动切到接口详图（最近的一次单件特写），再弹卡片。 */
      if (state.mode === 'assembly') setMode('joint');
      mesh.visible = true;                                  // 右键隐藏过的件，左键点一下就恢复
      el.classList.remove('off');
      el.querySelector('.eye').textContent = '●';
      if (state.cut) applyCut();
      showInfo(p.id);
      tree.querySelectorAll('.item').forEach((n) => n.classList.toggle('sel', n.dataset.id === p.id));
    };
    el.oncontextmenu = (ev) => {
      ev.preventDefault();
      const mesh = partsMeshes.get(p.id);
      if (!mesh) return;
      mesh.visible = !mesh.visible;
      el.querySelector('.eye').textContent = mesh.visible ? '●' : '○';
      el.classList.toggle('off', !mesh.visible);
      if (state.cut) applyCut();     // 可见性变了要重建模板组与封盖
      if (state.selected === p.id) $('right').classList.add('hide');
    };
    tree.appendChild(el);
  }
  // P04 默认隐藏
  const m4 = partsMeshes.get('P04');
  if (m4) {
    m4.visible = false;
    const el = tree.querySelector('[data-id="P04"]');
    if (el) { el.classList.add('off'); el.querySelector('.eye').textContent = '○'; }
  }
}

/* ----------------------------------------------------------------- 信息卡 */
const DIM_ROWS = {
  P01: ['D01', 'D02', 'D03', 'D04', 'D05'],
  P02: ['D09', 'D10', 'D11', 'D12', 'D13'],
  P04: ['D15', 'D16', 'D17', 'D18', 'D19', 'D21'],
  P05: ['D22'],
  P06: ['D23'],
};

function showInfo(id) {
  const p = model.parts.find((x) => x.id === id);
  if (!p) return;
  state.selected = id;
  $('right').classList.remove('hide');
  $('infoName').textContent = p.cn + '　' + (p.en || '');
  const srcLabel = p.kind === 'step' ? '原始 STEP B-rep' : (p.kind === 'context' ? '环境件' : '参数化重建');
  $('infoTags').innerHTML = `<span class="tag">${p.id}</span><span class="tag">${srcLabel}</span>
    <span class="tag">${(p.triCount || 0).toLocaleString()} 三角面</span>`;

  const rows = [];
  const dimById = {};
  for (const d of (dims?.dimensions || [])) dimById[d.id] = d;
  for (const did of (DIM_ROWS[id] || [])) {
    const d = dimById[did];
    if (!d) continue;
    const v = Array.isArray(d.value) ? d.value.join(' / ') : d.value;
    rows.push([d.name, `${v}${d.tol && d.tol !== '—' && d.tol !== '°' ? '　' + (d.tol.length < 6 ? d.tol : '') : ''}`]);
  }
  if (p.volumeMm3) rows.push(['体积', (p.volumeMm3 / 1000).toFixed(2) + ' cm³']);
  if (id === 'P01') {
    rows.push(['当前管长 L', state.L.toFixed(1) + ' mm']);
    rows.push(['通道', state.channel
      ? `${state.channel.pos}（奇#${state.channel.serialOdd || '—'} / 偶#${state.channel.serialEven || '—'}）`
      : '自定义']);
  }
  $('infoTable').innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  $('infoNote').textContent = p.note || '';
}

/* ----------------------------------------------------------------- P1–P6 标记 */
let stationGroup = null;
function buildStations() {
  if (stationGroup) { root.remove(stationGroup); stationGroup.traverse((o) => { o.geometry?.dispose(); }); }
  stationGroup = new THREE.Group();
  stationGroup.name = 'stations';
  root.add(stationGroup);
  const st = stations.stations.filter((s) => s.fromTop !== null);
  for (const s of st) {
    const fromTop = s.fromTop === 'L' ? state.L : s.fromTop;
    const y = state.L - fromTop;
    const est = s.status === '推定';
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(state.fat ? 27 : 6.6, state.fat ? 1.2 : 0.55, 8, 48),
      new THREE.MeshBasicMaterial({ color: est ? 0xd98b2b : 0x0b6bcb, transparent: true, opacity: 0.95 })
    );
    ring.rotation.x = Math.PI / 2;
    ring.position.y = y;
    ring.userData = { station: s, anchor: new THREE.Vector3(0, y, 0) };
    stationGroup.add(ring);
    s._y = y;
  }
  stationGroup.visible = state.stations;
}

/* ----------------------------------------------------------------- 标注 */
const dimDefs = [
  { id: 'tubeOD', text: '指套管 Φ8.6（壁厚 1.7）', p: [4.3, 178, 0], mode: ['joint', 'full'] },
  { id: 'socketTop', text: '管座端面 / 密封锥', p: [0, 126.87, 0], mode: ['joint', 'socket'] },
  { id: 'socketOD', text: '管座 Φ47.3', p: [23.65, 62, 0], mode: ['joint', 'socket'] },
  { id: 'socketBore', text: '内孔 Φ13.84', p: [6.92, 96, 0], mode: ['socket'] },
  { id: 'socketThr', text: '内螺纹 Φ25.127', p: [12.56, 30, 0], mode: ['socket'] },
  { id: 'nutOD', text: '调整螺母 Φ57.15', p: [96 + 28.575, 60, 0], mode: ['joint'] },
  { id: 'pipeOD', text: '中子测量贯穿管 Φ50.8', p: [25.4, -70, 0], mode: ['joint', 'full'] },
];

function updateOverlay() {
  const svg = $('leaders');
  svg.innerHTML = '';
  const w = innerWidth, h = innerHeight;
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  for (const el of document.querySelectorAll('.dim')) el.remove();
  if (!camera || w <= 0 || h <= 0) return;
  if (state.mode === 'assembly') return;   // 整体模式不加零件标注，避免盖住管束

  const project = (v) => {
    const p = v.clone().project(camera);
    return { x: (p.x * 0.5 + 0.5) * w, y: (-p.y * 0.5 + 0.5) * h,
      behind: ![p.x, p.y, p.z].every(Number.isFinite) || p.z > 1 };
  };

  // 尺寸标注
  if (state.dims) {
    for (const d of dimDefs) {
      if (!d.mode.includes(state.mode)) continue;
      if (d.id === 'nutOD' && !partsMeshes.get('P04')?.visible) continue;
      let ay = d.p[1];
      if (state.mode === 'full' && d.id === 'tubeOD') ay = state.L - 150;
      if (state.mode === 'full' && d.id === 'pipeOD') ay = -160;
      const anchor = new THREE.Vector3(d.p[0] * (state.fat ? 4 : 1), ay, d.p[2] * (state.fat ? 4 : 1));
      const s = project(anchor);
      if (s.behind) continue;
      const el = document.createElement('div');
      el.className = 'dim';
      el.textContent = d.text;
      el.style.left = (s.x + 54) + 'px';
      el.style.top = (s.y - 16) + 'px';
      document.body.appendChild(el);
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('x1', s.x); ln.setAttribute('y1', s.y);
      ln.setAttribute('x2', s.x + 48); ln.setAttribute('y2', s.y - 18);
      svg.appendChild(ln);
    }
  }

  // P1–P6 标记
  if (state.stations && stationGroup?.visible && state.mode !== 'full') {
    for (const s of stations.stations) {
      if (s._y === undefined) continue;
      const p = project(new THREE.Vector3(0, s._y, 0));
      if (p.behind) continue;
      const el = document.createElement('div');
      el.className = 'dim station' + (s.status === '推定' ? ' est' : '');
      el.textContent = s.id + (s.status === '推定' ? '?' : '');
      el.style.left = (p.x + 44) + 'px';
      el.style.top = p.y + 'px';
      document.body.appendChild(el);
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      ln.setAttribute('class', 'station');
      ln.setAttribute('x1', p.x + 6); ln.setAttribute('y1', p.y);
      ln.setAttribute('x2', p.x + 40); ln.setAttribute('y2', p.y);
      svg.appendChild(ln);
    }
  }
}

/* ----------------------------------------------------------------- P1–P6 标尺 */
function syncAuxiliaryPanels() {
  $('scale').hidden = state.mode !== 'full' || !$('right').classList.contains('hide')
    || Boolean($('referenceInspection')?.open) || document.body.classList.contains('reference-controls-open');
}

function renderScale() {
  const box = $('scale');
  syncAuxiliaryPanels();
  if (state.mode !== 'full') { box.classList.add('hide'); return; }
  box.classList.remove('hide');
  const ticks = box.querySelector('.ticks');
  ticks.innerHTML = '';
  const L = state.L;
  for (const st of stations.stations) {
    if (st.fromTop === null) continue;
    const d = st.fromTop === 'L' ? L : st.fromTop;
    const t = Math.max(0, Math.min(1, d / L));
    const el = document.createElement('div');
    el.className = 'tick' + (st.status === '推定' ? ' est' : '');
    el.style.top = `${t * 100}%`;
    const pct = d / L * 100;
    el.innerHTML = `<span class="lab">${st.id}</span><span class="dep">${d.toFixed(1)} mm (${pct.toFixed(0)}%)</span>`;
    ticks.appendChild(el);
  }
}

/* ----------------------------------------------------------------- 视角 */
function normDir(v) {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}

function resetDefaultView(options = {}) {
  const rotate = options.rotate === true;
  const damping = controls.enableDamping;
  controls.autoRotate = false;
  controls.enableDamping = false;
  controls.update();
  Object.assign(state, {spin:false,cut:false,cutPos:0,cutPrv:false,explode:0,
    prv:true,dome:true,struct:true,penetrations:true,axes:true,ghost:true,dims:true,
    stations:true,axis:false,fat:true,fatAuto:true,lenColor:false,typeColor:false,depthColor:false,
    typeFilter:null,colVis:{},selected:null,topPlate:false});
  const flags = {optPrv:'prv',optDome:'dome',optStruct:'struct',optPenetrations:'penetrations',
    optAxes:'axes',optGhost:'ghost',optDims:'dims',optStations:'stations',optAxis:'axis',
    optFat:'fat',optCut:'cut',optCutPrv:'cutPrv',optLenColor:'lenColor',optTypeColor:'typeColor',optDepthColor:'depthColor'};
  for (const [id,key] of Object.entries(flags)) $(id).checked = state[key];
  syncDepthLegend();
  $('exSlider').value = $('cutSlider').value = '0';
  document.body.classList.remove('reference-controls-open');
  $('referencePanelToggle').setAttribute('aria-expanded','false');
  if ($('referenceInspection')) $('referenceInspection').open = false;
  $('right').classList.add('hide');
  for (const group of Object.values(asmG.colByType || {})) for (const child of group) child.visible = true;
  for (const mesh of partsMeshes.values()) mesh.visible = true;
  root.children.filter(child=>child.name==='axisHelper').forEach(child=>{
    root.remove(child); child.geometry?.dispose(); child.material?.dispose();
  });
  perspCam.zoom = orthoCam.zoom = 1;
  perspCam.updateProjectionMatrix(); orthoCam.updateProjectionMatrix();
  setMode('assembly');
  applyTubeInstances(); applyTubeColor(); applyPrvCut(); applyExplode(); applyCut(); applyGhost();
  buildTree(); fillColumnLegend(); fillModelLegend();
  setView('iso');
  $('right').classList.add('hide');
  controls.enableDamping = damping;
  document.querySelectorAll('[data-view]').forEach(button => button.classList.toggle('on',button.dataset.view==='iso'));
  state.spin = controls.autoRotate = rotate;
  controls.autoRotateSpeed = 1.1;
  document.querySelector('[data-view="spin"]')?.classList.toggle('on',rotate);
  invalidateModel();
}

/* 整体布置视角：按包络尺度定距，不跟着单管长度走 */
/** 整体布置的包围盒（含包络外壳）。
 *  includeDome：正交视图（正视/侧视/俯视）传 true —— 视锥是精确贴合的，不算封头就会
 *  被画面下沿硬切一刀，半透明白弧悬在边框外，看着像渲染出错。含封头只多 17%（4229 → 4948）。
 *  轴测/适配传 false —— 透视取景本来留了余量，封头能自然落在画面内，算进去只会把 50 根管子缩小一圈。 */
function asmBoundingBox(includeDome) {
  if (!asmRoot) return null;
  const box = new THREE.Box3();
  for (const child of asmRoot.children) {
    if (!child.visible) continue;
    if (!includeDome && child === asmG.dome) continue;
    box.expandByObject(child);
  }
  return box.isEmpty() ? null : box;
}

/* 切相机：controls 的 object、模块级 camera、调试句柄三者必须一起换，
   否则投影（尺寸标注）、射线拾取、轴标方向会用到另一台相机的矩阵。 */
function useCam(next) {
  if (camera === next && controls.object === next) return;
  camera = next;
  controls.object = next;
  window.__camera = next;
}

/** 画布上真正"看得见"的横向区间（画布像素）。
 *  左栏与右侧信息卡都浮在画布上方，取景若按整幅画布居中，
 *  模型右半边会被卡片吃掉（俯视时容器圆直接被切掉一块）。
 *  两栏都可在 UI 里收起，所以每次都按当前 DOM 实测，不写死像素。 */
function visibleBand() {
  const cv = renderer.domElement.getBoundingClientRect();
  let left = 0, right = cv.width;
  const l = document.getElementById('left');
  if (l) {
    const b = l.getBoundingClientRect();
    if (b.width > 0 && !l.classList.contains('hide')) left = Math.max(0, b.right - cv.left) + 10;
  }
  const r = document.getElementById('right');
  if (r) {
    const b = r.getBoundingClientRect();
    // Reserve the final layout width, not the transient scale-in animation.
    if (b.width > 0 && !r.classList.contains('hide')) right = Math.min(cv.width, r.offsetLeft - cv.left - 10);
  }
  if (right - left < 260) { left = 0; right = cv.width; }   // 窗口太窄就别让位了，宁可压一点
  return { left, right };
}

function setAsmView(name) {
  if (!vessel) return;
  const V = vessel.vessel;
  const dirs = {
    iso: [0.52, 0.40, 0.76], front: [0, 0, 1], back: [0, 0, -1],
    left: [-1, 0, 0], side: [1, 0, 0], bottom: [0, -1, 0],
    /* 俯视严格垂直：正交相机没有"视线与 up 平行导致基向量退化"的问题
       （up=(0,0,-1) 与视线 (0,-1,0) 正交），所以不必再为稳定而故意倾斜。
       之前那 2.43° 的偏置在透视下会把 2.7 m 长的管子拉成 40 px 斜纹。 */
    top: [0, 1, 0], fit: [0.52, 0.40, 0.76],
  };
  const v = new THREE.Vector3().fromArray(normDir(dirs[name] || dirs.iso));
  const wantOrtho = ['front', 'back', 'left', 'side', 'top', 'bottom'].includes(name);
  const box = asmBoundingBox(wantOrtho);
  /* 剖切只留 x≤0 半边：包围盒也跟着夹到 ≤0，否则中心还停在整件的中点，
     剖开后模型会挤在画面左半边、右边空一大片（旧版靠 t.x -= R*0.18 硬挪，只能补 18%）。 */
  if (box && state.cutPrv) box.max.x = Math.min(box.max.x, 0);
  const center = box ? box.getCenter(new THREE.Vector3())
    : new THREE.Vector3(0, (V.headBottomY + V.cylinderTopY) / 2, 0);

  /* 取景不能按"画布多大"算 —— 左栏和右侧信息卡都浮在画布上，
     按画布居中装进去，模型两边会被面板吃掉（俯视时容器圆直接被切一块）。
     这里按实测的"可见带"求视场，再把视点整体平移，模型就落在看得见的那块正中。 */
  const w = Math.max(1, renderer.domElement.clientWidth || innerWidth);
  const h = Math.max(1, renderer.domElement.clientHeight || innerHeight);
  const band = visibleBand();
  const effW = Math.max(240, band.right - band.left);
  const effH = Math.max(300, h - 104);            // 让开顶栏与底部提示条
  const bandShiftPx = (band.left + band.right) / 2 - w / 2;   // 可见带中心相对画布中心（>0 = 偏右）
  const fovV = THREE.MathUtils.degToRad(perspCam.fov);
  const fovH = 2 * Math.atan(Math.tan(fovV / 2) * (effW / effH));
  const tanV = Math.tan(fovV / 2), tanH = Math.tan(fovH / 2);

  const forward = v.clone().negate();             // 目标 → 相机 的反向（视线方向）
  /* 俯视时视线几乎与默认 up=(0,1,0) 平行，lookAt 的基向量退化 ——
     画面会绕视线轴自转 45°。俯视改用 up=(0,0,-1)，让 -Z 朝屏幕上方，与读图习惯一致。
     取景的 right/up 也必须跟着用同一个 up 提示，否则算出的取景框与最终画面不是一个朝向。 */
  const upHint = name === 'top' ? new THREE.Vector3(0, 0, -1)
    : name === 'bottom' ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(0, 1, 0);
  const right = new THREE.Vector3().crossVectors(forward, upHint);
  if (right.lengthSq() < 1e-6) right.set(1, 0, 0);
  right.normalize();
  const up = new THREE.Vector3().crossVectors(right, forward).normalize();

  /* 包围盒 8 个角点在相机基上的投影：横向/纵向半跨（正交直接拿去开视锥）、
     以及朝相机的最大深度（定 near/far）。剖切时 +X 半边已被切掉，角点 x 先夹到 ≤0。
     不按包围球半径 / sin(半角) 算：容器是矮胖圆柱，球半径被对角线撑大，会白留 40% 空边。 */
  let maxU = 0, maxV = 0, maxDepth = 0;
  if (box) {
    const c = new THREE.Vector3();
    for (let i = 0; i < 8; i++) {
      c.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z);
      if (state.cutPrv && c.x > 0) c.x = 0;
      const p = c.sub(center);
      maxU = Math.max(maxU, Math.abs(p.dot(right)));
      maxV = Math.max(maxV, Math.abs(p.dot(up)));
      maxDepth = Math.max(maxDepth, p.dot(v));
    }
  }
  if (!(maxU > 0) || !(maxV > 0)) {
    maxU = V.outerRadius * 1.2;
    maxV = Math.abs(V.cylinderTopY - V.headBottomY) * 0.6;
  }

  // 中心已由"夹到 x≤0 的包围盒"给出，不再额外偏置
  const t = center.clone();

  useCam(wantOrtho ? orthoCam : perspCam);

  if (wantOrtho) {
    /* 正交：视锥直接开到刚好包住投影。
       halfW/halfH 的单位是"整幅画布"的毫米半宽/半高，模型只填在可见带
       （effW × effH）里，所以要按 w/effW、h/effH 放大，模型才会真正顶满看得见的那块；
       再按画布纵横比补齐另一边，保证不拉伸。 */
    const M = 1.06;                                        // 留 6% 边
    let halfW = maxU * M * (w / effW);
    let halfH = maxV * M * (h / effH);
    const aspect = w / h;
    if (halfW / halfH > aspect) halfH = halfW / aspect;
    else halfW = halfH * aspect;

    // 相机与目标点一起沿 -right 平移 → 模型在屏幕上右移，落在可见带正中
    t.addScaledVector(right, (name === 'top' ? 1 : -1) * bandShiftPx * ((2 * halfW) / w));

    const depth = maxDepth + Math.max(2000, maxV * 2);
    // The official plan is read from R to A. Mirror the top projection only;
    // model coordinates, hole positions and the underlying CAD stay unchanged.
    orthoCam.left = name === 'top' ? halfW : -halfW;
    orthoCam.right = name === 'top' ? -halfW : halfW;
    orthoCam.top = halfH;
    orthoCam.bottom = -halfH;
    orthoCam.near = 1;
    orthoCam.far = depth + maxDepth + 4000;
    orthoCam.zoom = 1;
    orthoCam.updateProjectionMatrix();
    // 注意：v 是 Vector3，不能写 v[0]（没有数字下标，取到 undefined 会让相机变 NaN）
    orthoCam.up.copy(upHint);
    orthoCam.position.copy(t).addScaledVector(v, depth);
    orthoCam.lookAt(t);
    controls.target.copy(t);
    controls.update();
    return;
  }

  /* 透视：按角点投影求距。 */
  let dist = 0;
  if (box) {
    const c = new THREE.Vector3();
    for (let i = 0; i < 8; i++) {
      c.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z);
      if (state.cutPrv && c.x > 0) c.x = 0;
      const p = c.sub(center);
      const depth = p.dot(v);                     // 该点到目标平面、朝相机方向的分量
      const need = Math.max(Math.abs(p.dot(right)) / tanH, Math.abs(p.dot(up)) / tanV) + depth;
      if (need > dist) dist = need;
    }
  }
  if (!(dist > 0)) dist = (V.cylinderTopY - V.headBottomY) * 1.6;
  dist *= 1.05;                                    // 留一点边

  // Shift the projection for side panels, keeping the orbit pivot at the model center.
  perspCam.setViewOffset(w, h, -bandShiftPx, 0, w, h);

  perspCam.up.copy(upHint);          // 与取景用的 up 提示保持一致，否则画面朝向与取景框不符
  perspCam.position.copy(t).addScaledVector(v, dist);
  controls.target.copy(t);
  controls.update();
}

function setView(name) {
  invalidateModel();
  state.view = name;                  // 记住当前视角，剖切开关要用它重新构图
  syncTopPlateOverlay();
  // 正交对齐（正视/侧视/俯视）才压淡封头；轴测/适配/自动旋转不算正交
  state.ortho = ['front', 'back', 'left', 'side', 'top', 'bottom'].includes(name);
  if (state.mode === 'assembly') {
    setAsmView(name);
    applyDomeOpacity();
    updateOverlay();
    syncSelectedTubeHighlight();
    invalidateModel();
    return;
  }

  /* 接口详图/整管/管座这几个是近距离观察模式，一律用透视相机。
     从正交视图切过来时必须把相机换回去，否则会带着正交视锥渲染（画面不缩放、不动）。 */
  useCam(perspCam);
  perspCam.clearViewOffset();
  // 复位 up：俯视会把 up 改成 (0,0,-1)，切回这些同样用 lookAt 的视图必须还原，否则画面是歪的
  perspCam.up.set(0, 1, 0);
  if (name === 'top') perspCam.up.set(0, 0, -1);
  if (name === 'bottom') perspCam.up.set(0, 0, 1);
  camera = perspCam;
  if (Math.abs(perspCam.fov - 38) > 0.01) { perspCam.fov = 38; perspCam.updateProjectionMatrix(); }
  const L = state.L;
  const t = new THREE.Vector3();
  const d = { joint: 340, full: 1, socket: 210 }[state.mode] || 340;
  if (state.mode === 'full') {
    t.set(0, L / 2, 0);
    const dist = L * 2.0;
    const dirs = {
      iso: [0.45, 0.12, 0.45], front: [0, 0, 1], side: [1, 0, 0],
      back: [0, 0, -1], left: [-1, 0, 0], bottom: [0, -1, 0],
      top: [0, 1, 0], fit: [0.45, 0.12, 0.45],
    };
    const v = normDir(dirs[name] || dirs.iso);
    camera.position.set(v[0] * dist, t.y + v[1] * dist, v[2] * dist);
    controls.target.copy(t);
  } else if (state.mode === 'socket') {
    t.set(0, 66, 0);
    const dist = 330;
    const dirs = { iso: [0.6, 0.35, 0.7], front: [0, 0, 1], back: [0, 0, -1], left: [-1, 0, 0], side: [1, 0, 0], top: [0, 1, 0], bottom: [0, -1, 0], fit: [0.6, 0.35, 0.7] };
    const v = normDir(dirs[name] || dirs.iso);
    camera.position.set(v[0] * dist, t.y + v[1] * dist, v[2] * dist);
    controls.target.copy(t);
  } else {
    t.set(0, 52, 0);
    const dist = 430;
    const dirs = { iso: [0.55, 0.38, 0.74], front: [0, 0, 1], back: [0, 0, -1], left: [-1, 0, 0], side: [1, 0, 0], top: [0, 1, 0], bottom: [0, -1, 0], fit: [0.55, 0.38, 0.74] };
    const v = dirs[name] || dirs.iso;
    camera.position.set(v[0] * dist, t.y + v[1] * dist, v[2] * dist);
    controls.target.copy(t);
  }
  controls.update();
  updateOverlay();
  applyDomeOpacity();
  syncSelectedTubeHighlight();
  invalidateModel();
}

/* 正交视图（正视/侧视/俯视）下的"减遮挡"处理。
 * 两处要压：
 *   1) 封头半球壳 —— 俯视时是块大圆盘，会把 96 个格位的圆点阵列糊掉，0.26 → 0.07。
 *   2) 支承板 / 二次格架 —— 两块 0.42 的白板上下叠着，俯视看下去比封头更致命：
 *      孔位透不出来，整屏就是一片灰。0.42 → 0.13，孔洞的暗点阵列才能显形。
 * 轴测/适配/自动旋转/自由旋转时都恢复设计基准值（0.26 / 0.42）。
 * 只改材质 opacity，不重建材质、不动 #optDome 与 #optStruct 的显隐语义、
 * 不碰 depthWrite:false / transparent:true / DoubleSide，也不碰"不参与拾取/不参与取景"的保护。 */
const PLATE_OPACITY = { on: 0.42, ortho: 0.13 };
function applyDomeOpacity() {
  if (asmG.dome) asmG.dome.material.opacity = state.ortho ? 0.07 : 0.26;
  // structG 是 buildAssembly 的局部量，对外只挂在 asmG.struct 上
  const sg = asmG.struct;
  if (!sg) return;
  sg.traverse((o) => {
    if (o.isMesh && o.material && o.userData && o.userData.kind === 'structure') {
      o.material.opacity = state.ortho ? PLATE_OPACITY.ortho : PLATE_OPACITY.on;
    }
  });
}

function setMode(m) {
  if (!['assembly', 'joint', 'full', 'socket'].includes(m)) return;
  state.mode = m;
  if (m !== 'assembly') {
    asmSelected = -1;
    asmSelectedSet.clear();
    applyTubeColor();
  }
  syncTopPlateOverlay();
  document.querySelectorAll('#modeSeg button').forEach((b) => {
    b.classList.toggle('on', b.dataset.mode === m);
    b.setAttribute('aria-pressed', String(b.dataset.mode === m));
  });

  $('right').classList.add('hide');
  if (m === 'socket' && !state.cut) { state.cut = true; $('optCut').checked = true; applyCut(); }
  if (m === 'full' && !state.fat) {
    state.fat = true;
    state.fatAuto = true;
    $('optFat').checked = true;
    if (tubeMesh) { tubeMesh.scale.set(4, 1, 4); buildStations(); }
  }

  const isAsm = m === 'assembly';
  if (isAsm && !asmRoot) buildVesselScene();
  // 整体尺度下 Φ8.6 只有 3 px 宽，管束会淹没在包络里；自动加粗到 ×3 只改视觉
  if (isAsm && !state.fat) {
    state.fat = true; state.fatAuto = true; $('optFat').checked = true; applyTubeInstances();
  } else if (!isAsm && state.fatAuto && m !== 'full') {
    state.fat = false; state.fatAuto = false; $('optFat').checked = false;
    if (tubeMesh) tubeMesh.scale.set(1, 1, 1);
    applyTubeInstances();
  }
  root.visible = !isAsm;                       // 单件与整体互斥
  if (asmRoot) {
    asmRoot.visible = isAsm;
    if (isAsm) applyAsmVisibility();
  }
  $('asmGrp').style.display = isAsm ? '' : 'none';
  /* 整体布置模式下，这几项只作用于单件 root（尺寸标注 / P1–P6 标记 / 环境件半透明 / 轴线 / 爆炸位移
     都是单件的子对象），点了画面一动不动——用户会当成"软件坏了"。置灰比无声无息好。
     整体剖切另有 optCutPrv，所以「剖切」组的 optCut/cutSlider 在整体模式下也一并置灰。 */
  for (const id of ['optDims', 'optStations', 'optGhost', 'optAxis', 'optCut', 'cutSlider', 'exSlider']) {
    const el = $(id);
    if (!el) continue;
    el.disabled = isAsm;
    (el.closest('.chk') || el).classList.toggle('na', isAsm);
  }
  ensureFit(null, false);          // 模式切换会显隐「整体布置」组，栏高变了要让位
  setView('fit');
  if (!isAsm) {
    if (state.channel) rebuildTube();
    buildStations();
    applyCut();
  }
  renderScale();
  syncSelectedTubeHighlight();
  updateOverlay();
  invalidateModel();
}

/* 整体模式的总览信息卡 */
function showAsmOverview() {
  if (!vessel) return;
  $('infoName').textContent = '整体布置 · 50 指套管';
  $('infoTags').innerHTML = '<span class="tag">实测管长</span><span class="tag">球面拟合</span>';
  const colsAll = (vessel.structure && vessel.structure.columns) || [];
  const cntType = (t) => colsAll.filter((c) => c.type === t).length;
  const rows = [
    ['管位', '50 根（48 仪表套管 + 2 空心支承柱）'],
    ['堆芯支承柱', (cntType('core-hollow') + cntType('core-solid')) + ' 根'],
    ['管长范围', '2694.1 – 3287.7 mm'],
  ];
  $('infoTable').innerHTML = rows.map(function (r) { return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>'; }).join('');
  $('infoNote').textContent = '下封头按实测管长拟合；筒体与下部支承仅作示意，不作尺寸依据。';
  $('right').classList.remove('hide');
  syncAuxiliaryPanels();
}

/* 整体模式里点到 PRV / 支承结构 / 支承柱时的说明 */
function showAsmInfo(ud) {
  const V = vessel.vessel;
  const S = vessel.structure;
  const rowsOf = (pairs) => pairs.map(function (r) {
    return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td></tr>';
  }).join('');

  $('infoName').textContent = ud.cn || ud.id;

  if (ud.kind === 'column') {
    const c = ud.col || {};
    const g = ud.grp || {};
    $('infoTags').innerHTML = '<span class="tag">支承柱</span><span class="tag">示意尺寸</span>';
    const rows = [
      ['类型', ud.cn || c.cn],
      ['布置环半径', 'R = ' + (c.ring || 0).toFixed(0) + ' mm'],
      ['柱外径', 'Φ' + (c.od || 0).toFixed(1) + ' mm'],
      ['柱顶高程', 'Y = ' + (c.yTop || 0).toFixed(1) + ' mm'],
      ['柱底高程', 'Y = ' + (c.yBottom || 0).toFixed(1) + ' mm'],
      ['全长', (g.length || 0).toFixed(0) + ' mm'],
      ['落点方式', g.landing === 'through-head' ? '穿过封头壁，末端露出外壁' : '落在封头内壁'],
      ['与最近管净距', c.clearToTube != null ? c.clearToTube.toFixed(1) + ' mm' : '—'],
      ['位号', c.pos || '—'],
    ];
    if (c.bore != null) {
      // 空心柱：core-hollow 同轴套在指套管外、sec-hollow 为二次支承柱，列出内孔
      rows.push(['内孔', 'Φ' + (c.bore || 0).toFixed(2) + ' mm']);
    }
    $('infoTable').innerHTML = rowsOf(rows);
    $('infoNote').textContent =
      '环半径与柱径为按参考图 AAX44226000 的相对关系取的示意值；柱底高程由封头球面方程在其实半径处解出，'
      + '因此柱脚必然贴合封头。布置时已核算与 50 根管的净距，见 vessel_layout.json 的 clearanceAudit。';
    $('right').classList.remove('hide');
    return;
  }

  if (ud.kind === 'tie') {
    $('infoTags').innerHTML = '<span class="tag">支承结构</span><span class="tag">示意尺寸</span>';
    $('infoTable').innerHTML = rowsOf([
      ['构件', '环向联系梁'],
      ['高程', 'Y = ' + (ud.tie?.y || 0).toFixed(1) + ' mm'],
      ['截面', '圆杆 Φ' + (ud.tie?.od || 40).toFixed(0) + ' mm'],
      ['与最近管净距', (ud.tie?.ringClearToTube ?? ud.tie?.clearToTube ?? 0).toFixed(1) + ' mm'],
    ]);
    $('infoNote').textContent = '连接同环上带延长段支承柱的收口，约束柱身中部。整圈可拉通时画整圈，否则退化为弦段。';
    $('right').classList.remove('hide');
    return;
  }

  $('infoTags').innerHTML = '<span class="tag">示意包络</span>';
  const rows = ud.kind === 'vessel' ? [
    ['类型', '反应堆压力容器'],
    ['外球面', 'Rs = ' + V.outerRadius.toFixed(1) + ' mm'],
    ['内径', 'Φ' + V.publicInnerDiameter.toFixed(0) + ' mm'],
    ['壁厚', V.wall.toFixed(1) + ' mm'],
    ['封头最低点', 'Y = ' + V.headBottomY.toFixed(1) + ' mm'],
  ] : [
    ['类型', '下部堆芯支承结构'],
    ['堆芯支承板', 'Y = ' + S.ucsPlate.y.toFixed(1) + ' mm（厚 ' + S.ucsPlate.thickness + '）'],
    ['二次支承板', 'Y = ' + S.secondaryGrid.y.toFixed(1) + ' mm（厚 ' + S.secondaryGrid.thickness + '）'],
    ['支承柱', S.columns.length + ' 根 / ' + S.columnGroups.length + ' 类'],
  ];
  (S.columnGroups || []).forEach(function (g) {
    // 真实数据按类型分组、未必带 ring；缺省时只显示根数与柱径，避免 toFixed 抛错
    const ringTxt = (g.ring != null) ? ('R' + g.ring.toFixed(0) + ' · ') : '';
    rows.push([g.cn, g.count + ' 根 · ' + ringTxt + 'Φ' + ((g.od || 0).toFixed(1))]);
  });
  $('infoTable').innerHTML = rowsOf(rows);
  $('infoNote').textContent = ud.kind === 'vessel'
    ? '外球面半径由 50 根管长反解，与公开内径 + 壁厚的量级自洽；筒体段长度与形状为示意。'
    : '资料中无下部堆芯支承结构尺寸，此处按参考总图 AAX44226000 的相对关系布置，仅供空间理解。';
  $('right').classList.remove('hide');
}

/* ================================================================ 整体布置
 * 50 根指套管 + 反应堆压力容器下封头 + 下部支承结构。
 *
 * 这套几何不是照着效果图摆的：
 *   50 根管的 P1→P6 长度与堆芯栅格半径强负相关（r = -0.974），由
 *     L = a + sqrt(Rs² - R²)
 *   反解出封头外球面 Rs = 2192.96 mm。反算后 50 根管顶落在同一高程面 ±6.8 mm 内，
 *   而 Rs - Φ3989/2 = 198.5 mm 又正好是 RPV 壁厚量级 —— 两条独立线索互相印证。
 *   生成过程见 02_几何生成/build_vessel_layout.py，结果带 status 字段标置信度。
 *
 *   管本体 / 管座(P02) / 贯穿管(P05) / 二次支承柱(P06) 均为已有几何的实例化，
 *   仅 PRV 筒体与支承结构是示意包络。
 */
let vessel = null;
let asmRoot = null;
const asmG = {};
// 四类支承柱配色（同属冷调但要一眼分开）。key 与 vessel_layout.json 的 columnGroups[].id 一致；
// 末尾兜底 COL_COLOR[t] || 0x8fa6bb，数据里冒出未知 type 也不会变黑。
const COL_COLOR = {
  'core-hollow': 0x5f87a8,  // 空心支承柱（A型）：沿用原 core 蓝
  'core-solid':  0x4f9d9d,  // 实心支承柱（B型）：青
  'sec-hollow':  0x8a7fb8,  // 空心二次支承柱：紫
  'sec-solid':   0x9fb4c9,  // 实心二次支承柱：浅板岩蓝
};
const asmInst = {};
let asmPickable = [];
let asmSelected = -1;
let asmSelectedSet = new Set();

function asmDispose() {
  if (!asmRoot) return;
  asmRoot.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material && o.material !== tubeMat && !capMatCache.has(o.material)) {
      if (o.material.map) o.material.map.dispose();
      o.material.dispose?.();
    }
  });
  scene.remove(asmRoot);
  asmRoot = null;
  asmPickable = [];
  Object.keys(asmG).forEach((k) => delete asmG[k]);
  Object.keys(asmInst).forEach((k) => delete asmInst[k]);
  asmSelected = -1;
  asmSelectedSet = new Set();
}

function partGeometry(id) {
  const p = model.parts.find((q) => q.id === id);
  if (!p) return null;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(p.positions, 3));
  if (p.normals && p.normals.length) geo.setAttribute('normal', new THREE.Float32BufferAttribute(p.normals, 3));
  else geo.computeVertexNormals();
  geo.setIndex(p.indices);
  return geo;
}

function makeLabelSprite(text, color, size, halo) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = 128;
  const ctx = cv.getContext('2d');
  ctx.font = 'bold 88px "Segoe UI", system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (halo) {
    ctx.lineWidth = 14;
    ctx.strokeStyle = halo;
    ctx.lineJoin = 'round';
    ctx.strokeText(text, 64, 70);
  }
  ctx.fillStyle = color;
  ctx.fillText(text, 64, 70);
  const tex = new THREE.CanvasTexture(cv);
  if ('colorSpace' in tex) tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sp.scale.setScalar(size);
  sp.renderOrder = 20;
  return sp;
}

/** XYZ 轴标：右下角 DOM/SVG 小徽标。用主相机的朝向来投影三根轴，不占用 3D 深度缓冲，
 *  也永远不会被半透明包络或管束挡住。 */
const AXIS_DEFS = [
  { d: [1, 0, 0], c: '#d0453e', t: 'X' },
  { d: [0, 1, 0], c: '#2e9c62', t: 'Y' },
  { d: [0, 0, 1], c: '#2b6fb8', t: 'Z' },
];
let axisG = null;
const axisNodes = [];
let axisKey = '';

function buildAxisGizmo() {
  const host = document.getElementById('axisGizmo');
  if (!host || axisG) return;
  const NS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(NS, 'svg');
  // 留出足够的内边距，保证轴端圆点和 X/Y/Z 标签在小尺寸容器中也不被裁切。
  svg.setAttribute('viewBox', '0 0 138 138');
  host.appendChild(svg);
  const cx = 69, cy = 69, R = 42;
  for (const a of AXIS_DEFS) {
    const g = document.createElementNS(NS, 'g');
    const stub = document.createElementNS(NS, 'line');
    stub.setAttribute('stroke', a.c);
    stub.setAttribute('stroke-width', '1.3');
    stub.setAttribute('stroke-dasharray', '2 3');
    stub.setAttribute('opacity', '.38');
    stub.setAttribute('stroke-linecap', 'round');
    const line = document.createElementNS(NS, 'line');
    line.setAttribute('stroke', a.c);
    line.setAttribute('stroke-width', '2.6');
    line.setAttribute('stroke-linecap', 'round');
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('r', '8');
    dot.setAttribute('fill', a.c);
    dot.setAttribute('stroke', '#ffffff');
    dot.setAttribute('stroke-width', '1.6');
    const txt = document.createElementNS(NS, 'text');
    txt.textContent = a.t;
    txt.setAttribute('fill', '#ffffff');
    txt.setAttribute('text-anchor', 'middle');
    txt.setAttribute('dominant-baseline', 'central');
    g.appendChild(stub);
    g.appendChild(line);
    g.appendChild(dot);
    g.appendChild(txt);
    svg.appendChild(g);
    axisNodes.push({ a, g, stub, line, dot, txt });
  }
  const hub = document.createElementNS(NS, 'circle');
  hub.setAttribute('cx', cx); hub.setAttribute('cy', cy); hub.setAttribute('r', '2.6');
  hub.setAttribute('fill', '#7b8ea6');
  svg.appendChild(hub);
  axisG = { svg, cx, cy, R };
}

const _axisQ = new THREE.Quaternion();
const _axisV = new THREE.Vector3();

function updateAxisGizmo() {
  const host = document.getElementById('axisGizmo');
  if (!host) return;
  const on = !!state.axes && state.mode === 'assembly';
  host.classList.toggle('off', !on);
  if (!on || !axisG) return;
  const mirrored = camera.isOrthographicCamera && camera.left > camera.right;
  const key = `${mirrored}|${camera.quaternion.toArray().map((v) => v.toFixed(3)).join()}`;
  if (key === axisKey) return;   // 相机没转就不重排 DOM
  axisKey = key;
  _axisQ.copy(camera.quaternion).invert();
  const list = axisNodes.map((n) => {
    _axisV.set(n.a.d[0], n.a.d[1], n.a.d[2]).applyQuaternion(_axisQ);
    return { n, x: axisG.cx + _axisV.x * axisG.R * (mirrored ? -1 : 1), y: axisG.cy - _axisV.y * axisG.R, z: _axisV.z };
  });
  list.sort((p, q) => p.z - q.z);        // 背离视线的最先画，靠前的盖住靠后的
  for (const { n, x, y } of list) {
    axisG.svg.appendChild(n.g);          // 重排即改变遮挡顺序
    n.line.setAttribute('x1', axisG.cx);
    n.line.setAttribute('y1', axisG.cy);
    n.line.setAttribute('x2', x.toFixed(1));
    n.line.setAttribute('y2', y.toFixed(1));
    n.stub.setAttribute('x1', axisG.cx);
    n.stub.setAttribute('y1', axisG.cy);
    n.stub.setAttribute('x2', (axisG.cx - (x - axisG.cx) * 0.42).toFixed(1));
    n.stub.setAttribute('y2', (axisG.cy - (y - axisG.cy) * 0.42).toFixed(1));
    n.dot.setAttribute('cx', x.toFixed(1));
    n.dot.setAttribute('cy', y.toFixed(1));
    n.txt.setAttribute('x', x.toFixed(1));
    n.txt.setAttribute('y', (y + 0.5).toFixed(1));
  }
  const bounds = axisG.svg.getBBox();
  const size = Math.max(bounds.width, bounds.height) + 32;
  axisG.svg.setAttribute('viewBox', `${bounds.x + bounds.width / 2 - size / 2} ${bounds.y + bounds.height / 2 - size / 2} ${size} ${size}`);
}

/** PRV 包络剖面：外球面 → 筒体外壁 → 筒体内壁 → 内球面（闭合）。 */
function vesselProfile(Rs, Ri, yTop, segs) {
  const pts = [];
  for (let i = 0; i <= segs; i++) {
    const th = (i / segs) * Math.PI / 2;
    pts.push(new THREE.Vector2(Rs * Math.sin(th), -Rs * Math.cos(th)));
  }
  pts.push(new THREE.Vector2(Rs, yTop));
  pts.push(new THREE.Vector2(Ri, yTop));
  for (let i = segs; i >= 0; i--) {
    const th = (i / segs) * Math.PI / 2;
    pts.push(new THREE.Vector2(Ri * Math.sin(th), -Ri * Math.cos(th)));
  }
  return pts;
}

/** 带穿孔的连续圆板：外圆 - 每个通道/支承柱各一个圆孔，挤出到板厚。
 * 原来用 LatheGeometry 做的是实心环板，柱和管直接从板里穿过去 —— 板上没有孔，
 * 剖面里看就是"实心带"，与参考图的穿板画法不符。开孔后剖面才有孔间材料。
 *
 * ExtrudeGeometry 沿 +Z 挤，形状在 XY 平面。用 rotateX(+90°)：
 * 形状的 +y 映射到世界 +z（孔位不用翻坐标），挤出方向 +Z 映射到 -Y，
 * 所以板从 y=0 往下长，定位点取板顶高程 plate.y + thickness。
 */
function plateWithHoles(plate, holes) {
  const shp = new THREE.Shape();
  shp.absarc(0, 0, plate.outerR, 0, Math.PI * 2, false);
  let n = 0;
  for (const h of holes) {
    // 保留管位和柱位穿孔；中央空环已按用户要求补成连续板面。
    if (!(h.r > 0)) continue;
    if (Math.hypot(h.x, h.z) + h.r >= plate.outerR - 4) continue;
    const p = new THREE.Path();
    p.absarc(h.x, h.z, h.r, 0, Math.PI * 2, true);
    shp.holes.push(p);
    n++;
  }
  const geo = new THREE.ExtrudeGeometry(shp, {
    depth: plate.thickness, bevelEnabled: false, curveSegments: 20,
  });
  geo.rotateX(Math.PI / 2);
  geo.userData = { holeCount: n };
  return geo;
}

function buildVesselScene() {
  asmDispose();
  if (!vessel) return;

  asmRoot = new THREE.Group();
  asmRoot.name = 'vesselScene';
  scene.add(asmRoot);

  const V = vessel.vessel;
  const S = vessel.structure;
  const chans = vessel.channels;

  /* ---------------- PRV 包络 ---------------- */
  const prvMat = new THREE.MeshStandardMaterial({
    color: 0x9db4c9, metalness: 0.45, roughness: 0.5,
    side: THREE.DoubleSide, transparent: true, opacity: 0.085, depthWrite: false,
  });
  const prvGeo = new THREE.LatheGeometry(vesselProfile(V.outerRadius, V.innerRadius, V.cylinderTopY, 36), 96);
  const prv = new THREE.Mesh(prvGeo, prvMat);
  prv.userData = { id: 'PRV', cn: '反应堆压力容器（示意包络）', kind: 'vessel', asm: true };
  prv.renderOrder = -1;
  asmRoot.add(prv);
  asmG.prv = prv;

  // 轮廓线：半透明面上加一层稀疏母线，让球壳的曲率读得出来。
  // 内外两层壳一起出线会糊成一张网（远看全是灰噪点），所以透明度压到 0.18、颜色提亮。
  const wireGeo = new THREE.LatheGeometry(vesselProfile(V.outerRadius, V.innerRadius, V.cylinderTopY, 18), 36);
  const wire = new THREE.LineSegments(
    new THREE.WireframeGeometry(wireGeo),
    new THREE.LineBasicMaterial({ color: 0x9fb8cf, transparent: true, opacity: 0.18 })
  );
  wire.renderOrder = -1;
  asmRoot.add(wire);
  asmG.prvWire = wire;
  wireGeo.dispose();

  /* ---------------- RPV 下封头（半球形封头，真实 STL 网格）----------------
   * 与上方示意包络不同：这是按 50 根实测管长反解球面（球心 y=-1118.77、内半径 2191.77）
   * 精确三角化的下封头（含 200mm 短筒体），半透明叠加在包络内侧，给出真实的封头壳形。
   * 约束：
   *   - 只在整体布置模式出现（本 mesh 挂在 asmRoot 下，非 assembly 模式 asmRoot 整体隐藏）；
   *   - 不参与点选：raycast 置空，绝不挡住点选通道；
   *   - 不参与取景 bbox：asmBoundingBox() 跳过它，否则画面被拉远、50 根管子变小；
   *   - 跟随整体剖切：applyPrvCut() 遍历 asmRoot 会把同一裁剪平面铺到本材质。 */
  if (domeData && domeData.positions && domeData.indices) {
    const dGeo = new THREE.BufferGeometry();
    dGeo.setAttribute('position', new THREE.Float32BufferAttribute(domeData.positions, 3));
    dGeo.setAttribute('normal', new THREE.Float32BufferAttribute(domeData.normals, 3));
    dGeo.setIndex(domeData.indices);
    const dMat = new THREE.MeshStandardMaterial({
      color: 0x8aa0bd,            // 偏冷灰蓝
      metalness: 0.25, roughness: 0.72,
      side: THREE.DoubleSide, transparent: true, opacity: 0.26, depthWrite: false,
    });
    const dome = new THREE.Mesh(dGeo, dMat);
    dome.name = 'RPV_DOME';
    dome.userData = { id: 'RPV_DOME', cn: 'RPV 下封头（半球形封头）', kind: 'dome', asm: false };
    dome.renderOrder = 0;
    dome.visible = !!state.dome;
    dome.raycast = () => {};       // 屏蔽拾取
    asmRoot.add(dome);
    asmG.dome = dome;
  }

  /* ---------------- 下部支承结构（示意）----------------
   * 三类支承柱按参考图 AAX44226000 的下段收尾方式区分：
   *   堆芯支承柱     等径柱 + 底部垫脚，落在封头内壁
   *   十字支承柱     下段改为十字形截面（四片翼板），穿壁后露出外壁
   *   带延长段支承柱   柱体在高程处收口（带环向联系梁），再由细延长段落到内壁
   * 环半径/根数/柱径为示意值，但落点高程由封头球面方程在各自半径处解出。
   */
  const structG = new THREE.Group();
  const plateMat = new THREE.MeshStandardMaterial({
    color: 0x8fa3b8, metalness: 0.5, roughness: 0.6,
    // 0.42：孔按真实 Φ12.7 开之后，板再"近乎透明"就完全读不出穿孔了 —— 孔只有 6.35 半径，
    // 靠的是"孔位透出下方深色"形成暗点阵列。太透（<0.34）孔消失，太实（>0.55）下半部糊成一片灰。
    side: THREE.DoubleSide, transparent: true, opacity: 0.42, depthWrite: false,
  });

  // 穿孔清单：每个通道一孔（套管穿孔）；支承柱只把 core-* 加进板孔，sec-* 在板下方不开孔。
  // 按 (x,z) 归并、同位置取最大半径——22 根 core-hollow 与所在通道同轴，否则同位置双孔会让
  // plateWithHoles 的 Shape+holes 三角化失败 / 出破面。归并后唯一孔位 = 50 通道 + 46 实心柱位 = 96。
  const PEN = S.platePenetration || { tubeHoleRadius: 6.35, columnHoleClearance: 6.0 };
  const holeMap = new Map();
  const addHole = (x, z, r) => {
    const k = x.toFixed(3) + ',' + z.toFixed(3);
    const prev = holeMap.get(k);
    if (!prev || r > prev.r) holeMap.set(k, { x, z, r });
  };
  for (const c of chans) addHole(c.x, c.z, PEN.tubeHoleRadius);
  for (const c of (S.columns || [])) {
    if (!c.type || c.type.indexOf('core') !== 0) continue;   // 仅堆芯支承柱（core-*）开孔
    addHole(c.x, c.z, c.od / 2 + (PEN.columnHoleClearance || 6.0));
  }
  const plateHoles = Array.from(holeMap.values());
  console.log('plate holes = ' + plateHoles.length);

  asmG.plateHoles = 0;
  for (const plate of [S.ucsPlate, S.secondaryGrid]) {
    const geo = plateWithHoles(plate, plateHoles);
    asmG.plateHoles += (geo.userData.holeCount || 0);
    const m = new THREE.Mesh(geo, plateMat);
    m.position.y = plate.y + plate.thickness;   // 挤出朝 -Y，从板顶往下长
    m.userData = {
      id: 'UCS', cn: '下部堆芯支承结构（示意）', kind: 'structure', asm: true,
      plate: plate, holes: geo.userData.holeCount,
    };
    structG.add(m);
  }

  // 四类柱配色见模块级 COL_COLOR（key 与 columnGroups[].id 一致，含兜底）
  const colMatCache = {};
  const colMat = (t) => colMatCache[t] || (colMatCache[t] = new THREE.MeshStandardMaterial({
    color: COL_COLOR[t] || 0x8fa6bb, metalness: 0.58, roughness: 0.44,
    transparent: true, opacity: 0.92,
  }));
  const grpById = {};
  for (const g of (S.columnGroups || [])) grpById[g.id] = g;

  let tieMatCache = null;
  const matTie = () => tieMatCache || (tieMatCache = new THREE.MeshStandardMaterial({
    color: 0x8ea5ba, metalness: 0.7, roughness: 0.4, transparent: true, opacity: 0.9,
  }));

  // crossGeo 暂留：另一脚本仍在演进，停止调用但保留避免那个人改到一半引用不到。
  function crossGeo(armR, bladeHW, len) {
    const p = [
      [armR, bladeHW], [bladeHW, bladeHW], [bladeHW, armR], [-bladeHW, armR],
      [-bladeHW, bladeHW], [-armR, bladeHW], [-armR, -bladeHW], [-bladeHW, -bladeHW],
      [-bladeHW, -armR], [bladeHW, -armR], [bladeHW, -bladeHW], [armR, -bladeHW],
    ];
    const shp = new THREE.Shape();
    shp.moveTo(p[0][0], p[0][1]);
    for (let i = 1; i < p.length; i++) shp.lineTo(p[i][0], p[i][1]);
    shp.closePath();
    const geo = new THREE.ExtrudeGeometry(shp, { depth: len, bevelEnabled: false, curveSegments: 1 });
    geo.rotateX(-Math.PI / 2);      // 挤出方向 +Z → +Y
    return geo;
  }

  // 四类柱：core-* 穿过堆芯支承板（core-hollow 同轴套在指套管外），sec-* 在板下方。
  // 轴向一律用 c.yTop / c.yBottom（不再读 yCollar / yExtBottom 等旧字段）。
  // 旧的示意附加件（十字翼板、延长段/凸缘/垫脚、联系梁）新数据里没有，停止生成。
  const cols = S.columns || [];
  const colByType = {};   // type -> [mesh,...]，供图例点击切换显隐
  for (const c of cols) {
    const g = grpById[c.type] || {};
    const mat = colMat(c.type);
    const baseUD = {
      id: 'COL', cn: c.cn, kind: 'column', asm: true,
      col: c, grp: g,
    };
    const vis = state.colVis[c.type] !== false;   // 图例可切换显隐
    const reg = (m) => { (colByType[c.type] = colByType[c.type] || []).push(m); return m; };
    const addCyl = (dia, y0, y1, extraUD) => {
      const h = Math.abs(y1 - y0);
      if (h < 0.5) return null;
      const m = new THREE.Mesh(new THREE.CylinderGeometry(dia / 2, dia / 2, h, 18), mat);
      m.position.set(c.x, (y0 + y1) / 2, c.z);
      m.userData = Object.assign({}, baseUD, extraUD || {});
      m.visible = vis;
      structG.add(m);
      return reg(m);
    };
    // 空心柱：外筒 + 内孔，用 openEnded 圆柱套内层（沿用 CylinderGeometry，不另造几何）。
    const addHollowCyl = (od, bore, y0, y1, extraUD) => {
      const h = Math.abs(y1 - y0);
      if (h < 0.5) return null;
      const outer = new THREE.Mesh(new THREE.CylinderGeometry(od / 2, od / 2, h, 18, 1, true), mat);
      outer.position.set(c.x, (y0 + y1) / 2, c.z);
      outer.userData = Object.assign({}, baseUD, extraUD || {});
      outer.visible = vis;
      structG.add(outer);
      reg(outer);
      if (bore && bore > 0) {
        const inner = new THREE.Mesh(new THREE.CylinderGeometry(bore / 2, bore / 2, h, 18, 1, true), mat);
        inner.position.copy(outer.position);
        inner.userData = Object.assign({}, baseUD, extraUD || {}, { seg: 'bore' });
        inner.visible = vis;
        structG.add(inner);
        reg(inner);
      }
      return outer;
    };

    // 旧数据（core/cross/ext，无 bore 字段）按实心柱兜底，保证不报错
    const isHollow = c.bore != null || c.type === 'core-hollow' || c.type === 'sec-hollow';
    if (isHollow) {
      addHollowCyl(c.od, c.bore != null ? c.bore : null, c.yBottom, c.yTop);
    } else {
      addCyl(c.od, c.yBottom, c.yTop);
    }
  }
  asmG.colByType = colByType;

  // 环向联系梁（只在整圈都撞不到管时才画；否则退化为弦 / 不画，见生成脚本）
  const tie = S.tieRing || { mode: 'none' };
  if (tie.mode === 'ring') {
    const torus = new THREE.Mesh(
      new THREE.TorusGeometry(tie.ring, tie.od / 2, 8, 160),
      matTie()
    );
    torus.rotation.x = -Math.PI / 2;
    torus.position.y = tie.y;
    torus.userData = { id: 'TIE', cn: '环向联系梁（示意）', kind: 'tie', asm: true, tie: tie };
    structG.add(torus);
  } else if (tie.mode === 'chords') {
    for (const b of (tie.beams || [])) {
      if (!b.keep) continue;
      const dx = b.x2 - b.x1, dz = b.z2 - b.z1;
      const L = Math.hypot(dx, dz);
      const m = new THREE.Mesh(new THREE.CylinderGeometry(b.od / 2, b.od / 2, L, 12), matTie());
      m.position.set((b.x1 + b.x2) / 2, b.y, (b.z1 + b.z2) / 2);
      m.rotation.z = Math.PI / 2;
      m.rotation.y = -Math.atan2(dz, dx);
      m.userData = { id: 'TIE', cn: '环向联系梁（示意）', kind: 'tie', asm: true, tie: b };
      structG.add(m);
    }
  }

  asmRoot.add(structG);
  asmG.struct = structG;

  /* ---------------- 剖切封盖（x = 0 剖面）----------------
   * 裁切只是把 +X 半边裁掉，实体在剖口上是敞开的 —— 远看像一层壳。参考总图是实心剖面，
   * 所以这里按**已知几何直接画出剖口**，不做三角形-平面求交那一套切片算法：
   *   容器 = lathe 的母线多边形（左右镜像拼成一张闭合面）
   *   板   = x=0 平面与环带相交得到的两段矩形
   *   柱   = 被剖面穿过的柱，剖口宽 2√(r²−x²) 的矩形
   * 封盖只在剖切打开时显示，且不参与拾取、不参与"被裁网格"统计。 */
  const cutFaces = new THREE.Group();
  cutFaces.name = 'cutFaces';
  cutFaces.visible = false;
  {
    // 剖口用**钢灰**而不是浅灰：浅色场景里 0xb4c3d2 几乎和背景同色，剖口看着像一层白纸；
    // 压到 0x8496ab 后剖面"沉"下去，才有被切开的实体感。
    const matSteel = new THREE.MeshStandardMaterial({
      color: 0x8496ab, metalness: 0.28, roughness: 0.72, side: THREE.DoubleSide,
    });
    const matShaft = new THREE.MeshStandardMaterial({
      color: 0x6d8199, metalness: 0.26, roughness: 0.78, side: THREE.DoubleSide,
    });
    const EPS = -0.4;   // 往保留侧让 0.4 mm，避免与裁切边界共面打架

    const addShape = (shp, mat, info) => {
      const geo = new THREE.ShapeGeometry(shp, 24);
      geo.rotateY(Math.PI / 2);        // XY 面 → x = 0：(u, v) → (0, v, −u)
      geo.translate(EPS, 0, 0);
      const m = new THREE.Mesh(geo, mat);
      m.userData = { id: 'CUTCAP', cn: '剖面封盖', kind: 'cutcap', asm: true, cap: info };
      cutFaces.add(m);
      return m;
    };

    // 1) PRV 壁厚剖面：母线多边形 + 镜像
    const prof = vesselProfile(V.outerRadius, V.innerRadius, V.cylinderTopY, 36);
    if (prof && prof.length > 3) {
      const shp = new THREE.Shape();
      shp.moveTo(prof[0].x, prof[0].y);
      for (let i = 1; i < prof.length; i++) shp.lineTo(prof[i].x, prof[i].y);
      for (let i = prof.length - 2; i >= 0; i--) shp.lineTo(-prof[i].x, prof[i].y);
      shp.closePath();
      addShape(shp, matSteel, { what: 'PRV 壁厚剖面' });
    }

    // 2) 两块支承板：x=0 与环带相交 → 两段矩形（±z 各一段）
    for (const plate of [S.ucsPlate, S.secondaryGrid]) {
      if (!plate) continue;
      for (const sgn of [1, -1]) {
        const shp = new THREE.Shape();
        const u0 = sgn * plate.innerR, u1 = sgn * plate.outerR;
        shp.moveTo(u0, plate.y);
        shp.lineTo(u1, plate.y);
        shp.lineTo(u1, plate.y + plate.thickness);
        shp.lineTo(u0, plate.y + plate.thickness);
        shp.closePath();
        addShape(shp, matSteel, { what: '支承板剖面', y: plate.y });
      }
    }

    // 3) 被剖面穿过的柱
    let capCols = 0;
    for (const c of (S.columns || [])) {
      const r = c.effRadius || c.od / 2;
      const dx = Math.abs(c.x || 0);
      if (dx >= r - 1e-6) continue;
      const hw = Math.sqrt(r * r - dx * dx);
      if (!(c.yTop > c.yBottom)) continue;
      const z0 = c.z || 0;
      const shp = new THREE.Shape();
      shp.moveTo(z0 - hw, c.yBottom);
      shp.lineTo(z0 + hw, c.yBottom);
      shp.lineTo(z0 + hw, c.yTop);
      shp.lineTo(z0 - hw, c.yTop);
      shp.closePath();
      addShape(shp, matShaft, { what: '支承柱剖面', cn: c.cn, type: c.type, width: 2 * hw });
      capCols++;
    }
    asmG.cutCapColumns = capCols;
  }
  asmRoot.add(cutFaces);
  asmG.cutFaces = cutFaces;

  /* ---------------- 50 通道 ---------------- */
  const n = chans.length;
  const tubeOD = (model.geometry?.tube_od || 8.6) / 2;

  // 管本体：单位长度细柱，按 L 纵向缩放（整体视图中管径不足 1 px，球头不可见）
  const tGeo = new THREE.CylinderGeometry(tubeOD, tubeOD, 1, 10, 1, false);
  tGeo.translate(0, 0.5, 0);
  // 管身压到深蓝灰：外壳与板都是浅灰，管再用 0x7d93a9 就跟配角糊成一片，50 根管是这张图的主体。
  // metalness 从 0.85 降到 0.32 —— 浅色环境里高金属度会把环境反射成一片白，深色根本显不出来。
  const tMat = new THREE.MeshStandardMaterial({
    color: 0x4d6a89, metalness: 0.32, roughness: 0.42,
    emissive: 0x16232f, emissiveIntensity: 0.42,
  });
  const tubes = new THREE.InstancedMesh(tGeo, tMat, n);
  tubes.name = 'asmTubes';
  tubes.userData = { id: 'TUBES', cn: '指套管（50 根）', kind: 'tubes', asm: true };

  const seatGeo = partGeometry('P02');
  const pipeGeo = partGeometry('P05');
  const mkInst = (geo, color, metal, key) => {
    if (!geo) return null;
    const m = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({
      color, metalness: metal, roughness: 0.34, side: THREE.DoubleSide,
    }), n);
    m.userData = { id: key, cn: key, kind: 'part', asm: true };
    asmRoot.add(m);
    asmInst[key] = m;
    return m;
  };
  const seats = mkInst(seatGeo, 0x9dafc2, 0.8, 'P02');
  const pipes = mkInst(pipeGeo, 0xb9c7d4, 0.5, 'P05');
  /* P06 空心二次支承柱**不在这里铺**。
     图纸技术要求第 4 条是「48 根仪表套管 + 2 根空心二次支承柱 = 50」，也就是 50 个管位里
     只有 2 个是 P06；资料没标定是哪 2 个。早先把它按 50 个全实例化，结果 50 根 Φ89.9 的空心筒
     堆在管底，把管束糊成一堆粗柱 —— 板上"孔径按 Φ101.9 取"也是这个错误的连带。
     现在按「50 个管位全是 Φ8.6 仪表套管」建（P1–P6 表本身也不区分种类），
     P06 留待柱位确认后再单独放 2 个。见 vessel_layout.json → platePenetration.unknownChannelSection。 */
  const columns = null;

  const mtx = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const cWhite = new THREE.Color(1, 1, 1);
  for (let i = 0; i < n; i++) {
    const c = chans[i];
    mtx.compose(new THREE.Vector3(c.x, c.yBase, c.z), q, new THREE.Vector3(1, c.L, 1));
    tubes.setMatrixAt(i, mtx);
    tubes.setColorAt(i, cWhite);
    mtx.makeTranslation(c.x, c.yBase, c.z);
    if (seats) { seats.setMatrixAt(i, mtx); seats.setColorAt(i, cWhite); }
    if (pipes) { pipes.setMatrixAt(i, mtx); pipes.setColorAt(i, cWhite); }
    if (columns) { columns.setMatrixAt(i, mtx); columns.setColorAt(i, cWhite); }
  }
  [tubes, seats, pipes, columns].forEach((m) => {
    if (!m) return;
    m.instanceMatrix.needsUpdate = true;
    if (m.instanceColor) m.instanceColor.needsUpdate = true;
    m.frustumCulled = false;
  });
  asmRoot.add(tubes);
  asmInst.TUBES = tubes;
  asmG.tubes = tubes;

  /* ---------------- XYZ 坐标轴（右下角小视口） ---------------- */
  // 轴标放在屏幕右上角，不随模型平移/缩放；Y 轴也不再从管束正中穿过把画面劈成两半。
  buildAxisGizmo();

  asmPickable = [tubes, seats, pipes, columns, structG].filter(Boolean);

  applyTubeInstances();
  applyAsmVisibility();
  applyTubeColor();
  applyPrvCut();
}

/** 50 个实例的位姿：管按 L 纵向缩放，管径可选视觉加粗（不改数据）。 */
function applyTubeInstances() {
  if (!asmInst.TUBES || !vessel) return;
  const f = state.fat ? 3 : 1;
  const mtx = new THREE.Matrix4();
  const q = new THREE.Quaternion();
  const pos = new THREE.Vector3();
  const scl = new THREE.Vector3();
  const chans = vessel.channels;
  for (let i = 0; i < chans.length; i++) {
    const c = chans[i];
    pos.set(c.x, c.yBase, c.z);
    scl.set(f, c.L, f);
    mtx.compose(pos, q, scl);
    asmInst.TUBES.setMatrixAt(i, mtx);
    mtx.makeTranslation(c.x, c.yBase, c.z);
    for (const k of ['P02', 'P05', 'P06']) {
      if (asmInst[k]) asmInst[k].setMatrixAt(i, mtx);
    }
  }
  for (const k of ['TUBES', 'P02', 'P05', 'P06']) {
    const m = asmInst[k];
    if (!m) continue;
    m.instanceMatrix.needsUpdate = true;
    m.frustumCulled = false;
  }
}

/** 面板开关 → 可见性。 */
function applyAsmVisibility() {
  if (!asmRoot) return;
  if (asmG.prv) asmG.prv.visible = !!state.prv;
  if (asmG.prvWire) asmG.prvWire.visible = !!state.prv;
  if (asmG.dome) asmG.dome.visible = !!state.dome;
  if (asmG.struct) asmG.struct.visible = !!state.struct;
  // 轴标是 DOM 徽标（#axisGizmo），由 updateAxisGizmo() 每帧按 state.axes 显隐，不在这里管
  // P05 是每根指套管下端的贯穿管（Φ50.8 环境件），属于通道本身，不该被"下部支承结构"开关带走
  if (asmInst.P05) asmInst.P05.visible = !!state.penetrations;
  if (asmInst.P06) asmInst.P06.visible = !!state.penetrations;
  const lg = $('asmLegend');
  if (lg) lg.hidden = !state.struct;
}

/** 切换某一类支承柱的显隐（图例点击；沿用零件树显隐思路）。 */
function toggleColumnGroup(type) {
  const now = state.colVis[type] !== false;   // 当前是否可见
  const next = !now;
  state.colVis[type] = next;
  const arr = asmG.colByType && asmG.colByType[type];
  if (arr) for (const m of arr) m.visible = next;
}

/** 支承柱图例：按 columnGroups 动态生成，颜色与几何一致；点击可切换该类柱显隐。 */
function fillColumnLegend() {
  const groups = (vessel && vessel.structure && vessel.structure.columnGroups) || [];
  const box = $('asmLegend');
  if (!box) return;
  box.innerHTML = '';
  /* 图例用简称：2 列布局下每列只有约 118px，「空心支承柱（A型）」会把列宽撑爆、
     文字折成三行，四个图例就占掉三行高度。简称 + title 全名，一眼能认又不占地方。 */
  const COL_SHORT = {
    'core-hollow': '空心柱 A',
    'core-solid': '实心柱 B',
    'sec-hollow': '二次空心',
    'sec-solid': '二次实心',
  };
  for (const g of groups) {
    const col = COL_COLOR[g.id] || 0x8fa6bb;
    const hex = '#' + col.toString(16).padStart(6, '0');
    const span = document.createElement('span');
    span.innerHTML = '<i style="background:' + hex + '"></i>' + (COL_SHORT[g.id] || g.cn) + '<b>' + g.count + '</b>';
    span.style.cursor = 'pointer';
    span.title = g.cn + '　共 ' + g.count + ' 根　点击切换显隐';
    if (state.colVis[g.id] === false) span.style.opacity = '0.4';
    span.onclick = () => {
      toggleColumnGroup(g.id);
      span.style.opacity = state.colVis[g.id] === false ? '0.4' : '1';
    };
    box.appendChild(span);
  }
}

/** 型号图例：六类（Ⅰ–Ⅴ + 空心二次支承柱位），色块 + 型号 + 根数；
 *  点击某项 = 只显示该型号（其余管淡出保留空间感），再点一次取消筛选。
 *  数据直接取自 tube_specs.json，与「按型号着色」共用同一套色值，保证图例与三维一致。 */
function fillModelLegend() {
  const box = $('modelLegend');
  if (!box || !specs) return;
  box.innerHTML = '';
  const items = specs.models.map((m) => ({ type: m.type, cn: m.cn, count: m.count, color: m.color }));
  items.push({ type: '空心柱', cn: '空心柱位', count: specs.counts.hollowSecPos || 2, color: HOLLOW_COLOR });
  for (const it of items) {
    const span = document.createElement('span');
    span.dataset.type = it.type;
    span.innerHTML = '<i style="background:' + it.color + '"></i>' + it.cn + '<b>' + it.count + '</b>';
    span.style.cursor = 'pointer';
    span.title = '点击只显示「' + it.cn + '」（再点恢复全部）';
    span.onclick = () => toggleTypeFilter(it.type, span);
    box.appendChild(span);
  }
}

/** 型号图例点击：切换某一型号的筛选态，并同步图例高亮（选中项加粗高亮、其余淡出）。 */
function toggleTypeFilter(type, span) {
  // 再次点击同一项 = 取消筛选
  state.typeFilter = (state.typeFilter === type) ? null : type;
  const box = $('modelLegend');
  if (box) for (const s of box.children) {
    s.classList.toggle('on', !!state.typeFilter && s.dataset.type === state.typeFilter);
    s.classList.toggle('off', !!state.typeFilter && s.dataset.type !== state.typeFilter);
  }
  applyTubeColor();
  drawPlan();          // 平面图与 3D 共用同一套型号色，筛选后要一起重绘
}

/* 默认实例色；材质保持白色，避免选中色和维护状态色被蓝灰底色冲淡。 */
const TUBE_BASE_COLOR = 0x667c8c;
/* 型号筛选时，非目标型号退成的中灰。
   不能取太亮：#8d96a0 在白色基色 + 自发光下仍然发亮，跟目标型号抢视线，
   压到 #6b7480 才真正"退到背景"、又不会黑成一堆看不出是管子。 */
const TYPE_FADE_COLOR = '#6b7480';

/* 白色材质下可直接使用目标实例色，不需要反算颜色乘积。 */
function colorToInstance(col, target) {
  col.copy(target);
}

/* 检测数据着色：色阶阈值与颜色全部跟随主窗口「磨损分级」设置（localStorage thimbleSeverity*），
   缺省值与主窗口 severitySettings() 一致（低 #79b98c / 中 #e5a83b / 高 #df4b45），保证三个视图同口径。 */
function depthSeveritySetting(key, fallback, pattern) {
  let raw = null;
  try { raw = localStorage.getItem(key); } catch { raw = null; }
  if (pattern && /^#[0-9a-f]{6}$/i.test(raw || '')) return raw;
  const value = Number(raw ?? fallback);
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : fallback;
}
function depthSeverityPalette() {
  if(window.appSettings){
    const settings=window.appSettings.severity();
    return {mid:settings.midThreshold,high:settings.highThreshold,
      lowColor:settings.low,midColor:settings.mid,highColor:settings.high};
  }
  const mid = depthSeveritySetting('thimbleSeverityMidThreshold', 30);
  return {
    mid,
    high: Math.max(mid, depthSeveritySetting('thimbleSeverityHighThreshold', 50)),
    lowColor: depthSeveritySetting('thimbleSeverityLowColor', '#79b98c', true),
    midColor: depthSeveritySetting('thimbleSeverityMidColor', '#e5a83b', true),
    highColor: depthSeveritySetting('thimbleSeverityHighColor', '#df4b45', true),
  };
}
function depthSeverityColor(value, palette = depthSeverityPalette()) {
  if (value >= palette.high) return palette.highColor;
  if (value >= palette.mid) return palette.midColor;
  return palette.lowColor;
}
/* 有效缺陷深度：与主窗口 isEffectiveFinding 同口径 —— NDD/未标注不算，未量化不算。 */
function effectiveDepthPercent(row) {
  const indication = String(row.indication || '').trim().toUpperCase();
  const location = String(row.location_raw ?? row.location ?? '').trim();
  if (['NDD', 'NONE', 'NO DEFECT'].includes(indication)) return null;
  if (!indication && !location) return null;
  const value = Number(row.percent);
  return Number.isFinite(value) && value > 0 ? value : null;
}
/* 汇总当前检测范围：每根管的最大磨损深度（%）。rows 由缺陷层在 scope 变化时重载。 */
function depthOverlayData() {
  const byTube = new Map();
  for (const row of (window.__thimbleDefects?.rows || [])) {
    const tube = Number(row.thimble_id), value = effectiveDepthPercent(row);
    if (!Number.isInteger(tube) || value == null) continue;
    byTube.set(tube, Math.max(byTube.get(tube) || 0, value));
  }
  return byTube;
}
/* 通道位号 → 管号：按检测范围机组（奇数机取 serialOdd，偶数机取 serialEven）。 */
function depthTubeForChannel(channel, unit) {
  const serial = unit % 2 ? channel.serialOdd : channel.serialEven;
  const tube = Number(serial);
  return Number.isInteger(tube) ? tube : null;
}
/* 数据着色图例：三级色阶 + 无记录灰，阈值文案跟随磨损分级设置。 */
function syncDepthLegend() {
  const legend = $('depthLegend');
  if (!legend) return;
  const on = !!state.depthColor;
  legend.hidden = !on;
  const row = $('optDepthColorRow');
  if (row) row.hidden = !((window.__thimbleDefects?.rows || []).length || (window.__thimbleDefects?.dataState === 'loaded'));
  if (!on) return;
  const palette = depthSeverityPalette(), pct = value => `${Math.round(value)}%`;
  legend.innerHTML =
    `<span><i style="background:${palette.lowColor}"></i>&lt; ${pct(palette.mid)}</span>` +
    `<span><i style="background:${palette.midColor}"></i>${pct(palette.mid)} – ${pct(palette.high)}</span>` +
    `<span><i style="background:${palette.highColor}"></i>≥ ${pct(palette.high)}</span>` +
    `<span><i style="background:${TUBE_BASE_COLOR ? '#' + TUBE_BASE_COLOR.toString(16).padStart(6, '0') : '#667c8c'}"></i>无有效缺陷记录</span>`;
}

/** 按管长着色：短管偏冷、长管偏暖，直观看出球面分布。 */
function applyTubeColor() {
  const inst = asmInst.TUBES;
  if (!inst || !vessel) return;
  if (!inst.instanceColor) {           // 首次调用时惰性初始化
    const white = new THREE.Color(1, 1, 1);
    for (let i = 0; i < vessel.channels.length; i++) inst.setColorAt(i, white);
  }
  const n = vessel.channels.length;
  const Ls = vessel.channels.map((c) => c.L);
  const lo = Math.min(...Ls);
  const hi = Math.max(...Ls);

  // Instance colors carry selection; the shared material stays white.
  const tinting = !!(state.typeColor || state.lenColor || state.typeFilter || state.depthColor);
  inst.material.color.setHex(0xffffff);
  /* 材质本身是"金属管"参数（metalness 0.32 + 深蓝自发光 0.42），这套参数配蓝灰管身很好看，
     但配饱和的分类色会把色相冲淡、整体发亮，图例色块与实物对不上。
     着色时临时降金属度与自发光，让 instanceColor 尽量就是眼睛看到的颜色；不着色时原样恢复。 */
  inst.material.metalness = tinting ? 0.16 : 0.32;
  inst.material.emissiveIntensity = tinting ? 0.1 : 0.42;

  const col = new THREE.Color();
  const cFade = new THREE.Color(TYPE_FADE_COLOR);   // 预建，避免在 50 次循环里反复 new
  const cType = new THREE.Color();
  // 数据着色范围只算一次：最大磨损按管号汇总（rows 变化时会经 reference-defects-updated 重进本函数）
  const depthUnit = Number(window.__thimbleDefects?.scope?.unit || 1) || 1;
  const depthOverlays = state.depthColor ? depthOverlayData() : null;
  const depthPalette = state.depthColor ? depthSeverityPalette() : null;
  const cBase = new THREE.Color(TUBE_BASE_COLOR);
  for (let i = 0; i < n; i++) {
    const c = vessel.channels[i];
    if (state.mode === 'assembly' && asmSelectedSet.has(i)) {
      // Yellow denotes explicit selection only, never an unknown maintenance state.
      col.setHex(i === asmSelected ? 0xffb800 : 0xffd400);
      inst.setColorAt(i, col); continue;
    }
    // 型号筛选激活：不匹配的管淡出（保留空间感，便于在轴测图里看出该型号聚成一片），不隐藏
    if (state.typeFilter && c.type !== state.typeFilter) {
      colorToInstance(col, cFade);
      inst.setColorAt(i, col); continue;
    }
    // 数据着色优先于型号/管长着色：检测结论是当前任务焦点，模型分类色先让位
    if (depthOverlays) {
      const tube = depthTubeForChannel(c, depthUnit);
      const value = tube != null ? depthOverlays.get(tube) : null;
      if (value == null) colorToInstance(col, cBase);
      else col.set(depthSeverityColor(value, depthPalette));
      inst.setColorAt(i, col); continue;
    }
    if (state.typeColor) {             // 按型号着色：直接取 tube_specs.json 的色值（空心柱位统一灰）
      colorToInstance(col, cType.set(typeColorHex(c.type)));
      inst.setColorAt(i, col); continue;
    }
    if (!state.lenColor) { col.setHex(TUBE_BASE_COLOR); inst.setColorAt(i, col); continue; }
    const t = (c.L - lo) / (hi - lo || 1);
    // 冷蓝 → 青 → 暖橙
    col.setHSL(0.58 - 0.58 * t, 0.62, 0.55);
    inst.setColorAt(i, col);
  }
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  syncSelectedTubeHighlight();
}

let selectedTubeHighlight = null;
function syncSelectedTubeHighlight() {
  if (!asmInst.TUBES || !vessel) return;
  if (tubeMat) tubeMat.color.setHex(state.mode === 'assembly' && asmSelected >= 0 ? 0xffc400 : TUBE_BASE_COLOR);
  if (!selectedTubeHighlight) {
    selectedTubeHighlight = new THREE.Mesh(asmInst.TUBES.geometry,
      new THREE.MeshBasicMaterial({color:0xffc400,transparent:true,opacity:.9,depthTest:false,depthWrite:false,toneMapped:false}));
    selectedTubeHighlight.name = 'selected-tube-highlight';
    selectedTubeHighlight.raycast = () => {};
    selectedTubeHighlight.renderOrder = 6;
    scene.add(selectedTubeHighlight);
  }
  const channel = vessel.channels[asmSelected];
  selectedTubeHighlight.visible = Boolean(channel && state.mode === 'assembly' && asmInst.TUBES.visible !== false && (!state.cutPrv || channel.x <= 0));
  if (!channel) return;
  selectedTubeHighlight.position.set(channel.x,channel.yBase,channel.z);
  const scale = (state.fat ? 3 : 1) * 1.5;
  selectedTubeHighlight.scale.set(scale,channel.L,scale);
  selectedTubeHighlight.updateMatrixWorld();
}

/** 型号 → 着色色值：models[].color 优先，空心柱等未列型号回退到灰。 */
function typeColorHex(type) {
  return TYPE_COLOR[type] || HOLLOW_COLOR;
}

/** 剖开 PRV：切掉 x<0 的一半，内部管束直接可见。 */
/** 整体场景剖切：同一平面铺到 PRV + 管束 + 支承结构，出与参考总图同构的剖面。
 *  只切 PRV 的话看进去是"透视"，跟参考图的剖面对不上；全切之后柱与管都被剖开，
 *  十字柱的十字截面会直接露在剖面上，正是参考图画法。
 */
function applyPrvCut() {
  if (!asmRoot) return;
  const on = !!state.cutPrv;
  const planes = on ? [new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0)] : [];
  const seen = new Set();

  asmRoot.traverse((o) => {
    // 网格、实例网格、线框都要裁 —— 只裁网格的话，被切走那半边还留着一层线稿轮廓
    if (!o.material) return;
    if (o.userData && o.userData.kind === 'cutcap') return;   // 封盖本身就在剖面上，别裁它
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    for (const m of mats) {
      if (!m || seen.has(m)) continue;
      seen.add(m);
      if (m.userData.__side0 == null) m.userData.__side0 = m.side;
      m.clippingPlanes = planes;
      // 剖开时双面渲染，否则切面处看进去是空的；关掉时还原原来的 side
      if (!m.isLineBasicMaterial) m.side = on ? THREE.DoubleSide : m.userData.__side0;
      m.needsUpdate = true;
    }
  });

  if (asmG.prv) {
    // 剖切后是站在容器"里面"往外看，外壳再保持 0.42 就是一层乳白罩，压到 0.14 当背景
    asmG.prv.material.opacity = on ? 0.14 : 0.085;
    asmG.prv.material.depthWrite = on;
    asmG.prv.material.needsUpdate = true;
  }
  if (asmG.prvWire) asmG.prvWire.visible = state.prv;
  if (asmG.cutFaces) asmG.cutFaces.visible = on;   // 剖口封盖只在剖开时出现
}

/** 三维点选和管号浏览使用同一套选中状态。 */
function selectAsmChannel(i) {
  if (!vessel || i < 0 || i >= vessel.channels.length) return;
  // channelList 与 vessel.channels 不同序（一个按行列排、一个按生成序），只能按 pos 找
  const c = channelList.find((x) => x.pos === vessel.channels[i].pos) || vessel.channels[i];
  syncChannelSelection(c);
  rebuildTube();               // 整体模式下 root 是隐藏的，重建只为切回单件视图时管长已经是对的
  if (!$('right').classList.contains('hide')) showAsmChannelInfo(i);
}

/** 当前管子的关键信息；维护原文和来源在检测记录的折叠区中保留。 */
function showAsmChannelInfo(i, options = {}) {
  const layer = window.__thimbleDefects;
  const unit = Number(layer?.scope?.unit || 0);
  // The data layer can finish a focus request after the model selection
  // callback. Prefer its authoritative tube id when resolving the card so a
  // late event cannot repaint the previous tube's title.
  const focusedTube = Number(layer?.selectedTube);
  const focusedIndex = options.preferData !== false && unit && Number.isInteger(focusedTube) && focusedTube > 0
    ? vessel.channels.findIndex(channel => Number(unit) % 2 ? Number(channel.serialOdd) === focusedTube : Number(channel.serialEven) === focusedTube)
    : -1;
  if (focusedIndex >= 0) i = focusedIndex;
  const c = vessel.channels[i];
  const type = c.cn || (c.type === '空心柱' ? '空心二次支承柱位' : c.type) || '未分类';
  const tube = unit % 2 ? c.serialOdd : c.serialEven;
  $('infoName').textContent = unit ? `${tube} 号管 · 位置 ${c.pos}` : `位置 ${c.pos}`;
  const records = Array.isArray(layer?.rows) ? layer.rows.filter(row => Number(row.thimble_id) === Number(tube)) : [];
  const effective = layer?.stateForTube?.(tube);
  const stateKeys = [...new Set(records.filter(row => row.state_recorded !== 0 && row.state_recorded !== false)
    .map(row => String(row.state || '').trim().toLowerCase()).filter(Boolean))];
  const stateLabels = { normal: '正常', plugged: '堵管', shifted: '移位', replaced: '换管' };
  const stateText = stateKeys.map(key => stateLabels[key] || '管子状态待确认');
  if (!stateText.length && records.length) stateText.push(records.some(row => row.note) ? '管子状态待确认' : '管子状态未记录');
  const shifted = records.filter(row => String(row.state || '').trim().toLowerCase() === 'shifted');
  const offsets = [...new Set(shifted.map(row => row.offset_confirmed !== 0 && row.offset_confirmed !== false && row.offset_mm != null && row.offset_mm !== ''
    ? `${row.offset_mm} mm`
    : row.unsigned_offset_mm != null && row.unsigned_offset_mm !== '' ? `${row.unsigned_offset_mm} mm（方向未确认）` : '距离未注明'))];
  const stateTag = layer?.stateError ? '管子状态加载失败' : effective
    ? (effective.last_maintenance ? effective.state_label : '管子状态未记录')
    : stateText.length ? stateText.join('、') : layer?.dataState === 'loaded' ? '管子状态未记录' : '未选择检测大修';
  if (effective?.shifted && effective.cumulative_offset_mm != null) {
    offsets.splice(0, offsets.length, `${effective.cumulative_offset_mm} mm`);
  } else if (effective?.shifted && !offsets.length) {
    offsets.push('距离或方向待确认');
  }
  $('infoTags').replaceChildren();
  for (const [text, className] of [[type, 'tag'], [stateTag, 'tag state-tag']]) {
    const tag = document.createElement('span');
    tag.className = className;
    tag.textContent = text;
    $('infoTags').append(tag);
  }
  const depths = records.filter(row => String(row.indication).trim().toUpperCase() !== 'NDD'
    && row.percent != null && row.percent !== '' && Number.isFinite(Number(row.percent))).map(row => Number(row.percent));
  const rows = [
    ['管长', `${c.L.toFixed(1)} mm`],
    ['最大磨损', depths.length ? `${Math.max(...depths)}%` : records.some(row => String(row.indication).trim().toUpperCase() === 'NDD') ? 'NDD' : '待确认'],
  ];
  if (offsets.length) rows.push(['移位距离', offsets.join('、')]);
  $('infoTable').innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  $('infoNote').textContent = offsets.length && shifted.some(row => row.offset_confirmed === 0 || row.offset_confirmed === false || row.offset_mm == null)
    ? '移位方向或距离未确认，未修正模型位置。'
    : effective?.needs_review ? '管子状态或维护顺序待核对；请核对模型位置。'
    : records.length ? `${layer.scope.outage} · ${records.length} 条检测记录` : '当前范围无记录，不能判为无缺陷。';
  $('right').classList.remove('hide');
  syncAuxiliaryPanels();
}

function refreshOpenTubeDetails() {
  if (asmSelected >= 0 && !$('right').classList.contains('hide')) showAsmChannelInfo(asmSelected);
}

/* ----------------------------------------------------------------- 通道布局 */
const COL = 'ABCDEFGHJKLMNPR';
function posXY(pos) {
  const col = COL.indexOf(pos[0]);
  const row = parseInt(pos.slice(1), 10);
  return { x: col, y: row };
}

function buildChannelData() {
  // 编号以 vessel_layout.json 为准：它由 build_vessel_layout.py 生成，已应用源表勘误
  // （《指套管P1-P6距离.xlsx》把 1 号机 46 同时给了 H11 和 H1，H11 应为 11），
  // 并对两套编号做过 1–50 各一次的完整性自检。
  // p1p6_channels.json 是源表的原始抄录（保持原样便于追溯），只在 vessel 缺失时兜底 ——
  // 否则左栏会显示源表的误录值 46，和两张分布图上的 11 对不上。
  const list = [];
  if (vessel && Array.isArray(vessel.channels) && vessel.channels.length) {
    vessel.channels.forEach((c) => {
      /* 型号字段必须一起带过来：平面图按型号着色、信息卡显示规格，都读 channelList。
         早先这里只挑 pos/L/两套编号四个字段，结果 type 一直是 undefined，
         typeColorHex() 全部回退成灰 —— 平面图看起来"上了色"，其实一片灰。 */
      list.push({
        pos: c.pos, L: c.L,
        serialOdd: c.serialOdd ?? '', serialEven: c.serialEven ?? '',
        type: c.type ?? null, cn: c.cn ?? '',
        L1: c.L1 ?? null, L2: c.L2 ?? null, V: c.V ?? null,
      });
    });
  } else {
    // p1p6_channels.json 中 oddChannel/evenChannel 为通道序号，与 posCodes 一一对应
    channels.rows.forEach((r, idx) => {
      r.posCodes.forEach((pos, i) => {
        list.push({
          pos,
          L: r.p1p6_mm,
          row: idx,
          serialOdd: r.oddChannel[i] ?? '',
          serialEven: r.evenChannel[i] ?? '',
        });
      });
    });
  }
  const byPos = new Map();
  for (const c of list) if (!byPos.has(c.pos)) byPos.set(c.pos, c);
  return [...byPos.values()].sort((a, b) => {
    const A = posXY(a.pos), B = posXY(b.pos);
    return (A.y * 16 + A.x) - (B.y * 16 + B.x);
  });
}

let channelList = [];
function buildChannelUI() {
  channelList = buildChannelData();
}

/* 左栏通道布局图：照官方图 1-1「LOCATION OF FLUX THIMBLES」的纸面版式画，
   不再是一堆脱离图纸的散点 ——
     · 15 行 × 15 列方格，每行画几格按图纸逐行实测（3,7,9,11,13,13,15×4,13,13,11,9,7，共 169 格）；
     · 列字母 R→A 从左到右（A 在 0° 侧）、行号 01→15 自上而下；
     · 每个有管位的格子画一个圆，圆内一条竖线分左右：
       左半 = 奇数机组（Odd）通道号，右半 = 偶数机组（Even）通道号。
   两套编号互为置换、同一位置两个号几乎都不同（H1 = 46|32、H11 = 11|24），
   所以必须两个都写出来，只显示一套会认错管。
   格子边长 10 个 viewBox 单位，圆直径 8.5 单位 —— 圆几乎顶满格子，跟图纸一样。 */
const PLAN_ROW_SPAN = [3, 7, 9, 11, 13, 13, 15, 15, 15, 15, 13, 13, 11, 9, 7];
const PLAN_COLS_L2R = 'RPNMLKJHGFEDCBA';
const PLAN_CW = 10;      // 格子边长
const PLAN_GX = 12;      // 左侧留给行号
const PLAN_GY = 12;      // 顶部留给列字母
const PLAN_HINT = '悬停圆圈看两套编号 · 点击选中该通道';
const PLAN_R = 4.62;     // 圆半径（格子的 0.92，跟图纸一样圆几乎顶满格子）

let planCircles = [];

function syncPlanSel(c) {
  const pos = c && c.pos;
  planCircles.forEach((n) => n.classList.toggle('on', n.dataset.pos === pos));
}

function drawPlan() {
  const svg = $('plan');
  if (!svg) return;
  svg.innerHTML = '';
  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag, attrs, txt) => {
    const el = document.createElementNS(NS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (txt != null) el.textContent = txt;
    return el;
  };

  const GW = PLAN_CW * 15;
  svg.setAttribute('viewBox', `0 0 ${PLAN_GX + GW + 2} ${PLAN_GY + GW + 2}`);

  // 管长色阶：只做淡底 + 深描边（圈里要写两位数字，底色不能太重）
  const vals = channelList.map((c) => c.L);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const k = (v) => (v - mn) / (mx - mn || 1);
  const mix = (a, b, t) => Math.round(a + (b - a) * t);
  const fillOf = (v) => { const t = k(v); return `rgb(${mix(240, 176, t)},${mix(246, 206, t)},${mix(252, 234, t)})`; };
  const strokeOf = (v) => { const t = k(v); return `rgb(${mix(180, 32, t)},${mix(206, 101, t)},${mix(231, 170, t)})`; };

  /* 平面图跟随 3D 的着色模式：勾了「按型号着色」或点了型号图例筛选时，改按型号上色。
     为什么这里比 3D 更该有色：3D 里管子只有 Φ8.6，远景下每根占不到 2px，
     五色混在一起几乎分不出；平面图的每个位号是一个色块，型号分布一眼就能看出来。 */
  const typeMode = !!(state.typeColor || state.typeFilter);
  /* 「按检测数据着色」在平面图上最有读数价值：位号 → 管号 → 当前范围最大磨损，直接套三级色阶。
     无有效记录的位号用蓝灰淡底示意"数据未覆盖"，不与缺陷分级色混音。 */
  const depthMode = !!state.depthColor;
  const depthUnit = Number(window.__thimbleDefects?.scope?.unit || 1) || 1;
  const depthOverlays = depthMode ? depthOverlayData() : null;
  const NO_DATA_FILL = '#8d9aa4';
  const posStyle = (c) => {
    if (depthMode) {
      const tube = depthTubeForChannel(c, depthUnit);
      const value = tube != null ? depthOverlays.get(tube) : null;
      if (value == null) return { fill: NO_DATA_FILL + '40', stroke: NO_DATA_FILL, dim: false };
      const hex = depthSeverityColor(value);
      return { fill: hex + '99', stroke: hex, dim: false };
    }
    if (!typeMode) return { fill: fillOf(c.L), stroke: strokeOf(c.L), dim: false };
    const hex = typeColorHex(c.type);
    return {
      fill: hex + '66',                                            // 淡底：圈里还要写两位机组号
      stroke: hex,
      dim: !!state.typeFilter && c.type !== state.typeFilter,      // 非目标型号淡出，直接看出分布
    };
  };

  // 1) 方格 + 行号
  for (let r = 1; r <= 15; r++) {
    const w = PLAN_ROW_SPAN[r - 1];
    const start = (15 - w) / 2;
    for (let i = 0; i < w; i++) {
      svg.appendChild(mk('rect', {
        class: 'pl-grid',
        // 别忘了 start —— 少了它每行都会从左端顶格画，跟图纸的居中阶梯轮廓对不上
        x: PLAN_GX + (start + i) * PLAN_CW, y: PLAN_GY + (r - 1) * PLAN_CW,
        width: PLAN_CW, height: PLAN_CW,
      }));
    }
    svg.appendChild(mk('text', {
      class: 'pl-row',
      x: PLAN_GX - 2.8, y: PLAN_GY + (r - 0.5) * PLAN_CW + 1.75,
      'text-anchor': 'end',
    }, String(r).padStart(2, '0')));
  }

  // 2) 列字母
  for (let i = 0; i < 15; i++) {
    svg.appendChild(mk('text', {
      class: 'pl-col',
      x: PLAN_GX + (i + 0.5) * PLAN_CW, y: PLAN_GY - 3.6,
      'text-anchor': 'middle',
    }, PLAN_COLS_L2R[i]));
  }

  // 3) 50 个管位：圆 + 竖线 + 两个机组号
  planCircles = [];
  for (const c of channelList) {
    const col = PLAN_COLS_L2R.indexOf(c.pos[0]);
    const row = parseInt(c.pos.slice(1), 10);
    if (col < 0 || !(row >= 1 && row <= 15)) continue;
    const cx = PLAN_GX + (col + 0.5) * PLAN_CW;
    const cy = PLAN_GY + (row - 0.5) * PLAN_CW;

    const ps = posStyle(c);
    const circle = mk('circle', {
      cx, cy, r: PLAN_R,
      fill: ps.fill, stroke: ps.stroke,
      'data-pos': c.pos,
    });
    if (ps.dim) circle.setAttribute('opacity', '0.26');
    circle.appendChild(mk('title', {},
      `${c.pos}　${c.cn || ''}　奇数机组 #${c.serialOdd || '—'}　偶数机组 #${c.serialEven || '—'}　` +
      `P1→P6 ${c.L.toFixed(1)} mm` + (c.V != null ? `　规格长 ${c.V.toFixed(1)} mm` : '')));
    circle.addEventListener('click', () => selectChannel(c));
    // 数字在这个尺寸下必然很小，所以悬停时把这一格的完整读数打到图下面
    circle.addEventListener('mouseenter', () => {
      $('planHover').innerHTML =
        `<b>${c.pos}</b>　<span style="color:#153f63">奇数机组 #${c.serialOdd || '—'}</span>` +
        ` / <span style="color:#7a3712">偶数机组 #${c.serialEven || '—'}</span>` +
        `　${c.L.toFixed(1)} mm`;
    });
    circle.addEventListener('mouseleave', () => {
      $('planHover').textContent = PLAN_HINT;
    });
    svg.appendChild(circle);
    planCircles.push(circle);

    svg.appendChild(mk('line', {
      class: 'pl-div',
      x1: cx, y1: cy - PLAN_R * 0.93, x2: cx, y2: cy + PLAN_R * 0.93,
    }));
    svg.appendChild(mk('text', {
      class: 'pl-num pl-odd',
      x: cx - PLAN_R * 0.52, y: cy + 1.02, 'text-anchor': 'middle',
    }, c.serialOdd || ''));
    svg.appendChild(mk('text', {
      class: 'pl-num pl-even',
      x: cx + PLAN_R * 0.52, y: cy + 1.02, 'text-anchor': 'middle',
    }, c.serialEven || ''));
  }

  $('planLegend').textContent = `${mn.toFixed(0)} – ${mx.toFixed(0)}`;
  if (state.channel) syncPlanSel(state.channel);
  fitPlan();            // 平面图每重绘一次都要重新让位：内容是动态的，可用高度也可能刚变过
}

/** 按堆芯位置把三维整体布置里的同一根管点亮，返回 vessel.channels 下标（找不到返回 -1）。
 *  instanceId 是 vessel.channels 的下标，与 channelList 不同序，必须按 pos 对，不能按下标对。 */
function highlightAsmByPos(pos) {
  if (!vessel) return -1;
  const j = vessel.channels.findIndex((x) => x.pos === pos);
  asmSelected = j;
  asmSelectedSet = new Set(j >= 0 ? [j] : []);
  applyTubeColor();
  return j;
}

/** 同步当前管号、模型高亮和管板叠加。 */
function syncChannelSelection(c) {
  state.channel = c;
  state.L = c.L;
  syncPlanSel(c);
  const assemblyIndex = highlightAsmByPos(c.pos);
  syncTopPlateOverlay();
  if (referenceReady && !referenceSelectionSilent) {
    dispatchEvent(new CustomEvent('reference-channel-selected', {
      detail: { channel: c, position: c.pos, assemblyIndex, source: 'reference' },
    }));
  }
  return assemblyIndex;
}

function applyWorkspaceTubeSelection(tubes = []) {
  const unit = Number(window.__thimbleDefects?.scope?.unit || 0);
  const wanted = new Set((Array.isArray(tubes) ? tubes : []).map(Number).filter(Number.isInteger));
  asmSelectedSet = new Set();
  if (vessel && wanted.size) {
    vessel.channels.forEach((channel, index) => {
      const tube = unit % 2 ? Number(channel.serialOdd) : Number(channel.serialEven);
      if (wanted.has(tube)) asmSelectedSet.add(index);
    });
    if (asmSelectedSet.size && !asmSelectedSet.has(asmSelected)) asmSelected = [...asmSelectedSet][0];
  }
  if (!wanted.size) asmSelected = -1;
  applyTubeColor();
}

function selectChannel(c) {
  const j = syncChannelSelection(c);
  if (state.mode !== 'assembly') rebuildTube();
  if (state.mode === 'full') setView('fit');
  if (j >= 0 && !referenceSelectionSilent && state.mode === 'assembly' && !$('right').classList.contains('hide')) {
    showAsmChannelInfo(j);
  }
}

function rebuildTube() {
  if (!tubeMesh) return;
  tubeMesh.geometry.dispose();
  tubeMesh.geometry = buildTubeGeometry();
  buildStations();
  applyExplode();
  renderScale();
  updateOverlay();
  if (state.selected === 'P01') showInfo('P01');
}

/* ----------------------------------------------------------------- 交互 */
/* 细管吸附：整体布置下指套管外径 Φ8.6、容器 Φ4384，管子在屏幕上只有 1~3 px，
   纯射线点选基本点不中（必须像素级对准）。
   更要紧的是同轴的 22 根空心支承柱：柱内孔包着管，柱壁永远在管前面，
   按"取最近命中"的规矩，这 22 根管在三维里一辈子选不中。
   所以这里在屏幕空间找 6 px 内最近的管中心，命中即优先选管；
   柱的外环（离管心 > 6 px）仍按射线选柱，互不打架。 */
const TUBE_SNAP_PX = 6;
function nearestTubeOnScreen(px, py, rect) {
  const mesh = asmG.tubes;
  if (!mesh || !mesh.visible) return -1;
  const m = new THREE.Matrix4();
  const p = new THREE.Vector3(), q = new THREE.Quaternion(), s = new THREE.Vector3();
  const a = new THREE.Vector3(), b = new THREE.Vector3();
  const maxD = TUBE_SNAP_PX * TUBE_SNAP_PX;
  let minD = Infinity, minZ = Infinity, best = -1;
  /* 两轮：先找屏幕上最近的那根，再在"与最近者相差不到 1.5 px"的候选里取离相机近的。
     不做深度优先 —— 50 根管在正视下大量交叉，深度最优常常在几像素之外，
     会出现"点这根却选中旁边那根"。 */
  for (let i = 0; i < mesh.count; i++) {
    mesh.getMatrixAt(i, m);
    m.decompose(p, q, s);
    if (!s.y) continue;
    /* 必须按"整根管的投影线段"算距离，不能只投中点：
       斜视时管的上下端点横向差几十像素，只取中点会漏掉管身中下段。 */
    a.set(p.x, p.y, p.z).project(camera);
    b.set(p.x, p.y + s.y, p.z).project(camera);
    if (a.z > 1 && b.z > 1) continue;
    const ax = (a.x * 0.5 + 0.5) * rect.width, ay = (-a.y * 0.5 + 0.5) * rect.height;
    const bx = (b.x * 0.5 + 0.5) * rect.width, by = (-b.y * 0.5 + 0.5) * rect.height;
    const vx = bx - ax, vy = by - ay;
    const len2 = vx * vx + vy * vy;
    let t = len2 > 0 ? ((px - ax) * vx + (py - ay) * vy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    const ddx = ax + vx * t - px, ddy = ay + vy * t - py;
    const d = ddx * ddx + ddy * ddy;
    if (d > maxD) continue;
    const z = a.z + (b.z - a.z) * t;
    if (d < minD) { minD = d; minZ = z; best = i; }
    else if (d <= minD + 2.25 && z < minZ) { minZ = z; best = i; }
  }
  return best;
}

let down = null;
function onPointerDown(ev) {
  if (ev.button !== 0) return;
  down = { x: ev.clientX, y: ev.clientY, t: Date.now() };
  renderer.domElement.addEventListener('pointerup', onPointerUp, { once: true });
}
function onPointerUp(ev) {
  if (!down || ev.button !== 0) { down = null; return; }
  const origin = down;
  down = null;
  /* 只按位移判拖拽，不再看按住时长。
     原来有 `Date.now() - down.t > 600` 的硬超时：本机软件渲染一帧要 400~500 ms
     （无独显的办公机更慢），按下与抬起之间常被渲染卡过 600 ms，
     于是"点一下"被当成拖拽丢掉 —— 表现为点选时灵时不灵。 */
  const moved = Math.hypot(ev.clientX - origin.x, ev.clientY - origin.y);
  if (moved > 4) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const mouse = new THREE.Vector2(
    ((ev.clientX - rect.left) / rect.width) * 2 - 1,
    -((ev.clientY - rect.top) / rect.height) * 2 + 1
  );
  const ray = new THREE.Raycaster();
  ray.setFromCamera(mouse, camera);
  const isAsm = state.mode === 'assembly' && asmRoot;
  const clean = (arr) => arr.filter((h) => h.object.visible && (h.object.isMesh || h.object.isInstancedMesh));
  // 整体模式：半透明的 PRV 挡在最外面，先只打管束/管座/柱，打不到再退回包络
  let hits = clean(ray.intersectObjects(isAsm ? asmPickable : root.children, true));
  if (!hits.length && isAsm) hits = clean(ray.intersectObjects([asmRoot], true));
  const snapIdx = isAsm
    ? nearestTubeOnScreen(ev.clientX - rect.left, ev.clientY - rect.top, rect)
    : -1;
  // 管心 6 px 内一律给管：管是同轴空心柱的内孔件，按深度取永远轮不到它
  if (snapIdx >= 0) { selectAsmChannel(snapIdx); return; }
  if (hits.length) {
    // 半透明支承板不挡拾取：若后面还有柱/管，优先取那个
    const solid = hits.find((h) => h.instanceId != null
      || (h.object.userData && h.object.userData.kind !== 'structure'));
    const hit = solid || hits[0];
    const obj = hit.object;
    if (obj.userData?.asm) {
      // instanceId 在 intersection 上，不在 InstancedMesh 上
      if (hit.instanceId != null) selectAsmChannel(hit.instanceId);
      else showAsmInfo(obj.userData);
      return;
    }
    if (obj.userData?.station) {
      toast(`${obj.userData.station.id}：${obj.userData.station.desc}（${obj.userData.station.basis}）`);
      return;
    }
    const id = obj.name;
    document.querySelectorAll('#tree .item').forEach((n) => n.classList.toggle('sel', n.dataset.id === id));
    showInfo(id);
  }
}

let toastTimer;
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.dataset.error = String(/失败|错误|未确认|无效/.test(msg));
  t.setAttribute('role', t.dataset.error === 'true' ? 'alert' : 'status');
  t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('on'), t.dataset.error === 'true' ? 6000 : 2600);
}

function bindTubeNavigator() {
  const host = $('referenceTubeNavigator');
  if (!host) return;
  host.innerHTML = '<button type="button" class="tube-step" data-step="-1" title="上一根管" aria-label="上一根管">‹</button>' +
    '<input type="number" min="1" max="50" step="1" value="1" aria-label="当前管号">' +
    '<input type="range" min="1" max="50" step="1" value="1" aria-label="滑动浏览管号">' +
    '<span class="tube-total">/ 50</span>' +
    '<button type="button" class="tube-step" data-step="1" title="下一根管" aria-label="下一根管">›</button>' +
    '<button type="button" class="tube-details" title="查看当前管子的关键信息" aria-controls="right" aria-expanded="false">管子详情</button>';
  const number = host.querySelector('input[type=number]');
  const range = host.querySelector('input[type=range]');
  const updateNumber = tube => {
    number.value = range.value = String(tube);
    host.querySelector('[data-step="-1"]').disabled = tube === 1;
    host.querySelector('[data-step="1"]').disabled = tube === 50;
  };
  const requestFocus = value => {
    const tube = Number(value);
    if (!Number.isInteger(tube) || tube < 1 || tube > 50) {
      toast('管号无效，请输入 1–50 的整数');
      return;
    }
    updateNumber(tube);
    // Keep the model-side selection synchronous.  The defect layer may still
    // be fetching scope data, so waiting only for its event leaves an open
    // detail card showing the previous tube for one or more frames.
    const unit = Number(window.__thimbleDefects?.scope?.unit || 1);
    const channel = channelList.find(item => Number(unit) % 2 ? Number(item.serialOdd) === tube : Number(item.serialEven) === tube);
    const index = channel && vessel?.channels?.findIndex(item => item.pos === channel.pos);
    if (index >= 0) {
      const previousSilent = referenceSelectionSilent;
      referenceSelectionSilent = true;
      try {
        selectChannel(channel);
        if (!$('right').classList.contains('hide')) showAsmChannelInfo(index, {preferData: false});
      } finally { referenceSelectionSilent = previousSilent; }
      window.dispatchEvent(new CustomEvent('reference-tube-focused', { detail: { thimble: tube } }));
    }
    window.dispatchEvent(new CustomEvent('reference-tube-focus-request', { detail: { thimble: tube } }));
    // The defect layer may handle the request asynchronously. Re-apply the
    // open card after that event turn so late model/data callbacks cannot
    // leave the previous tube label visible.
    setTimeout(refreshOpenTubeDetails, 0);
  };
  // Number inputs do not consistently emit `change` until blur/drag ends in
  // Chromium.  Sync on every valid edit so the selected tube, labels and the
  // open detail card update while the user is typing or presses Enter.
  number.addEventListener('input', () => requestFocus(number.value));
  number.addEventListener('change', () => requestFocus(number.value));
  number.addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      event.preventDefault();
      requestFocus(number.value);
    }
  });
  range.addEventListener('input', () => requestFocus(range.value));
  host.querySelectorAll('[data-step]').forEach(button => {
    button.addEventListener('click', () => requestFocus(Number(number.value) + Number(button.dataset.step)));
  });
  host.querySelector('.tube-details').addEventListener('click', () => {
    if (!$('right').classList.contains('hide')) {
      $('right').classList.add('hide');
      syncAuxiliaryPanels();
      return;
    }
    const channel = state.channel;
    const index = channel && vessel?.channels?.findIndex(item => item.pos === channel.pos);
    if (index != null && index >= 0) showAsmChannelInfo(index);
    else showAsmOverview();
  });
  window.addEventListener('reference-tube-focused', event => {
    const tube = Number(event.detail?.thimble);
    if (!Number.isInteger(tube) || tube < 1 || tube > 50) return;
    updateNumber(tube);
    const unit = Number(window.__thimbleDefects?.scope?.unit || 1);
    const channel = channelList.find(item => Number(unit) % 2 ? Number(item.serialOdd) === tube : Number(item.serialEven) === tube);
    const index = channel && vessel?.channels?.findIndex(item => item.pos === channel.pos);
    if (index >= 0) {
      asmSelected = index;
      asmSelectedSet = new Set([index]);
      applyTubeColor();
      refreshOpenTubeDetails();
    }
  });
  updateNumber(1);
}

let topPlate = null;
async function syncTopPlateOverlay() {
  const button = $('topPlateToggle');
  if (!button) return;
  const active = Boolean(state.topPlate && state.mode === 'assembly');
  button.classList.toggle('on', active);
  button.textContent = `管板图：${active ? '开' : '关'}`;
  button.setAttribute('aria-pressed', String(active));
  if (!scene || !vessel) return;
  if (!topPlate) topPlate = new PlateOverlay(scene,vessel,invalidateModel);
  try {
    await topPlate.update(state.topPlate && state.mode==='assembly',window.__thimbleDefects?.scope?.unit,state.channel?.pos,state.view==='top');
    if (active && $('toast').textContent.startsWith('管板图加载失败')) {
      clearTimeout(toastTimer);
      $('toast').classList.remove('on');
    }
  } catch (error) {
    state.topPlate = false;
    if (topPlate.mesh) topPlate.mesh.visible = false;
    button.classList.remove('on');
    button.textContent = '管板图：关';
    button.setAttribute('aria-pressed','false');
    toast(error.message.startsWith('管板图加载失败') ? error.message : `管板图加载失败：${error.message}`);
  }
}

function bindUI() {
  window.addEventListener('reference-defects-updated', () => {
    applyTubeColor();
    syncDepthLegend();   // 数据就绪后露出「按检测数据着色」选项；开着时重进 applyTubeColor 重算最大磨损
    syncTopPlateOverlay();
    refreshOpenTubeDetails();
  });
  // 设置窗口与模型窗口可能属于同一渲染进程，也可能跨窗口；两种通知都要即时刷新。
  const refreshSeverity = () => {
    if (state.depthColor) applyTubeColor();
    syncDepthLegend();
    drawPlan();
    updateOverlay();
    invalidateModel();
  };
  window.addEventListener('storage', event => {
    if (event.key?.startsWith('thimbleSeverity')) refreshSeverity();
  });
  window.addEventListener('severity-settings-changed', refreshSeverity);
  document.querySelectorAll('#modeSeg button').forEach((b) => {
    b.onclick = () => setMode(b.dataset.mode);
  });
  document.querySelectorAll('[data-view]').forEach((b) => {
    b.onclick = () => {
      if (b.dataset.view === 'spin') {
        state.spin = !state.spin;
        if (state.spin) {
          setView('iso');
          document.querySelectorAll('[data-view]').forEach(button => {
            if (button.dataset.view !== 'spin') button.classList.toggle('on', button.dataset.view === 'iso');
          });
        }
        controls.autoRotate = state.spin;
        controls.autoRotateSpeed = 1.1;
        // 浮动条上改由 .on 类表达激活态（原来写内联 color，搬到画布后会被胶囊底色压住）
        b.classList.toggle('on', state.spin);
        // 自动旋转 = 离开正交对齐，封头按轴测恢复 0.26；关掉时若当前还是正交视角则重新压淡
        state.ortho = !state.spin && (state.view === 'front' || state.view === 'side' || state.view === 'top');
        applyDomeOpacity();
        return;
      }
      setView(b.dataset.view);
      document.querySelectorAll('[data-view]').forEach((x) => {
        if (x.dataset.view !== 'spin') x.classList.toggle('on', x === b);
      });
    };
  });
  // 用户手动旋转/平移（鼠标拖拽）时离开正交对齐，封头立刻恢复 0.26，
  // 这样"自由旋转后"不会再被压淡的封头糊住——programmatic 的 controls.update() 不会触发本事件。
  controls.addEventListener('start', () => {
    if (state.ortho) { state.ortho = false; applyDomeOpacity(); }
  });
  $('optDims').onchange = (e) => { state.dims = e.target.checked; updateOverlay(); };
  $('optStations').onchange = (e) => {
    state.stations = e.target.checked;
    if (stationGroup) stationGroup.visible = state.stations;
    updateOverlay();
  };
  $('optGhost').onchange = (e) => { state.ghost = e.target.checked; applyGhost(); };
  $('optAxis').onchange = (e) => {
    state.axis = e.target.checked;
    if (state.axis) {
      const grid = new THREE.GridHelper(400, 20, 0xc9d7e6, 0xe4ecf5);
      grid.name = 'axisHelper';
      grid.position.y = 0;
      root.add(grid);
      const ax = new THREE.AxesHelper(90);
      ax.name = 'axisHelper';
      root.add(ax);
    } else {
      root.children.filter((c) => c.name === 'axisHelper').forEach((c) => { root.remove(c); c.geometry?.dispose(); });
    }
  };
  $('optFat').onchange = (e) => {
    state.fat = e.target.checked;
    state.fatAuto = false;
    tubeMesh.scale.set(state.fat ? 4 : 1, 1, state.fat ? 4 : 1);
    applyTubeInstances();                 // 整体布置同步加粗/还原
    buildStations();
    updateOverlay();
    toast(state.fat
      ? (state.mode === 'assembly' ? '整体布置：管身径向放大 ×3（仅视觉增强，位置与长度不变）'
                                   : '管身径向放大 ×4（仅视觉增强，尺寸标注与数据不变）')
      : '恢复真实比例');
  };
  $('optCut').onchange = (e) => { state.cut = e.target.checked; applyCut(); };
  $('cutSlider').oninput = (e) => {
    state.cutPos = +e.target.value;
    if (!state.cut) { state.cut = true; $('optCut').checked = true; }
    applyCut();
  };
  $('exSlider').oninput = (e) => { state.explode = +e.target.value; applyExplode(); };
  for (const [id,key] of Object.entries({optPrv:'prv',optDome:'dome',optStruct:'struct',optPenetrations:'penetrations'})) {
    $(id).onchange = event => {
      state[key] = event.target.checked;
      applyAsmVisibility();
      if (state.mode === 'assembly') setAsmView(state.view || 'iso');
    };
  }
  $('optAxes').onchange = (e) => { state.axes = e.target.checked; applyAsmVisibility(); };
  $('optLenColor').onchange = (e) => {
    state.lenColor = e.target.checked;
    // 与「按型号着色」互斥：勾一个自动取消另一个，避免两种着色同时生效颜色打架
    if (state.lenColor && state.typeColor) {
      state.typeColor = false;
      $('optTypeColor').checked = false;
    }
    applyTubeColor();
    drawPlan();        // 平面图的着色口径跟随 3D（管长 / 型号）
  };
  $('optTypeColor').onchange = (e) => {
    state.typeColor = e.target.checked;
    if (state.typeColor && state.lenColor) {
      state.lenColor = false;
      $('optLenColor').checked = false;
    }
    applyTubeColor();
    drawPlan();
  };
  $('optDepthColor').onchange = (e) => {
    state.depthColor = e.target.checked;
    // 三种着色互斥：数据着色优先，勾上它就取消型号/管长着色
    if (state.depthColor && (state.typeColor || state.lenColor)) {
      state.typeColor = state.lenColor = false;
      $('optTypeColor').checked = $('optLenColor').checked = false;
    }
    syncDepthLegend();
    applyTubeColor();
    drawPlan();        // 平面图与 3D 同口径：数据着色时管位同步按最大磨损上色
  };
  $('optCutPrv').onchange = (e) => {
    state.cutPrv = e.target.checked;
    applyPrvCut();
    // 剖切会改变可见范围，顺手把当前视角重新构图（半个模型不该挤在一边）
    if (state.mode === 'assembly') setAsmView(state.view || 'iso');
  };
  $('infoClose').onclick = () => { $('right').classList.add('hide'); syncAuxiliaryPanels(); };
  $('defaultViewButton').onclick = resetDefaultView;
  $('topPlateToggle').onclick = () => {
    if (state.mode !== 'assembly') {
      setMode('assembly');
      state.topPlate = true;
    } else state.topPlate = !state.topPlate;
    syncTopPlateOverlay();
  };

  bindTubeNavigator();
  initGrpCollapse();   // 左栏分组折叠：默认让常用项在一屏内看完
}

/* ---------- 左栏分组折叠 ----------
 * 1440×860 下 7 个分组总高超出一屏约 582px，核心控件要滚动才够得着。
 * 默认展开「整体布置/通道选择/视图模式」三类主操作，折叠「显示/剖切/爆炸/零件」四类调整项；
 * 折叠态存 localStorage（viewer.grpCollapsed），刷新后保持——纯本地离线软件，安全。
 * 用 CSS 类 .collapsed 控制显隐（隐藏「除 .t 外的直接子节点」），不重新包 DOM、不用 <details>，
 * 因此不打乱既有 .grp 的内边距与样式。 */
// 「视图模式」已搬到画布上的浮动条，左栏只剩六组；默认展开「整体布置 + 通道选择」两组主操作，
// 折叠「显示/剖切/爆炸/零件」四组调整项——折叠组标题只有 22px 高，四条并排一眼能看到全部入口，
// 点一下即展开，状态会记住。
const GRP_COLLAPSED_DEFAULT = ['disp', 'cut', 'explode', 'parts'];
/* ---------- 左栏自适应：平面图按剩余空间缩放 ----------
 * #plan 是 164×164 的正方形 viewBox，width:100% 让它高度恒等于栏宽（≈304px），
 * 于是左栏内容总高锁死在 751px：窗口只要低于 ~860px 就必然溢出要滚动
 * （1280×800 溢出 31px，1366×768 溢出 63px）——写死像素在不同机器上就失效。
 * 这里按「可用高 = 栏可视高 − 除平面图外的总高」反算正方形边长，再居中；
/* 下限按宽度算：viewBox 约 164×164，宽 200 时圈内编号（2.95 单位）实到 3.6px，再小就看不清了。
 * 缩放必须按真实宽高比走（viewBox 不是严格正方形），只设宽度让高度 auto 即可保持比例。 */
const PLAN_MIN_W = 200;
/* 兜底下限 152px：宁可把圈内编号隐掉（3px 的字本来就是糊的，hover 仍会显示通道号），
   也不能把「通道选择」整组折掉 —— 下拉框和平面大图入口都在这一组里，
   收掉等于把选通道这条路断掉。只在 ensureFit 确认 200px 放不下时才降级。 */
const PLAN_TINY_W = 152;
function fitPlan(minWanted) {
  const left = document.querySelector('#left');
  const plan = document.querySelector('#plan');
  if (!left || !plan) return null;
  const wrap = plan.parentElement;
  /* 判隐藏不能用 plan.offsetParent：#plan 是 <svg>，SVGElement 压根没有 offsetParent
   * （那是 HTMLElement 的属性），取值恒为 undefined —— 照它判断会一路早退，缩放从不生效。
   * 折叠组里元素实测宽高为 0，用这个判最准。 */
  plan.style.width = ''; plan.style.height = '';
  const r0 = plan.getBoundingClientRect();
  if (!r0.width || !r0.height) return null;
  const naturalH = r0.height;
  const others = left.scrollHeight - naturalH;             // 平面图以外的全部内容高
  const innerW = wrap.clientWidth - 6;                     // 去掉 wrap 左右各 3px padding
  const availH = left.clientHeight - others - 6;           // 再留 6px 余量，凑掉小数误差
  const ratio = naturalH / r0.width;
  const want = Math.min(minWanted || PLAN_MIN_W, innerW);
  const w = Math.round(Math.max(want, Math.min(innerW, availH / ratio)));
  plan.style.width = w + 'px';
  // 圈内编号 2.95 单位：宽 200 时实到 3.6px（勉强可读），再小就隐掉，只留色块与选中高亮
  plan.classList.toggle('tiny', w < PLAN_MIN_W);
  return { w, h: Math.round(w * ratio) };
}

let grpSet = null;                       // 折叠状态集合，ensureFit 要读写它

/* 自适应手风琴：空间不够就自动收起最次要的组，保证左栏在任何展开组合下都不用滚动。
 * 为什么必须有这一步：1280×720 全展开时左栏内容要 1003px，而可视区只有 646px，
 * 差 357px —— 光靠缩平面图（已卡在可读下限）最多再省 30px，物理上堵不上。
 * 与其让用户滚着找控件，不如「同时只展开一类调整项」：用户一次本来也只调一类参数。
 * keep = 用户刚点开的那个组，绝不能自动收它（否则等于点了没反应）。
 * 顺序 parts → explode → cut → disp → chan：越靠后越常用；asm（整体布置）不参与自动折叠，
 * 它是主操作组，收掉等于把面板废了 —— 真到那一步就保留滚动条。 */
const AUTO_FOLD_ORDER = ['parts', 'explode', 'cut', 'disp', 'chan'];
/* autoFolded 只记「本系统因空间不足自动收起」的组，用户自己点的折叠不记 ——
   否则窗口一拉大，用户手动收起的组又冒出来，等于推翻他的操作。 */
let autoFolded = new Set();
function ensureFit(keep, notify) {
  const left = document.querySelector('#left');
  if (!left) return;
  if (!grpSet) { fitPlan(); return; }      // 早于 initGrpCollapse 的调用只做平面图适配
  const fits = () => left.scrollHeight <= left.clientHeight;
  const refit = () => { fitPlan(); if (!fits()) fitPlan(PLAN_TINY_W); };
  refit();
  /* 窗口被拉大后要还回去：只恢复 autoFolded 里的，且逐个试 —— 展开后仍放不下就立刻收回，
     保证任何一次尝试结束时都是「放得下」的状态。 */
  if (autoFolded.size) {
    for (const key of [...AUTO_FOLD_ORDER].reverse()) {   // 逆序 = 先还常用的 chan / disp
      if (!autoFolded.has(key)) continue;
      const g = left.querySelector(`.grp[data-grp="${key}"]`);
      if (!g) { autoFolded.delete(key); continue; }
      grpSet.delete(key); g.classList.remove('collapsed');
      refit();
      if (fits()) { autoFolded.delete(key); continue; }
      grpSet.add(key); g.classList.add('collapsed'); refit();   // 还是放不下，退回去
    }
  }
  /* 折组之前先把平面图压到兜底下限：收掉「通道选择」是断功能，缩平面图只是掉几个编号。 */
  if (!fits()) fitPlan(PLAN_TINY_W);
  const folded = [];
  for (const key of AUTO_FOLD_ORDER) {
    if (fits()) break;
    if (key === keep || grpSet.has(key)) continue;
    const g = left.querySelector(`.grp[data-grp="${key}"]`);
    if (!g) continue;
    grpSet.add(key); autoFolded.add(key);
    g.classList.add('collapsed');
    // 标题形如「通道选择（真实 P1→P6 长度）」：按空白切会留下半截括号，先去掉括号注释
    folded.push((g.querySelector(':scope > .t')?.textContent || key).split('（')[0].trim());
    refit();
  }
  if (folded.length) {
    try { localStorage.setItem('viewer.grpCollapsed.v2', JSON.stringify(Array.from(grpSet))); } catch {}
    if (notify) toast(`窗口高度不足，已自动收起：${folded.join('、')}`);
  }
}

function initGrpCollapse() {
  const groups = Array.from(document.querySelectorAll('#left .grp[data-grp]'));
  if (!groups.length) return;
  let set;
  try {
    // key 带 .v2：默认折叠组变过，旧缓存会让新默认值失效
    const raw = localStorage.getItem('viewer.grpCollapsed.v2');
    set = raw ? new Set(JSON.parse(raw)) : new Set(GRP_COLLAPSED_DEFAULT);
  } catch { set = new Set(GRP_COLLAPSED_DEFAULT); }
  grpSet = set;
  const sync = () => { for (const g of groups) g.classList.toggle('collapsed', set.has(g.dataset.grp)); };
  sync();
  for (const g of groups) {
    const t = g.querySelector(':scope > .t');
    if (!t) continue;
    t.setAttribute('role','button');
    t.tabIndex=0;
    const describe=()=>t.setAttribute('aria-expanded',String(!g.classList.contains('collapsed')));
    describe();
    new MutationObserver(describe).observe(g,{attributes:true,attributeFilter:['class']});
    t.addEventListener('keydown',event=>{
      if(event.key==='Enter'||event.key===' '){event.preventDefault();t.click();}
    });
    t.addEventListener('click', () => {
      const key = g.dataset.grp;
      const opening = set.has(key);          // 点之前是折叠的 → 这次是展开
      if (opening) set.delete(key); else set.add(key);
      autoFolded.delete(key);                // 用户亲手点过，此后由他说了算，不再自动管
      g.classList.toggle('collapsed', set.has(key));
      try { localStorage.setItem('viewer.grpCollapsed.v2', JSON.stringify(Array.from(set))); } catch {}
      // 展开后放不下就自动收起更次要的组（keep 住刚点开的这个，否则等于点了没反应）
      if (opening) ensureFit(key, true); else fitPlan();
      /* 左栏是 fixed 浮层，展开的组很可能被挤出视口底部 —— 用户点开却看不见，
         会当成"点了没反应"。展开后把它滚进可视区（nearest 只在必要时滚，不跳动）。 */
      if (opening && !g.classList.contains('collapsed')) g.scrollIntoView({ block: 'nearest' });
    });
  }
  ensureFit(null, false);          // 启动态也要保证不溢出（持久化的展开状态可能已超出当前窗口）
}

let rebuildTimer;

// The reference viewer owns all geometry and interaction; business overlays only use this bridge.
function resolveReferenceChannel(input = state.channel) {
  if (typeof input === 'number') return vessel?.channels?.[input] || null;
  const pos = typeof input === 'string' ? input : input?.pos || input?.position;
  return channelList.find((c) => c.pos === pos)
    || vessel?.channels?.find((c) => c.pos === pos) || null;
}

function referenceSelect(input, options = {}) {
  const channel = resolveReferenceChannel(input);
  if (!channel) return false;
  const previousSilent = referenceSelectionSilent;
  referenceSelectionSilent = options.silent !== false;
  try { selectChannel(channel); } finally { referenceSelectionSilent = previousSilent; }
  return true;
}

function getReferenceChannelGeometry(input = state.channel) {
  const selected = resolveReferenceChannel(input);
  const isAssembly = state.mode === 'assembly';
  const channel = vessel?.channels?.find((c) => c.pos === selected?.pos) || selected;
  if (isAssembly && !channel) return null;
  const length = isAssembly ? channel.L : state.L;
  const explode = isAssembly ? 0 : (partsMeshes.get('P01')?.position.y || 0);
  const topY = isAssembly ? channel.yTop : length + explode;
  const baseY = isAssembly ? channel.yBase : explode;
  return {
    channel, id: channel?.pos || null, position: channel?.pos || null,
    x: isAssembly ? channel.x : 0, z: isAssembly ? channel.z : 0,
    length, topY, baseY, mode: state.mode,
    coordinateSpace: isAssembly ? 'assembly-local' : 'single-local',
    object3D: isAssembly ? asmRoot : root,
    planes: (stations?.stations || []).map((s) => {
      const fromTop = s.fromTop === 'L' ? length : s.fromTop;
      return { ...s, name: s.id, y: topY - fromTop, fromTop };
    }),
  };
}

const referenceAPI = {
  get ready() { return referenceReady; },
  get THREE() { return THREE; },
  get scene() { return scene; },
  get root() { return root; },
  get asmRoot() { return asmRoot; },
  get camera() { return camera; },
  get renderer() { return renderer; },
  get controls() { return controls; },
  get state() { return state; },
  get model() { return model; },
  get vessel() { return vessel; },
  get channels() { return channels; },
  get channelList() { return channelList; },
  get stations() { return stations; },
  get specs() { return specs; },
  get dims() { return dims; },
  get asmG() { return asmG; },
  get asmInst() { return asmInst; },
  get asmSelected() { return asmSelected; },
  get partsMeshes() { return partsMeshes; },
  get tubeMesh() { return tubeMesh; },
  get clipPlane() { return clipPlane; },
  get topPlate() { return topPlate; },
  get selectedTubeHighlight() { return selectedTubeHighlight; },
  invalidate: invalidateModel,
  syncAuxiliaryPanels,
  resetDefaultView,
  setMode(mode) {
    if (!['assembly', 'joint', 'full', 'socket'].includes(mode)) return false;
    setMode(mode); return true;
  },
  setView(view) {
    if (!['iso', 'front', 'side', 'top', 'fit'].includes(view)) return false;
    setView(view); return true;
  },
  selectChannel: referenceSelect,
  selectAsmChannel(index, options) { return referenceSelect(index, options); },
  syncChannelSelection: referenceSelect,
  getChannelGeometry: getReferenceChannelGeometry,
  resolveChannel: resolveReferenceChannel,
};
window.__thimbleReference = referenceAPI;

function observeReferenceViewport() {
  if (typeof ResizeObserver === 'undefined') return;
  let lastWidth = innerWidth;
  let lastHeight = innerHeight;
  const observer = new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect;
    if (width < 1 || height < 1) { lastWidth = width; lastHeight = height; return; }
    if (width === lastWidth && height === lastHeight) return;
    const wasHidden = lastWidth < 1 || lastHeight < 1;
    lastWidth = width; lastHeight = height;
    dispatchEvent(new Event('resize'));
    if (wasHidden) setView(state.view || 'fit');
  });
  observer.observe($('stage'));
}

function bindReferencePanelToggle() {
  const button = $('referencePanelToggle');
  if (!button) return;
  button.addEventListener('click', () => {
    const open = document.body.classList.toggle('reference-controls-open');
    if (open) {
      if ($('referenceInspection')) $('referenceInspection').open = false;
      $('right').classList.add('hide');
    }
    button.setAttribute('aria-expanded', String(open));
    syncAuxiliaryPanels();
    ensureFit(null, false);
    setView(state.view || 'fit');
  });
  const inspection = $('inspectionToggle');
  if (inspection) {
    inspection.addEventListener('click', () => {
      const panel = $('referenceInspection');
      if (!panel) return;
      panel.open = !panel.open;
      inspection.classList.toggle('on', panel.open);
      inspection.setAttribute('aria-pressed', String(panel.open));
    });
  }
}

function observeInfoLayout() {
  const update = () => {
    const open = !$('right').classList.contains('hide');
    document.querySelector('#referenceTubeNavigator .tube-details')?.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('reference-info-open',open);
    if (open && $('referenceInspection')) $('referenceInspection').open = false;
    if (open) {
      document.body.classList.remove('reference-controls-open');
      $('referencePanelToggle').setAttribute('aria-expanded','false');
    }
    syncAuxiliaryPanels();
  };
  new MutationObserver(update).observe($('right'),{attributes:true,attributeFilter:['class']});
  update();
}

/* ----------------------------------------------------------------- 启动 */
async function init() {
  const [asm, chan, stat, dim, ves, dome, sp] = await Promise.all([
    fetch('./data/thimble_assembly.json').then((r) => r.json()),
    fetch('./data/p1p6_channels.json').then((r) => r.json()),
    fetch('./data/p1p6_stations.json').then((r) => r.json()),
    fetch('./data/dimensions.json').then((r) => r.json()).catch(() => null),
    fetch('./data/vessel_layout.json').then((r) => r.json()).catch(() => null),
    fetch('./data/dome.json').then((r) => r.json()).catch(() => null),
    fetch('./data/tube_specs.json').then((r) => r.json()).catch(() => null),
  ]);
  domeData = dome;
  model = asm; channels = chan; stations = stat; dims = dim; vessel = ves; specs = sp;
  // 规格联动：从 tube_specs.json 建两张查找表 —— 型号色值、以及 16 档 V 的排位
  if (specs) {
    for (const m of specs.models) TYPE_COLOR[m.type] = m.color;
    // 16 档 V 升序排定档序（空心柱无 V，不入表）
    const vs = specs.lengthSpecs.map((s) => s.V).sort((a, b) => a - b);
    vs.forEach((v, i) => V_RANK.set(v, i + 1));
  }
  // 从尺寸清单同步几何参数
  if (dims?.geometry) model.geometry = dims.geometry;
  state.L = model.tubeLengthDefault || 3000;

  initScene();
  buildAssembly();
  buildChannelUI();
  bindUI();
  bindReferencePanelToggle();
  observeInfoLayout();
  // 回归脚本用：asmSelected / asmInst 是 module 级 let，不挂 window 读不到
  window.__asmSel = () => asmSelected;
  window.__asmTubes = () => asmInst.TUBES || null;
  fillColumnLegend();
  fillModelLegend();         // 型号图例（按型号着色 + 点击筛选），与柱图例同族、紧邻其后
  setMode('assembly');        // 先看整体，再进单件
  setView('iso');
  document.querySelector('[data-view="iso"]').classList.add('on');
  $('loading').classList.add('off');
  referenceReady = true;
  observeReferenceViewport();
  dispatchEvent(new CustomEvent('reference-model-ready', { detail: { api: referenceAPI } }));
  requestAnimationFrame(loop);

  console.log('[指套管模型] 零件 %d，三角面 %d；整体 %d 通道，外球面 Rs=%.2f mm，拟合残差 %.2f mm',
    model.parts.length, model.parts.reduce((a, p) => a + (p.triCount || 0), 0),
    vessel ? vessel.channels.length : 0,
    vessel ? vessel.vessel.outerRadius : 0, vessel ? vessel.fit.rms : 0);
}

function loop(time = performance.now()) {
  requestAnimationFrame(loop);
  if (document.hidden) { invalidateModel(); return; }
  if (window.parent !== window) {
    try {
      const view = window.parent.document.querySelector('#threeD');
      if (view && !view.classList.contains('active')) { invalidateModel(); return; }
    } catch {}
  }
  controls.update();
  syncSelectedTubeHighlight();
  dispatchEvent(new CustomEvent('reference-frame'));
  // Keep stationary models cheap, including software WebGL; interactive frames
  // are capped at 30 fps and the idle refresh catches asynchronous mesh changes.
  if ((renderDirty && time - lastRenderTime >= 1000 / 30) || time - lastRenderTime >= 10000) {
    renderer.render(scene, camera);
    renderDirty = false;lastRenderTime = time;
  }
  updateAxisGizmo();
}

init().catch((err) => {
  console.error(err);
  $('loading').innerHTML = `<div class="box"><p style="color:#c0392b">模型加载失败：${err.message}</p></div>`;
});
window.addEventListener('workspace-tubes-selected', event => {
  applyWorkspaceTubeSelection(event.detail?.thimbles || []);
});
