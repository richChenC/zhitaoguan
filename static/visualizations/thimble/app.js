import * as THREE from '/vendor/three.module.min.js';
import { OrbitControls } from '/vendor/OrbitControls.js';

const ODD_POSITIONS='L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 N5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
const EVEN_POSITIONS='B5 C8 E11 D10 D12 C12 B10 B7 A9 B8 D5 D3 F6 H13 F9 G14 F13 E5 F11 D7 G7 F2 H6 H11 J10 J12 J15 G9 F8 F4 H3 H1 J3 N12 L9 L11 L14 J5 J7 H4 M3 M5 R8 N7 N8 N10 L5 L8 L6 L4'.split(' ');
let POSITIONS=ODD_POSITIONS;
const COLS='RPNMLKJHGFEDCBA'.split('');
const CORE_ROWS=[
  'J1 H1 G1','L2 K2 J2 H2 G2 F2 E2','M3 L3 K3 J3 H3 G3 F3 E3 D3',
  'N4 M4 L4 K4 J4 H4 G4 F4 E4 D4 C4','P5 N5 M5 L5 K5 J5 H5 G5 F5 E5 D5 C5 B5',
  'P6 N6 M6 L6 K6 J6 H6 G6 F6 E6 D6 C6 B6','R7 P7 N7 M7 L7 K7 J7 H7 G7 F7 E7 D7 C7 B7 A7',
  'R8 P8 N8 M8 L8 K8 J8 H8 G8 F8 E8 D8 C8 B8 A8','R9 P9 N9 M9 L9 K9 J9 H9 G9 F9 E9 D9 C9 B9 A9',
  'P10 N10 M10 L10 K10 J10 H10 G10 F10 E10 D10 C10 B10','P11 N11 M11 L11 K11 J11 H11 G11 F11 E11 D11 C11 B11',
  'N12 M12 L12 K12 J12 H12 G12 F12 E12 D12 C12','M13 L13 K13 J13 H13 G13 F13 E13 D13',
  'L14 K14 J14 H14 G14 F14 E14','J15 H15 G15'
];

const host=document.querySelector('#scene');
const scene=new THREE.Scene();scene.background=new THREE.Color(0x080b0c);scene.fog=new THREE.FogExp2(0x080b0c,.012);
const camera=new THREE.PerspectiveCamera(34,1,.1,220);camera.position.set(32,18,37);
const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;host.append(renderer.domElement);
const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(4,2,0);controls.enableDamping=true;controls.dampingFactor=.065;controls.minDistance=10;controls.maxDistance=85;
scene.add(new THREE.HemisphereLight(0xe8f1ed,0x111716,2.2));
const key=new THREE.DirectionalLight(0xffffff,4);key.position.set(15,24,18);scene.add(key);
const rim=new THREE.DirectionalLight(0xd7ef4a,2.2);rim.position.set(-16,8,-12);scene.add(rim);

const root=new THREE.Group();scene.add(root);
const coreGroup=new THREE.Group(),tubesGroup=new THREE.Group(),structureGroup=new THREE.Group(),labelsGroup=new THREE.Group(),externalGroup=new THREE.Group();
root.add(coreGroup,tubesGroup,structureGroup,labelsGroup,externalGroup);
const tubeGroups=[];let selected=0,scanning=false,coreVisible=true,labelsVisible=true,cameraTween=null,currentCamera='overview';

const metal=new THREE.MeshStandardMaterial({color:0x8f9b96,metalness:.82,roughness:.28});
const darkMetal=new THREE.MeshStandardMaterial({color:0x39433f,metalness:.74,roughness:.34});
const fuelMaterial=new THREE.MeshStandardMaterial({color:0x485550,metalness:.35,roughness:.58,transparent:true,opacity:.2});
const shellMaterial=new THREE.MeshPhysicalMaterial({color:0x71807a,metalness:.45,roughness:.28,transparent:true,opacity:.16,side:THREE.DoubleSide,depthWrite:false});
const tubeMaterial=new THREE.MeshPhysicalMaterial({color:0xaebbb5,metalness:.78,roughness:.18,clearcoat:.65});
const sleeveMaterial=new THREE.MeshPhysicalMaterial({color:0x53605b,metalness:.68,roughness:.3,transparent:true,opacity:.56});
const signalMaterial=new THREE.MeshStandardMaterial({color:0xd7ef4a,emissive:0x829500,emissiveIntensity:1.5,metalness:.25,roughness:.28});
const hotMaterial=new THREE.MeshStandardMaterial({color:0xe45b4e,emissive:0x6d1710,emissiveIntensity:.65,metalness:.35,roughness:.3});

function coordinate(position){const m=position.match(/([A-Z])(\d+)/);return{x:(COLS.indexOf(m[1])-7)*1.08,z:(+m[2]-8)*1.08}}
function cylinder(radius,height,material,segments=20){return new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,height,segments),material)}
function horizontalCylinder(radius,length,material){const mesh=cylinder(radius,length,material,24);mesh.rotation.z=Math.PI/2;return mesh}
function tubeFrom(points,radius,material,segments=48){return new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),segments,radius,14,false),material)}
function makeLabel(text,color='#d7ef4a'){const wide=text.length>4,c=document.createElement('canvas');c.width=wide?440:180;c.height=58;const x=c.getContext('2d');x.fillStyle='#111716e8';x.fillRect(0,0,c.width,c.height);x.strokeStyle=color;x.strokeRect(1,1,c.width-2,c.height-2);x.fillStyle='#eef2ed';x.font='700 24px Microsoft YaHei';x.textAlign='center';x.textBaseline='middle';x.fillText(text,c.width/2,30);const s=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(c),transparent:true,depthTest:false}));s.scale.set(wide?4.3:1.75,.56,1);return s}

function buildCore(){
  CORE_ROWS.forEach(row=>row.split(' ').forEach(cell=>{const{x,z}=coordinate(cell);const a=new THREE.Mesh(new THREE.BoxGeometry(.96,8.2,.96),fuelMaterial);a.position.set(x,5.2,z);a.userData.cell=cell;coreGroup.add(a)}));
}

function buildInternalStructures(){
  const lowerGrid=new THREE.Mesh(new THREE.CylinderGeometry(8.55,8.55,.22,72),darkMetal);lowerGrid.position.y=.96;structureGroup.add(lowerGrid);
  const supportPlate=new THREE.Mesh(new THREE.CylinderGeometry(8.2,8.2,.5,72),metal);supportPlate.position.y=-.05;structureGroup.add(supportPlate);
  for(let i=0;i<12;i++){const a=i/12*Math.PI*2,col=cylinder(.24,2.5,darkMetal,16);col.position.set(Math.cos(a)*6.4,-1.55,Math.sin(a)*6.4);structureGroup.add(col)}
  const gridPlate=new THREE.Mesh(new THREE.CylinderGeometry(7.65,7.65,.24,72),metal);gridPlate.position.y=-2.78;structureGroup.add(gridPlate);
  const vesselWall=new THREE.Mesh(new THREE.CylinderGeometry(9.5,9.5,8.3,72,1,true,Math.PI*.18,Math.PI*1.42),shellMaterial);vesselWall.position.y=-.2;structureGroup.add(vesselWall);
  const lowerHead=new THREE.Mesh(new THREE.SphereGeometry(9.5,72,28,Math.PI*.18,Math.PI*1.42,Math.PI/2,Math.PI/2),shellMaterial);lowerHead.scale.y=.48;lowerHead.position.y=-4.35;structureGroup.add(lowerHead);
}

function buildThimbles(){
  POSITIONS.forEach((position,index)=>{const{x,z}=coordinate(position),g=new THREE.Group();g.userData={index,position};
    const straight=cylinder(.095,13.25,tubeMaterial,14);straight.position.set(x,2.575,z);g.add(straight);
    const tip=new THREE.Mesh(new THREE.SphereGeometry(.095,14,8,0,Math.PI*2,0,Math.PI/2),tubeMaterial);tip.position.set(x,9.2,z);g.add(tip);
    const guide=new THREE.Mesh(new THREE.CylinderGeometry(.28,.28,4.7,18,1,true),sleeveMaterial);guide.position.set(x,-1.65,z);g.add(guide);
    const nozzle=cylinder(.32,1.25,darkMetal,18);nozzle.position.set(x,-4.32,z);g.add(nozzle);
    tubesGroup.add(g);tubeGroups.push(g);
  });
}

const pointDefinitions=[
  ['P1',.9,'下栅格板'],['P2',.2,'支撑板上表面'],['P3',-.3,'支撑板下表面'],
  ['P4',-2.65,'支撑柱与格架板'],['P5',-3.7,'支撑柱与RPV管座'],['P6',-4.75,'RPV管座与导向管']
];
function buildPointLabels(){pointDefinitions.forEach(([p,y,label],i)=>{const color=i===0||i===3?'#e45b4e':'#d7ef4a';const line=new THREE.Mesh(new THREE.BoxGeometry(2.1,.025,.025),new THREE.MeshBasicMaterial({color}));line.position.set(9.3,y,0);labelsGroup.add(line);const sprite=makeLabel(`${p} ${label}`,color);sprite.position.set(11.5,y,0);labelsGroup.add(sprite)})}

function addValve(group,x,label,automatic=false){
  const body=horizontalCylinder(.42,1.05,darkMetal);body.position.set(x,-5.6,0);group.add(body);
  const flangeA=horizontalCylinder(.58,.16,metal),flangeB=horizontalCylinder(.58,.16,metal);flangeA.position.set(x-.52,-5.6,0);flangeB.position.set(x+.52,-5.6,0);group.add(flangeA,flangeB);
  const stem=cylinder(.12,.75,metal,14);stem.position.set(x,-5.05,0);group.add(stem);
  const actuator=new THREE.Mesh(new THREE.BoxGeometry(automatic?1.1:.72,automatic?.8:.18,.72),darkMetal);actuator.position.set(x,automatic?-4.45:-4.65,0);group.add(actuator);
  const tag=makeLabel(label);tag.position.set(x,-6.5,0);group.add(tag);
}
function buildExternalPath(){
  externalGroup.clear();const{x,z}=coordinate(POSITIONS[selected]);
  const route=tubeFrom([new THREE.Vector3(x,-4.5,z),new THREE.Vector3(x,-5.15,z),new THREE.Vector3(x+.5,-5.6,z*.65),new THREE.Vector3(11,-5.6,0),new THREE.Vector3(25,-5.6,0)],.11,signalMaterial,72);
  const guide=tubeFrom([new THREE.Vector3(x,-4.5,z),new THREE.Vector3(x,-5.15,z),new THREE.Vector3(x+.5,-5.6,z*.65),new THREE.Vector3(11,-5.6,0),new THREE.Vector3(25,-5.6,0)],.28,sleeveMaterial,72);externalGroup.add(guide);externalGroup.add(route);
  addValve(externalGroup,13.2,'手动隔离阀');
  const seal=horizontalCylinder(.52,2.2,darkMetal);seal.position.set(16.2,-5.6,0);externalGroup.add(seal);const sealTag=makeLabel('密封组件');sealTag.position.set(16.2,-6.5,0);externalGroup.add(sealTag);
  addValve(externalGroup,19.2,'球形逆止阀');addValve(externalGroup,22.7,'自动阀',true);
  const drive=new THREE.Mesh(new THREE.BoxGeometry(1.7,1.35,1.25),darkMetal);drive.position.set(25,-5.6,0);externalGroup.add(drive);const driveTag=makeLabel('传送装置');driveTag.position.set(25,-6.5,0);externalGroup.add(driveTag);
}

buildCore();buildInternalStructures();buildThimbles();buildPointLabels();
const detector=cylinder(.05,.7,signalMaterial,14);root.add(detector);const detectorGlow=new THREE.PointLight(0xd7ef4a,8,3);root.add(detectorGlow);
const defectMaterial=new THREE.MeshStandardMaterial({color:0xe45b4e,emissive:0x7a1912,emissiveIntensity:1.15,metalness:.22,roughness:.26});
const defectPreview=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),defectMaterial);root.add(defectPreview);

function updateDepth(){const value=+document.querySelector('#detectorDepth').value,y=-3.95+value/100*13.5;detector.position.y=y;detectorGlow.position.y=y;document.querySelector('#depthOutput').textContent=`${Math.round(value)}%`}
function setSelected(index){selected=Math.max(0,Math.min(49,index));tubeGroups.forEach((g,i)=>{g.visible=currentCamera!=='tube'||i===selected;g.children.forEach(m=>{if(m.material===tubeMaterial||m.material===signalMaterial)m.material=i===selected?signalMaterial:tubeMaterial})});const pos=POSITIONS[selected],{x,z}=coordinate(pos);detector.position.x=x;detector.position.z=z;detectorGlow.position.x=x;detectorGlow.position.z=z;document.querySelector('#tubeSelect').value=selected+1;document.querySelector('#tubeOutput').textContent=String(selected+1).padStart(2,'0');document.querySelector('#objectName').textContent=`指套管 #${String(selected+1).padStart(2,'0')}`;document.querySelector('#position').textContent=pos;buildExternalPath();updateDepth();updateArtificialDefect()}

function updateArtificialDefect(){
  const zone=document.querySelector('#layerSelect')?.value||'P1';
  const offset=Math.max(0,Math.min(400,Number(document.querySelector('#offsetInput')?.value||0)));
  const layerIndex=Math.max(0,pointDefinitions.findIndex(item=>item[0]===zone));
  const base=pointDefinitions[layerIndex][1],next=pointDefinitions[layerIndex+1]?.[1]??-5.25;
  const {x,z}=coordinate(POSITIONS[selected]);defectPreview.position.set(x,base-(offset/400)*(base-next),z);
  const size=Number(document.querySelector('#defectSize')?.value||11);defectPreview.scale.setScalar(size/70);
  const color=document.querySelector('#defectColor')?.value||'#e45b4e';defectMaterial.color.set(color);defectMaterial.emissive.set(color);
  document.querySelector('#defectSummary').textContent=`${String(selected+1).padStart(2,'0')}号管 · ${zone} + ${offset} mm`;
  document.querySelector('#defectSizeOutput').textContent=String(size);
}

function applyParity(value){
  POSITIONS=value==='even'?EVEN_POSITIONS:ODD_POSITIONS;
  tubeGroups.forEach((group,index)=>{const {x,z}=coordinate(POSITIONS[index]);group.userData.position=POSITIONS[index];group.children.forEach(mesh=>{mesh.position.x=x;mesh.position.z=z})});
  setSelected(selected);
}
setSelected(0);

const presets={overview:{p:[43,22,49],t:[8,1,0]},section:{p:[40,9,43],t:[8,-.8,0]},plate:{p:[0,37,.01],t:[0,2,0]},tube:{p:[36,3,27],t:[13,-3.2,0]}};
function setCamera(name){currentCamera=name;const preset=presets[name];tubeGroups.forEach((g,i)=>g.visible=name!=='tube'||i===selected);coreGroup.visible=name==='tube'?false:coreVisible;cameraTween={start:performance.now(),fromP:camera.position.clone(),fromT:controls.target.clone(),toP:new THREE.Vector3(...preset.p),toT:new THREE.Vector3(...preset.t)};document.querySelectorAll('[data-camera]').forEach(b=>b.classList.toggle('active',b.dataset.camera===name))}
function enter(){document.querySelector('.intro').classList.add('dismissed');document.querySelector('.inspector').classList.add('visible')}
function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}new ResizeObserver(resize).observe(host);resize();

const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();renderer.domElement.addEventListener('pointerdown',event=>{const r=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects(tubeGroups,true)[0];if(hit){let o=hit.object;while(o.parent&&!o.userData.position)o=o.parent;if(o.userData.position)setSelected(o.userData.index)}});
document.querySelector('#enter').onclick=()=>{enter();setCamera('overview')};
document.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>{enter();setCamera(b.dataset.camera)});
document.querySelector('#tubeSelect').oninput=e=>setSelected(+e.target.value-1);document.querySelector('#detectorDepth').oninput=updateDepth;
document.querySelector('#paritySelect').onchange=e=>applyParity(e.target.value);
document.querySelector('#layerSelect').onchange=updateArtificialDefect;document.querySelector('#offsetInput').oninput=updateArtificialDefect;document.querySelector('#defectColor').oninput=updateArtificialDefect;document.querySelector('#defectSize').oninput=updateArtificialDefect;
document.querySelector('#coreOpacity').oninput=e=>{fuelMaterial.opacity=Number(e.target.value)/100;document.querySelector('#coreOpacityOutput').textContent=`${e.target.value}%`};
document.querySelector('#toggleCore').onclick=e=>{coreVisible=!coreVisible;coreGroup.visible=currentCamera!=='tube'&&coreVisible;e.currentTarget.classList.toggle('active',coreVisible)};
document.querySelector('#toggleLabels').onclick=e=>{labelsVisible=!labelsVisible;labelsGroup.visible=labelsVisible;e.currentTarget.classList.toggle('active',labelsVisible)};
document.querySelector('#toggleDefect').onclick=e=>{defectPreview.visible=!defectPreview.visible;e.currentTarget.classList.toggle('active',defectPreview.visible)};
document.querySelector('#autoScan').onclick=e=>{scanning=!scanning;e.currentTarget.classList.toggle('active',scanning)};

enter();updateArtificialDefect();
let frames=0,lastFps=performance.now();function animate(now){if(cameraTween){const t=Math.min(1,(now-cameraTween.start)/850),e=1-Math.pow(1-t,3);camera.position.lerpVectors(cameraTween.fromP,cameraTween.toP,e);controls.target.lerpVectors(cameraTween.fromT,cameraTween.toT,e);if(t===1)cameraTween=null}if(scanning){const value=(Math.sin(now*.0012)*.5+.5)*100;document.querySelector('#detectorDepth').value=value;updateDepth()}controls.update();renderer.render(scene,camera);frames++;if(now-lastFps>1000){document.querySelector('#fps').textContent=`${frames} FPS`;frames=0;lastFps=now}requestAnimationFrame(animate)}requestAnimationFrame(animate);
