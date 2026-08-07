import * as THREE from '/vendor/three.module.min.js';
import { OrbitControls } from '/vendor/OrbitControls.js';
const EMBEDDED=new URLSearchParams(location.search).get('embedded')==='1';
if(EMBEDDED)document.body.classList.add('embedded');

const ODD_POSITIONS='L11 G14 N7 H13 J12 R8 N12 N10 L14 J15 H11 F13 J7 L5 M5 L8 N8 L6 J10 L9 F9 C12 G7 L4 J5 M3 G9 E11 F11 D12 F6 B10 D7 E5 H3 J3 H6 H4 F8 D10 B7 B5 D3 D5 F2 H1 B8 F4 C8 A9'.split(' ');
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
const scene=new THREE.Scene();scene.background=new THREE.Color(0x0b1213);
// Keep the rear rows readable in the overview. The model already has transparent
// support layers, so a dense scene fog only makes otherwise valid tubes disappear.
scene.fog=new THREE.FogExp2(0x0b1213,.0055);
const camera=new THREE.PerspectiveCamera(34,1,.1,220);camera.position.set(32,18,37);
const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(Math.max(devicePixelRatio,1)*2,3));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.08;host.append(renderer.domElement);
const defectTooltip=document.createElement('div');
defectTooltip.className='defect-tooltip';
defectTooltip.hidden=true;
defectTooltip.setAttribute('role','status');
document.querySelector('#experience')?.append(defectTooltip);
function createStudioEnvironment(){
  const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=512;const context=canvas.getContext('2d');
  const vertical=context.createLinearGradient(0,0,0,512);vertical.addColorStop(0,'#dce8e2');vertical.addColorStop(.24,'#82918a');vertical.addColorStop(.5,'#303a36');vertical.addColorStop(.74,'#66736d');vertical.addColorStop(1,'#111816');context.fillStyle=vertical;context.fillRect(0,0,1024,512);
  for(let center=0;center<1024;center+=128){const strip=context.createLinearGradient(center-48,0,center+48,0);strip.addColorStop(0,'rgba(255,255,255,0)');strip.addColorStop(.38,'rgba(244,251,247,.2)');strip.addColorStop(.5,'rgba(255,255,255,.86)');strip.addColorStop(.62,'rgba(244,251,247,.2)');strip.addColorStop(1,'rgba(255,255,255,0)');context.fillStyle=strip;context.fillRect(center-48,54,96,360)}
  const source=new THREE.CanvasTexture(canvas);source.mapping=THREE.EquirectangularReflectionMapping;source.colorSpace=THREE.SRGBColorSpace;
  const generator=new THREE.PMREMGenerator(renderer);generator.compileEquirectangularShader();const target=generator.fromEquirectangular(source);scene.environment=target.texture;source.dispose();generator.dispose();
}
createStudioEnvironment();
function createBrushedMetalTexture(){
  const canvas=document.createElement('canvas');canvas.width=256;canvas.height=8;const context=canvas.getContext('2d');
  for(let start=0;start<256;start+=64){const band=context.createLinearGradient(start,0,start+64,0);band.addColorStop(0,'#56615c');band.addColorStop(.22,'#85938d');band.addColorStop(.43,'#f4faf7');band.addColorStop(.56,'#ffffff');band.addColorStop(.72,'#9ba8a2');band.addColorStop(1,'#56615c');context.fillStyle=band;context.fillRect(start,0,64,8)}
  const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=THREE.RepeatWrapping;texture.wrapT=THREE.ClampToEdgeWrapping;texture.needsUpdate=true;return texture;
}
const brushedMetalTexture=createBrushedMetalTexture();
const controls=new OrbitControls(camera,renderer.domElement);controls.target.set(0,-.6,0);controls.enableDamping=true;controls.dampingFactor=.28;controls.rotateSpeed=.3;controls.panSpeed=.48;controls.zoomSpeed=.72;controls.minDistance=10;controls.maxDistance=85;controls.minPolarAngle=.06;controls.maxPolarAngle=Math.PI-.06;
// 左键低速旋转，中键和右键平移，滚轮缩放。
controls.mouseButtons.MIDDLE=THREE.MOUSE.PAN;
controls.mouseButtons.RIGHT=THREE.MOUSE.PAN;
// Fixed world-space lights keep brightness stable while the model rotates.
scene.add(new THREE.AmbientLight(0xdce5e1,.82));
const inspectionLights=new THREE.Group(),inspectionTarget=new THREE.Object3D();inspectionTarget.position.set(0,-.8,0);inspectionLights.add(inspectionTarget);
[[10,18,14,0xf8fbfa,1.65],[-14,8,10,0xcbd9d2,1.05],[8,3,-16,0x9db9ad,.72],[-4,-10,6,0xdce7e2,.28]].forEach(([x,y,z,color,intensity])=>{const light=new THREE.DirectionalLight(color,intensity);light.position.set(x,y,z);light.target=inspectionTarget;inspectionLights.add(light)});
scene.add(inspectionLights);scene.add(camera);

const root=new THREE.Group();scene.add(root);
const coreGroup=new THREE.Group(),tubesGroup=new THREE.Group(),singleTubeModelGroup=new THREE.Group(),selectedTubeHighlightGroup=new THREE.Group(),structureGroup=new THREE.Group(),shellGroup=new THREE.Group(),labelsGroup=new THREE.Group(),singleTubeLabelsGroup=new THREE.Group(),numberGroup=new THREE.Group(),tubeHitGroup=new THREE.Group(),orientationGroup=new THREE.Group(),externalGroup=new THREE.Group(),dataDefectsGroup=new THREE.Group(),evolutionGroup=new THREE.Group();
root.add(coreGroup,tubesGroup,singleTubeModelGroup,selectedTubeHighlightGroup,structureGroup,shellGroup,labelsGroup,singleTubeLabelsGroup,numberGroup,tubeHitGroup,orientationGroup,externalGroup,dataDefectsGroup,evolutionGroup);
const tubeGroups=[],tubeSquareCells=[];let selected=0,workspaceRows=[],scanning=false,coreVisible=true,structureVisible=true,externalVisible=false,labelsVisible=true,orientationVisible=true,shellVisible=false,numbersVisible=true,cameraTween=null,currentCamera='overview';

const metal=new THREE.MeshPhysicalMaterial({color:0x899791,metalness:.52,roughness:.38,envMapIntensity:.9,clearcoat:.16,clearcoatRoughness:.48});
const darkMetal=new THREE.MeshPhysicalMaterial({color:0x35413c,metalness:.42,roughness:.42,envMapIntensity:.8});
const fuelMaterial=new THREE.MeshStandardMaterial({color:0x435a51,emissive:0x0b0f0d,emissiveIntensity:.06,metalness:.08,roughness:.76,transparent:true,opacity:.11,depthWrite:false});
const shellMaterial=new THREE.MeshPhysicalMaterial({color:0x718b82,metalness:.04,roughness:.58,envMapIntensity:.35,transparent:true,opacity:.18,side:THREE.DoubleSide,depthWrite:false});
const tubeMaterial=new THREE.MeshPhysicalMaterial({color:0xdbe5df,map:brushedMetalTexture,metalness:.56,roughness:.31,envMapIntensity:1.06,clearcoat:.24,clearcoatRoughness:.36});
const sleeveMaterial=new THREE.MeshPhysicalMaterial({color:0x789087,map:brushedMetalTexture,metalness:.38,roughness:.4,envMapIntensity:.82,transparent:true,opacity:.2,depthWrite:false});
const signalMaterial=new THREE.MeshStandardMaterial({color:0xd7ef4a,emissive:0x829500,emissiveIntensity:1.5,metalness:.25,roughness:.28});
const edgeMetal=new THREE.MeshPhysicalMaterial({color:0x596660,metalness:.72,roughness:.26,envMapIntensity:1.1,clearcoat:.2,clearcoatRoughness:.32});
const fastenerMetal=new THREE.MeshPhysicalMaterial({color:0xb7c1bc,metalness:.8,roughness:.2,envMapIntensity:1.15});
const layerRingMaterial=new THREE.MeshPhysicalMaterial({color:0x9ba9a2,metalness:.86,roughness:.22,envMapIntensity:1.25,clearcoat:.28,clearcoatRoughness:.24});
const layerAccent='#d7ef4a';
const supportMaterials=[];

function coordinate(position){const m=position.match(/([A-Z])(\d+)/);return{x:(COLS.indexOf(m[1])-7)*1.08,z:(+m[2]-8)*1.08}}
function cylinder(radius,height,material,segments=32){return new THREE.Mesh(new THREE.CylinderGeometry(radius,radius,height,segments),material)}
function horizontalCylinder(radius,length,material){const mesh=cylinder(radius,length,material,24);mesh.rotation.z=Math.PI/2;return mesh}
function tubeFrom(points,radius,material,segments=48){return new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),segments,radius,14,false),material)}
function makeLabel(text,color='#d7ef4a'){const wide=text.length>4,c=document.createElement('canvas');c.width=wide?440:180;c.height=58;const x=c.getContext('2d');x.imageSmoothingEnabled=true;x.fillStyle='#111716e8';x.fillRect(0,0,c.width,c.height);x.strokeStyle=color;x.strokeRect(1,1,c.width-2,c.height-2);x.fillStyle='#eef2ed';x.font='700 24px Microsoft YaHei';x.textAlign='center';x.textBaseline='middle';x.fillText(text,c.width/2,30);const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=Math.min(renderer.capabilities.getMaxAnisotropy(),4);texture.minFilter=THREE.LinearMipmapLinearFilter;texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=true;const s=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));s.scale.set(wide?4.3:1.75,.56,1);return s}
function makePlateLabel(text,width,height,accent='#75866b',{fontSize=58,background='rgba(16,23,22,.88)',border=5}={}){const c=document.createElement('canvas');c.width=512;c.height=256;const x=c.getContext('2d');x.imageSmoothingEnabled=true;x.fillStyle=background;x.fillRect(4,4,504,248);x.strokeStyle=accent;x.lineWidth=border*2;x.strokeRect(10,10,492,236);x.fillStyle='#ffffff';x.font=`700 ${fontSize*2}px Consolas`;x.textAlign='center';x.textBaseline='middle';x.fillText(text,256,136);const texture=new THREE.CanvasTexture(c);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=Math.min(renderer.capabilities.getMaxAnisotropy(),4);texture.generateMipmaps=true;texture.minFilter=THREE.LinearMipmapLinearFilter;texture.magFilter=THREE.LinearFilter;texture.needsUpdate=true;const mesh=new THREE.Mesh(new THREE.PlaneGeometry(width,height),new THREE.MeshBasicMaterial({map:texture,transparent:true,alphaTest:.03,side:THREE.DoubleSide,depthTest:false,toneMapped:false}));mesh.rotation.x=-Math.PI/2;mesh.renderOrder=20;return mesh}

function buildCore(){
  const height=EMBEDDED?3.2:8.2,center=EMBEDDED?3:5.2;
  CORE_ROWS.forEach(row=>row.split(' ').forEach(cell=>{const{x,z}=coordinate(cell);const a=new THREE.Mesh(new THREE.BoxGeometry(.96,height,.96),fuelMaterial);a.position.set(x,center,z);a.userData.cell=cell;coreGroup.add(a)}));
}

function buildInternalStructures(){
  const plateMetal=metal.clone(),plateDark=darkMetal.clone();plateMetal.color.set(0x879b92);plateDark.color.set(0x3f5149);[plateMetal,plateDark].forEach(material=>{material.transparent=true;material.opacity=.52;material.depthWrite=true});supportMaterials.push(plateMetal,plateDark);
  const gridMaterial=plateDark.clone();gridMaterial.opacity=.3;gridMaterial.depthWrite=false;supportMaterials.push(gridMaterial);
  // P1: thin lower grid plate, visually distinct from the solid support plate.
  const lowerGrid=new THREE.Mesh(new THREE.CylinderGeometry(8.55,8.55,.14,96),gridMaterial);lowerGrid.position.y=1.35;structureGroup.add(lowerGrid);
  const gridBarMaterial=edgeMetal.clone();gridBarMaterial.transparent=true;gridBarMaterial.opacity=.5;gridBarMaterial.depthWrite=false;supportMaterials.push(gridBarMaterial);
  for(let i=-6;i<=6;i++){
    const xBar=new THREE.Mesh(new THREE.BoxGeometry(15.6,.055,.055),gridBarMaterial);xBar.position.set(0,1.45,i*1.08);structureGroup.add(xBar);
    const zBar=new THREE.Mesh(new THREE.BoxGeometry(.055,.055,15.6),gridBarMaterial);zBar.position.set(i*1.08,1.45,0);structureGroup.add(zBar);
  }
  // P2/P3: one thick support plate with two inspection surfaces.
  const supportPlate=new THREE.Mesh(new THREE.CylinderGeometry(8.2,8.2,.9,96),plateMetal);supportPlate.position.y=0;structureGroup.add(supportPlate);
  for(let i=0;i<12;i++){const a=i/12*Math.PI*2,col=cylinder(.24,3.05,plateDark,16);col.position.set(Math.cos(a)*6.4,-1.65,Math.sin(a)*6.4);structureGroup.add(col)}
  // P4: smaller, darker grid frame at the support-column connection.
  const gridPlate=new THREE.Mesh(new THREE.CylinderGeometry(7.35,7.35,.2,96),plateDark);gridPlate.position.y=-3.05;structureGroup.add(gridPlate);
  const cellFillMaterial=new THREE.MeshBasicMaterial({color:0x70877d,transparent:true,opacity:.08,depthWrite:false,side:THREE.DoubleSide});
  const cellEdgeMaterial=new THREE.LineBasicMaterial({color:0xb8cbc3,transparent:true,opacity:.58});supportMaterials.push(cellFillMaterial,cellEdgeMaterial);
  [1.44,.46,-.46,-3.04].forEach((y,layerIndex)=>POSITIONS.forEach((position,index)=>{const{x,z}=coordinate(position),cell=new THREE.Group();cell.position.set(x,y,z);cell.userData.index=index;cell.userData.layer=layerIndex;const fillMaterial=cellFillMaterial.clone();fillMaterial.opacity=layerIndex===0?.11:.025;fillMaterial.depthWrite=false;const edgeMaterial=cellEdgeMaterial.clone();edgeMaterial.color.set(layerIndex===0?0xd7e9df:layerIndex===1?0xa7c2b8:0x71877e);edgeMaterial.opacity=layerIndex===0?.72:.34;const fill=new THREE.Mesh(new THREE.BoxGeometry(.99,.028,.99),fillMaterial);const edge=new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(.99,.03,.99)),edgeMaterial);cell.add(fill,edge);structureGroup.add(cell);tubeSquareCells.push(cell)}));
  const vesselWall=new THREE.Mesh(new THREE.CylinderGeometry(9.5,9.5,10.6,96,1,true),shellMaterial);vesselWall.position.y=-.3;shellGroup.add(vesselWall);
  const upperHead=new THREE.Mesh(new THREE.SphereGeometry(9.5,96,36,0,Math.PI*2,0,Math.PI/2),shellMaterial);upperHead.scale.y=.38;upperHead.position.y=5;shellGroup.add(upperHead);
  const lowerHead=new THREE.Mesh(new THREE.SphereGeometry(9.5,96,36,0,Math.PI*2,Math.PI/2,Math.PI/2),shellMaterial);lowerHead.scale.y=.38;lowerHead.position.y=-5.6;shellGroup.add(lowerHead);

  [[8.55,1.42,.22],[8.2,0,.5],[7.65,-3.2,.24]].forEach(([radius,y,thickness],plateIndex)=>{
    const boltRadius=radius-.48,boltCount=plateIndex===1?20:16;
    for(let i=0;i<boltCount;i++){const angle=i/boltCount*Math.PI*2,bolt=cylinder(.075,.14,fastenerMetal,16);bolt.position.set(Math.cos(angle)*boltRadius,y+thickness/2+.075,Math.sin(angle)*boltRadius);structureGroup.add(bolt)}
  });
}

function buildThimbles(){
  POSITIONS.forEach((position,index)=>{const{x,z}=coordinate(position),g=new THREE.Group();g.userData={index,position};
    // Keep the overview proportions close to the physical 8.6 mm tube: a slim tube,
    // a visibly larger but translucent guide section, and a compact lower fitting.
    const tubeRadius=.105,straightHeight=EMBEDDED?7.0:13.25,straightCenter=EMBEDDED?-1.15:2.575,tipY=EMBEDDED?2.35:9.2;
    const straight=cylinder(tubeRadius,straightHeight,tubeMaterial,48);straight.position.set(x,straightCenter,z);g.add(straight);
    const tip=new THREE.Mesh(new THREE.SphereGeometry(tubeRadius,44,20,0,Math.PI*2,0,Math.PI/2),tubeMaterial);tip.position.set(x,tipY,z);g.add(tip);
    const guide=new THREE.Mesh(new THREE.CylinderGeometry(.245,.245,6.7,48,1,true),sleeveMaterial);guide.position.set(x,-2.15,z);g.add(guide);
    const nozzle=cylinder(.3,1.15,darkMetal,40);nozzle.position.set(x,-5.5,z);g.add(nozzle);
    const baseFlange=new THREE.Mesh(new THREE.TorusGeometry(.245,.038,12,40),layerRingMaterial);baseFlange.rotation.x=Math.PI/2;baseFlange.position.set(x,-6.12,z);g.add(baseFlange);
    tubesGroup.add(g);tubeGroups.push(g);
  });
}

const numberLabels=[];
const tubeHitMaterial=new THREE.MeshBasicMaterial({transparent:true,opacity:0,depthWrite:false,side:THREE.DoubleSide});
function buildTubeNumbers(){const coreTop=EMBEDDED?2.75:9.32;numberGroup.clear();tubeHitGroup.clear();numberLabels.length=0;POSITIONS.forEach((position,index)=>{const{x,z}=coordinate(position),label=makePlateLabel(String(index+1),.8,.5,'#91a39b',{fontSize:76,background:'rgba(8,13,12,.96)',border:4});label.position.set(x,coreTop,z);label.userData={index,position};label.scale.setScalar(index===selected?1.1:1);label.material.color.set(index===selected?0xd7ef4a:0xffffff);numberGroup.add(label);numberLabels.push(label);const hitArea=new THREE.Mesh(new THREE.PlaneGeometry(1.02,1.02),tubeHitMaterial);hitArea.rotation.x=-Math.PI/2;hitArea.position.set(x,coreTop+.025,z);hitArea.userData={index,position};tubeHitGroup.add(hitArea)})}
function buildOrientation(){orientationGroup.clear();[['180°',0,-11.15],['0°',0,11.15],['90°',-11.15,0],['270°',11.15,0]].forEach(([text,x,z])=>{const marker=makePlateLabel(text,1.82,.62,'#d7ef4a',{fontSize:70,background:'rgba(8,13,12,.82)',border:4});marker.position.set(x,2.25,z);orientationGroup.add(marker)})}

const pointDefinitions=[
  ['P1',1.35,'下栅格板'],['P2',.45,'支撑板上表面'],['P3',-.45,'支撑板下表面'],
  ['P4',-3.05,'支撑柱与格架板'],['P5',-4.55,'支撑柱与RPV管座'],['P6',-5.85,'RPV管座与导向管']
];
function buildSingleTubeModel(){
  singleTubeModelGroup.clear();
  // The radial proportions follow the brief: 8.6 mm OD and 1.7 mm wall.
  // Axial length is intentionally compressed so P1-P6 remain inspectable.
  const outerRadius=.14,wall=.14*(1.7/4.3),innerRadius=outerRadius-wall;
  const body=new THREE.Mesh(new THREE.CylinderGeometry(outerRadius,outerRadius,8.8,64),tubeMaterial);body.position.y=-2.15;singleTubeModelGroup.add(body);
  const bulletTip=new THREE.Mesh(new THREE.SphereGeometry(outerRadius,48,20,0,Math.PI*2,0,Math.PI/2),tubeMaterial);bulletTip.position.y=2.25;singleTubeModelGroup.add(bulletTip);
  const lowerSocket=cylinder(.19,.42,darkMetal,48);lowerSocket.position.y=-6.59;singleTubeModelGroup.add(lowerSocket);
  const socketBore=cylinder(innerRadius,.012,darkMetal,40);socketBore.position.y=-6.805;singleTubeModelGroup.add(socketBore);
  const lowerFlange=new THREE.Mesh(new THREE.TorusGeometry(.205,.045,14,56),layerRingMaterial);lowerFlange.rotation.x=Math.PI/2;lowerFlange.position.y=-6.38;singleTubeModelGroup.add(lowerFlange);
  pointDefinitions.forEach(([zone,y])=>{
    const ring=new THREE.Mesh(new THREE.TorusGeometry(.18,.032,12,56),layerRingMaterial);
    ring.rotation.x=Math.PI/2;ring.position.y=y;ring.userData.zone=zone;singleTubeModelGroup.add(ring);
    const band=new THREE.Mesh(new THREE.CylinderGeometry(.155,.155,.065,56),layerRingMaterial);band.position.y=y;singleTubeModelGroup.add(band);
  });
  singleTubeModelGroup.visible=false;
}
function buildPointLabels(){
  labelsGroup.clear();
  pointDefinitions.forEach(([p,y])=>{const color=layerAccent;
    [[1,0],[-1,0],[0,1],[0,-1]].forEach(([dx,dz])=>{const radial=9.15,labelRadius=10.15,horizontal=dx!==0;
      const line=new THREE.Mesh(horizontal?new THREE.BoxGeometry(1.25,.032,.032):new THREE.BoxGeometry(.032,.032,1.25),new THREE.MeshBasicMaterial({color,depthTest:false}));line.position.set(dx*radial,y,dz*radial);line.renderOrder=18;labelsGroup.add(line);
      const sprite=makeLabel(p,color);sprite.position.set(dx*labelRadius,y,dz*labelRadius);sprite.scale.set(.9,.36,1);labelsGroup.add(sprite)
    })
  })
}
function buildSingleTubeLabels(){
  singleTubeLabelsGroup.clear();
  const {x,z}=coordinate(POSITIONS[selected]);
  pointDefinitions.forEach(([p,y])=>{
    const color=layerAccent;
    const guide=new THREE.Mesh(new THREE.BoxGeometry(.75,.025,.025),new THREE.MeshBasicMaterial({color,depthTest:false}));
    guide.position.set(x+.55,y,z);guide.renderOrder=24;singleTubeLabelsGroup.add(guide);
    const label=makeLabel(p,color);label.position.set(x+1.2,y,z);label.scale.set(.75,.3,1);label.renderOrder=25;singleTubeLabelsGroup.add(label);
  });
}

function buildSelectedTubeHighlight(){
  selectedTubeHighlightGroup.clear();
  const glowMaterial=new THREE.MeshBasicMaterial({color:0xd7ef4a,transparent:true,opacity:.26,depthWrite:false,depthTest:false,blending:THREE.AdditiveBlending});
  const glow=new THREE.Mesh(new THREE.CylinderGeometry(.24,.24,7.15,48,1,true),glowMaterial);glow.position.y=-1.15;glow.renderOrder=14;selectedTubeHighlightGroup.add(glow);
  const cap=new THREE.Mesh(new THREE.SphereGeometry(.25,32,16,0,Math.PI*2,0,Math.PI/2),glowMaterial);cap.position.y=2.42;cap.renderOrder=14;selectedTubeHighlightGroup.add(cap);
  const light=new THREE.PointLight(0xd7ef4a,1.3,2.8,2);light.position.y=.3;selectedTubeHighlightGroup.add(light);
}

function addValve(group,x,label,automatic=false){
  const body=horizontalCylinder(.42,1.05,darkMetal);body.position.set(x,-6.75,0);group.add(body);
  const flangeA=horizontalCylinder(.58,.16,metal),flangeB=horizontalCylinder(.58,.16,metal);flangeA.position.set(x-.52,-6.75,0);flangeB.position.set(x+.52,-6.75,0);group.add(flangeA,flangeB);
  const stem=cylinder(.12,.75,metal,14);stem.position.set(x,-6.2,0);group.add(stem);
  const actuator=new THREE.Mesh(new THREE.BoxGeometry(automatic?1.1:.72,automatic?.8:.18,.72),darkMetal);actuator.position.set(x,automatic?-5.6:-5.8,0);group.add(actuator);
  const tag=makeLabel(label);tag.position.set(x,-7.65,0);group.add(tag);
}
function buildExternalPath(){
  externalGroup.clear();const{x,z}=coordinate(POSITIONS[selected]);
  const route=tubeFrom([new THREE.Vector3(x,-5.7,z),new THREE.Vector3(x,-6.3,z),new THREE.Vector3(x+.5,-6.75,z*.65),new THREE.Vector3(11,-6.75,0),new THREE.Vector3(25,-6.75,0)],.11,signalMaterial,72);
  const guide=tubeFrom([new THREE.Vector3(x,-5.7,z),new THREE.Vector3(x,-6.3,z),new THREE.Vector3(x+.5,-6.75,z*.65),new THREE.Vector3(11,-6.75,0),new THREE.Vector3(25,-6.75,0)],.28,sleeveMaterial,72);externalGroup.add(guide);externalGroup.add(route);
  addValve(externalGroup,13.2,'手动隔离阀');
  const seal=horizontalCylinder(.52,2.2,darkMetal);seal.position.set(16.2,-6.75,0);externalGroup.add(seal);const sealTag=makeLabel('密封组件');sealTag.position.set(16.2,-7.65,0);externalGroup.add(sealTag);
  addValve(externalGroup,19.2,'球形逆止阀');addValve(externalGroup,22.7,'自动阀',true);
  const drive=new THREE.Mesh(new THREE.BoxGeometry(1.7,1.35,1.25),darkMetal);drive.position.set(25,-6.75,0);externalGroup.add(drive);const driveTag=makeLabel('传送装置');driveTag.position.set(25,-7.65,0);externalGroup.add(driveTag);
}

buildCore();buildInternalStructures();buildThimbles();buildSingleTubeModel();buildSelectedTubeHighlight();buildTubeNumbers();buildOrientation();buildPointLabels();buildSingleTubeLabels();labelsGroup.visible=false;singleTubeLabelsGroup.visible=false;externalGroup.visible=externalVisible;shellGroup.visible=shellVisible;
const detector=cylinder(.05,.7,signalMaterial,14);root.add(detector);const detectorGlow=new THREE.PointLight(0xd7ef4a,0,3);root.add(detectorGlow);
detector.visible=!EMBEDDED;detectorGlow.visible=!EMBEDDED;
const defectMaterial=new THREE.MeshStandardMaterial({color:0xe45b4e,emissive:0x7a1912,emissiveIntensity:1.15,metalness:.22,roughness:.26});
const defectPreview=new THREE.Mesh(new THREE.SphereGeometry(1,24,16),defectMaterial);root.add(defectPreview);
defectPreview.visible=!EMBEDDED;

function updateDepth(){const value=+document.querySelector('#detectorDepth').value,y=-3.95+value/100*13.5;detector.position.y=y;detectorGlow.position.y=y;document.querySelector('#depthOutput').textContent=`${Math.round(value)}%`}
function setSelected(index){selected=Math.max(0,Math.min(49,index));tubeGroups.forEach((g,i)=>{g.visible=currentCamera!=='tube'||i===selected;g.children.forEach(m=>{if(m.material===tubeMaterial||m.material===signalMaterial)m.material=i===selected?signalMaterial:tubeMaterial})});numberLabels.forEach((label,i)=>{label.scale.setScalar(i===selected?1.18:1);label.material.color.set(i===selected?0xd7ef4a:0xffffff)});const pos=POSITIONS[selected],{x,z}=coordinate(pos);singleTubeModelGroup.position.set(x,0,z);selectedTubeHighlightGroup.position.set(x,0,z);detector.position.x=x;detector.position.z=z;detectorGlow.position.x=x;detectorGlow.position.z=z;document.querySelector('#tubeSelect').value=selected+1;document.querySelector('#tubeOutput').textContent=String(selected+1).padStart(2,'0');const embeddedTube=document.querySelector('#embeddedTubeSelect');if(embeddedTube){embeddedTube.value=selected+1;document.querySelector('#embeddedTubeOutput').textContent=String(selected+1).padStart(2,'0')}document.querySelector('#objectName').textContent=`指套管 #${String(selected+1).padStart(2,'0')}`;document.querySelector('#position').textContent=pos;buildSingleTubeLabels();buildExternalPath();updateDepth();updateArtificialDefect();updateSelectedTubeDetails();if(currentCamera==='tube')setCamera('tube')}

function updateArtificialDefect(){
  const zone=document.querySelector('#layerSelect')?.value||'P1';
  const offset=Math.max(0,Math.min(400,Number(document.querySelector('#offsetInput')?.value||0)));
  const layerIndex=Math.max(0,pointDefinitions.findIndex(item=>item[0]===zone));
  const base=pointDefinitions[layerIndex][1],next=pointDefinitions[layerIndex+1]?.[1]??-6.35;
  const {x,z}=coordinate(POSITIONS[selected]);defectPreview.position.set(x,base-(offset/400)*(base-next),z);
  const size=Number(document.querySelector('#defectSize')?.value||11);defectPreview.scale.setScalar(size/70);
  const color=document.querySelector('#defectColor')?.value||'#e45b4e';defectMaterial.color.set(color);defectMaterial.emissive.set(color);
  document.querySelector('#defectSummary').textContent=`${String(selected+1).padStart(2,'0')}号管 · ${zone} + ${offset} mm`;
  document.querySelector('#defectSizeOutput').textContent=String(size);
}

function applyParity(value){
  POSITIONS=value==='even'?EVEN_POSITIONS:ODD_POSITIONS;
  tubeGroups.forEach((group,index)=>{const {x,z}=coordinate(POSITIONS[index]);group.userData.position=POSITIONS[index];group.children.forEach(mesh=>{mesh.position.x=x;mesh.position.z=z})});
  tubeSquareCells.forEach(cell=>{const {x,z}=coordinate(POSITIONS[cell.userData.index]);cell.position.x=x;cell.position.z=z});
  buildTubeNumbers();
  setSelected(selected);
}

function isDefect(row){const indication=String(row.indication||'').trim().toUpperCase(),percent=Number(row.percent);return Boolean(indication)&&!['NDD','NONE','NO DEFECT'].includes(indication)&&Number.isFinite(percent)&&percent>0}
function escapeHtml(value){return String(value??'').replace(/[&<>"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[char]))}
function updateSelectedTubeDetails(){
  const host=document.querySelector('#selectedTubeDetails');if(!host)return;
  const records=workspaceRows.filter(row=>Number(row.thimble_id)===selected+1);
  if(!records.length){host.className='inspection-empty';host.textContent='当前筛选无检测记录';return}
  const defects=records.filter(isDefect),maxPercent=Math.max(0,...defects.map(row=>Number(row.percent)||0));
  const summary=defects.length?`发现 ${defects.length} 条缺陷 · 最大磨损 ${maxPercent}%`:'无有效缺陷';
  const recordHtml=records.map((row,index)=>{const defect=isDefect(row),percent=defect?`${Number(row.percent)}%`:'--',note=[row.comment,row.analysis].filter(Boolean).join('；')||'--',fields=[['大修批次',row.outage||'--'],['磨损位置',row.location||'--'],['测量通道',row.channel||'--'],['幅值',row.volts==null?'--':`${row.volts} V`],['相位',row.degrees==null?'--':`${row.degrees}°`],['分析人员',row.analyst||'--'],['数据组',row.calgroup||'--'],['数据文件',row.filename||'--'],['备注',note]];return `<details class="inspection-record${defect?' has-defect':''}" ${index===0?'open':''}><summary><i>${String(index+1).padStart(2,'0')}</i><b>${escapeHtml(row.indication||'NDD')} · ${escapeHtml(percent)}</b><span>${escapeHtml(row.location||'无磨损位置')}</span><small>${index+1}/${records.length}</small></summary><dl>${fields.map(([label,value])=>`<div><dt>${label}</dt><dd title="${escapeHtml(value)}">${escapeHtml(value)}</dd></div>`).join('')}</dl></details>`}).join('');
  host.className='inspection-list';host.innerHTML=`<div class="inspection-summary"><b>${selected+1}号管 · ${escapeHtml(POSITIONS[selected])}</b><span>${escapeHtml(summary)}</span></div><div class="inspection-list-actions"><button type="button" data-record-action="expand">全部展开</button><button type="button" data-record-action="collapse">全部收起</button></div><div class="inspection-records">${recordHtml}</div>`;
  host.querySelector('[data-record-action="expand"]')?.addEventListener('click',()=>host.querySelectorAll('.inspection-record').forEach(record=>record.open=true));
  host.querySelector('[data-record-action="collapse"]')?.addEventListener('click',()=>host.querySelectorAll('.inspection-record').forEach(record=>record.open=false));
}
function defectY(location){const match=String(location||'').match(/(P[1-6])(?:\s*\+\s*([-+]?\d+(?:\.\d+)?))?/i),zone=(match?.[1]||'P3').toUpperCase(),offset=Math.max(0,Math.min(400,Number(match?.[2]||0))),index=Math.max(0,pointDefinitions.findIndex(item=>item[0]===zone)),base=pointDefinitions[index][1],next=pointDefinitions[index+1]?.[1]??-6.35;return base-(offset/400)*(base-next)}
function defectStyle(percent){const mid=Math.max(0,Math.min(100,Number(localStorage.getItem('thimbleSeverityMidThreshold')||20))),high=Math.max(mid,Math.min(100,Number(localStorage.getItem('thimbleSeverityHighThreshold')||40))),color=key=>{const value=localStorage.getItem(key);return /^#[0-9a-f]{6}$/i.test(value||'')?value:null};const hex=percent>=high?(color('thimbleSeverityHighColor')||'#df4b45'):percent>=mid?(color('thimbleSeverityMidColor')||'#e5a83b'):(color('thimbleSeverityLowColor')||'#79b98c');return{color:new THREE.Color(hex),radius:.17+Math.min(.10,Math.max(0,percent)/100*.10)}}
function renderDataDefects(rows=[]){
  dataDefectsGroup.clear();const grouped=new Map();rows.filter(isDefect).forEach(row=>{const key=`${row.thimble_id}|${row.location}`;if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(row)});
  grouped.forEach(records=>{const row=records.reduce((best,item)=>Number(item.percent||0)>Number(best.percent||0)?item:best,records[0]),position=row.position||POSITIONS[Number(row.thimble_id)-1],{x,z}=coordinate(position),percent=Number(row.percent||0),style=defectStyle(percent),point=new THREE.Mesh(new THREE.SphereGeometry(style.radius,18,12),new THREE.MeshStandardMaterial({color:style.color,emissive:style.color,emissiveIntensity:.85}));point.position.set(x,defectY(row.location),z);point.userData={records,id:Number(row.thimble_id),position};point.visible=currentCamera!=='tube'||Number(row.thimble_id)===selected+1;dataDefectsGroup.add(point)});
  return grouped.size;
}
function renderEvolution(rows=[]){
  evolutionGroup.clear();const outages=[...new Set(rows.map(row=>String(row.outage||'未标注大修')))].sort((a,b)=>a.localeCompare(b,'zh-CN',{numeric:true}));
  outages.forEach((outage,index)=>{const y=(outages.length-1-index)*1.8,grid=new THREE.GridHelper(18,15,0x596961,0x25332e);grid.position.y=y;grid.material.transparent=true;grid.material.opacity=.45;evolutionGroup.add(grid);const label=makeLabel(outage,'#d7ef4a');label.position.set(-10,y+.2,-10);label.scale.set(2.5,.42,1);evolutionGroup.add(label);rows.filter(row=>String(row.outage||'未标注大修')===outage&&isDefect(row)).forEach(row=>{const position=row.position||POSITIONS[Number(row.thimble_id)-1];if(!position)return;const{x,z}=coordinate(position),style=defectStyle(Number(row.percent||0)),point=new THREE.Mesh(new THREE.SphereGeometry(style.radius,18,12),new THREE.MeshStandardMaterial({color:style.color,emissive:style.color,emissiveIntensity:.75}));point.position.set(x,y+.18,z);point.userData={id:Number(row.thimble_id),records:[row],position,outage};evolutionGroup.add(point)})});
}

let scopeRequest=0;
async function fetchScopeRows(scope,request){
  const unit=Number(scope.unit||0);if(!unit)return[];
  const rows=[];let page=1,pages=1;
  do{const params=new URLSearchParams({page:String(page),size:'200',unit:String(unit)});if(scope.site)params.set('site',scope.site);if(scope.outage)params.set('outage',scope.outage);const response=await fetch(`/api/findings?${params}`);const data=await response.json();if(request!==scopeRequest)return null;rows.push(...(data.items||[]));pages=Number(data.pages||1);page++}while(page<=pages);
  return rows;
}
async function applyWorkspaceScope(scope={}){
  const request=++scopeRequest,unit=Number(scope.unit||0);if(unit){const parity=unit%2?'odd':'even';document.querySelector('#paritySelect').value=parity;applyParity(parity)}
  const rows=await fetchScopeRows(scope,request);if(rows===null||request!==scopeRequest)return;
  const outages=new Set(rows.map(row=>String(row.outage||'')));if(!scope.outage&&outages.size>1){workspaceRows=[];renderDataDefects([]);renderEvolution([]);updateSelectedTubeDetails();const status=document.querySelector('.status span');if(status)status.textContent='请选择单一大修批次查看三维缺陷';return}
  workspaceRows=rows;const selectedHasDefect=workspaceRows.some(row=>Number(row.thimble_id)===selected+1&&isDefect(row)),firstDefect=workspaceRows.find(isDefect);if(!selectedHasDefect&&firstDefect)setSelected(Number(firstDefect.thimble_id)-1);const defectPoints=renderDataDefects(workspaceRows);renderEvolution(workspaceRows);updateSelectedTubeDetails();const status=document.querySelector('.status span');if(status)status.textContent=`${scope.outage||'当前大修'} · ${workspaceRows.length} 条记录 · ${defectPoints} 个缺陷位置`;
}

window.addEventListener('message',event=>{if(event.origin!==location.origin)return;const message=event.data||{};if(message.type==='thimble-scope')applyWorkspaceScope(message.scope);if(message.type==='thimble-focus'){setSelected(Number(message.thimble||1)-1)}});
setSelected(0);

const presets={overview:{p:EMBEDDED?[34,13,42]:[43,22,49],t:EMBEDDED?[0,-.8,0]:[0,0,0]},section:{p:[27,4,31],t:[0,-2.1,0]},plate:{p:[0,44,3.2],t:[0,-.6,0]},tube:{p:[28,2,22],t:[9,-2.2,0]},evolution:{p:[25,19,27],t:[0,2,0]}};
 function setCamera(name){currentCamera=name;const single=name==='tube';let preset=presets[name];if(single){const{x,z}=coordinate(POSITIONS[selected]);preset={p:[x+9,2,z+12],t:[x,-1.2,z]}}camera.up.set(0,1,0);tubeGroups.forEach((g,i)=>g.visible=!single||i===selected);selectedTubeHighlightGroup.visible=!single;coreGroup.visible=!single&&coreVisible;structureGroup.visible=!single&&structureVisible;shellGroup.visible=!single&&shellVisible;externalGroup.visible=!single&&externalVisible;labelsGroup.visible=false;singleTubeLabelsGroup.visible=single&&labelsVisible;numberGroup.visible=!single&&numbersVisible;tubeHitGroup.visible=!single;orientationGroup.visible=!single&&orientationVisible;dataDefectsGroup.children.forEach(point=>point.visible=!single||Number(point.userData.id)===selected+1);const picker=document.querySelector('#singleTubePicker');if(picker)picker.hidden=false;const layerButton=document.querySelector('[data-visibility="labels"]');if(layerButton)layerButton.hidden=!single;cameraTween={start:performance.now(),fromP:camera.position.clone(),fromT:controls.target.clone(),toP:new THREE.Vector3(...preset.p),toT:new THREE.Vector3(...preset.t)};document.querySelectorAll('[data-camera],[data-embedded-view]').forEach(b=>b.classList.toggle('active',(b.dataset.camera||b.dataset.embeddedView)===name))}
const physicalSetCamera=setCamera;
setCamera=function(name){
  if(name==='evolution'){
    currentCamera='evolution';evolutionGroup.visible=true;singleTubeModelGroup.visible=false;selectedTubeHighlightGroup.visible=false;coreGroup.visible=false;tubesGroup.visible=false;structureGroup.visible=false;shellGroup.visible=false;labelsGroup.visible=false;singleTubeLabelsGroup.visible=false;numberGroup.visible=false;tubeHitGroup.visible=false;orientationGroup.visible=false;dataDefectsGroup.visible=false;const preset=presets.evolution;cameraTween={start:performance.now(),fromP:camera.position.clone(),fromT:controls.target.clone(),toP:new THREE.Vector3(...preset.p),toT:new THREE.Vector3(...preset.t)};document.querySelectorAll('[data-camera],[data-embedded-view]').forEach(b=>b.classList.toggle('active',(b.dataset.camera||b.dataset.embeddedView)===name));return;
  }
  if(name==='tube'&&currentCamera==='tube'){
    const {x,z}=coordinate(POSITIONS[selected]),offset=camera.position.clone().sub(controls.target);tubeGroups.forEach(group=>group.visible=false);singleTubeModelGroup.visible=true;controls.target.set(x,-2.15,z);camera.position.set(x+offset.x, -2.15+offset.y, z+offset.z);document.querySelectorAll('[data-camera],[data-embedded-view]').forEach(b=>b.classList.toggle('active',(b.dataset.camera||b.dataset.embeddedView)===name));return;
  }
  evolutionGroup.visible=false;physicalSetCamera(name);singleTubeModelGroup.visible=name==='tube';if(name==='tube'){tubeGroups.forEach(group=>group.visible=false);if(cameraTween){const{x,z}=coordinate(POSITIONS[selected]);cameraTween.toT.set(x,-2.15,z)}}
};
function enter(){document.querySelector('.intro').classList.add('dismissed');document.querySelector('.inspector').classList.add('visible')}
function resize(){const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix()}new ResizeObserver(resize).observe(host);resize();

 const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2();let clickStart=null;
 function updateDefectTooltip(event){
   const rect=renderer.domElement.getBoundingClientRect();
   pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
   raycaster.setFromCamera(pointer,camera);
   const hit=raycaster.intersectObjects([dataDefectsGroup],true)[0];
   if(!hit||!hit.object.userData.records?.length){defectTooltip.hidden=true;return}
   const records=hit.object.userData.records, row=records.reduce((best,item)=>Number(item.percent||0)>Number(best.percent||0)?item:best,records[0]);
   const percent=Number(row.percent);
   defectTooltip.innerHTML=`<b>Tube ${String(hit.object.userData.id).padStart(2,'0')} · ${escapeHtml(hit.object.userData.position||'--')}</b><br>Indication: ${escapeHtml(row.indication||'--')} · Max wear: ${Number.isFinite(percent)?percent+'%':'--'}<br>Location: ${escapeHtml(row.location||'--')} · Channel: ${escapeHtml(row.channel||'--')}<br>Records: ${records.length} · Analyst: ${escapeHtml(row.analyst||'--')}`;
   defectTooltip.hidden=false;
   defectTooltip.style.left=`${Math.min(event.clientX+14,window.innerWidth-430)}px`;
   defectTooltip.style.top=`${Math.min(event.clientY+14,window.innerHeight-96)}px`;
 }
 renderer.domElement.addEventListener('pointermove',updateDefectTooltip);
 renderer.domElement.addEventListener('pointerleave',()=>{defectTooltip.hidden=true});
renderer.domElement.addEventListener('pointerdown',event=>{if(event.button===0)clickStart={x:event.clientX,y:event.clientY}});
renderer.domElement.addEventListener('pointerup',event=>{if(event.button!==0||!clickStart)return;const distance=Math.hypot(event.clientX-clickStart.x,event.clientY-clickStart.y);clickStart=null;if(distance>5)return;const r=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);const hit=raycaster.intersectObjects([dataDefectsGroup,tubeHitGroup,numberGroup,tubesGroup],true)[0];if(!hit)return;let object=hit.object;if(object.userData.id!==undefined){setSelected(Number(object.userData.id)-1);window.parent!==window&&window.parent.postMessage({type:'thimble-selected',thimble:selected+1,position:POSITIONS[selected]},location.origin);return}while(object.parent&&object.userData.index===undefined)object=object.parent;if(object.userData.index!==undefined){setSelected(object.userData.index);window.parent!==window&&window.parent.postMessage({type:'thimble-selected',thimble:selected+1,position:POSITIONS[selected]},location.origin)}});
renderer.domElement.addEventListener('dblclick',event=>{
  const r=renderer.domElement.getBoundingClientRect();
  pointer.set((event.clientX-r.left)/r.width*2-1,-(event.clientY-r.top)/r.height*2+1);
  raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects([tubeHitGroup,numberGroup,tubesGroup],true)[0];
  let object=hit?.object;
  while(object&&object.userData.index===undefined)object=object.parent;
  if(object?.userData?.index!==undefined){
    setSelected(object.userData.index);
    setCamera('tube');
    notifyParentSelection();
    return;
  }
  setCamera('plate');
});
document.querySelector('#enter').onclick=()=>{enter();setCamera('overview')};
document.querySelectorAll('[data-camera]').forEach(b=>b.onclick=()=>{enter();setCamera(b.dataset.camera)});
document.querySelectorAll('[data-embedded-view]').forEach(button=>button.onclick=()=>setCamera(button.dataset.embeddedView));
document.querySelector('[data-embedded-view="evolution"]')?.addEventListener('click',async()=>{const unit=Number(workspaceRows[0]?.unit_id||0);if(!unit){document.querySelector('.status span')?.replaceChildren(document.createTextNode('请先在工作台选择机组'));return}try{const params=new URLSearchParams({unit:String(unit),size:'200'}),response=await fetch(`/api/findings?${params}`),data=await response.json();renderEvolution(data.items||workspaceRows);setCamera('evolution')}catch(error){document.querySelector('.status span')?.replaceChildren(document.createTextNode('历次演变加载失败'))}});
document.querySelectorAll('[data-visibility]').forEach(button=>button.onclick=()=>{const target=button.dataset.visibility;if(target==='shell'){shellVisible=!shellVisible;shellGroup.visible=currentCamera!=='tube'&&shellVisible}if(target==='core'){coreVisible=!coreVisible;coreGroup.visible=currentCamera!=='tube'&&coreVisible}if(target==='structure'){structureVisible=!structureVisible;structureGroup.visible=currentCamera!=='tube'&&structureVisible}if(target==='external'){externalVisible=!externalVisible;externalGroup.visible=currentCamera!=='tube'&&externalVisible}if(target==='numbers'){numbersVisible=!numbersVisible;numberGroup.visible=currentCamera!=='tube'&&numbersVisible}if(target==='labels'){labelsVisible=!labelsVisible;labelsGroup.visible=false;singleTubeLabelsGroup.visible=currentCamera==='tube'&&labelsVisible}if(target==='orientation'){orientationVisible=!orientationVisible;orientationGroup.visible=currentCamera!=='tube'&&orientationVisible}button.classList.toggle('active',({shell:shellVisible,core:coreVisible,structure:structureVisible,external:externalVisible,numbers:numbersVisible,labels:labelsVisible,orientation:orientationVisible})[target])});
function notifyParentSelection(){window.parent!==window&&window.parent.postMessage({type:'thimble-selected',thimble:selected+1,position:POSITIONS[selected]},location.origin)}
document.querySelector('#tubeSelect').oninput=e=>{setSelected(+e.target.value-1);notifyParentSelection()};document.querySelector('#embeddedTubeSelect')?.addEventListener('input',e=>{setSelected(+e.target.value-1);notifyParentSelection()});document.querySelector('#detectorDepth').oninput=updateDepth;
document.querySelector('#paritySelect').onchange=e=>applyParity(e.target.value);
document.querySelector('#layerSelect').onchange=updateArtificialDefect;document.querySelector('#offsetInput').oninput=updateArtificialDefect;document.querySelector('#defectColor').oninput=updateArtificialDefect;document.querySelector('#defectSize').oninput=updateArtificialDefect;
document.querySelector('#coreOpacity').oninput=e=>{fuelMaterial.opacity=Number(e.target.value)/100;document.querySelector('#coreOpacityOutput').textContent=`${e.target.value}%`};
document.querySelector('#plateOpacity').oninput=e=>{const opacity=Number(e.target.value)/100;supportMaterials.forEach(material=>{material.transparent=opacity<1;material.opacity=opacity;material.depthWrite=opacity>=1;material.needsUpdate=true});document.querySelector('#plateOpacityOutput').textContent=`${e.target.value}%`};
document.querySelector('#toggleCore').onclick=e=>{coreVisible=!coreVisible;coreGroup.visible=currentCamera!=='tube'&&coreVisible;e.currentTarget.classList.toggle('active',coreVisible)};
document.querySelector('#toggleLabels').onclick=e=>{labelsVisible=!labelsVisible;labelsGroup.visible=false;singleTubeLabelsGroup.visible=currentCamera==='tube'&&labelsVisible;e.currentTarget.classList.toggle('active',labelsVisible)};
document.querySelector('#toggleOrientation').onclick=e=>{orientationVisible=!orientationVisible;orientationGroup.visible=orientationVisible;e.currentTarget.classList.toggle('active',orientationVisible)};
document.querySelector('#toggleDefect').onclick=e=>{defectPreview.visible=!defectPreview.visible;e.currentTarget.classList.toggle('active',defectPreview.visible)};
document.querySelector('#autoScan').onclick=e=>{scanning=!scanning;e.currentTarget.classList.toggle('active',scanning)};

enter();updateArtificialDefect();
let frames=0,lastFps=performance.now();function animate(now){if(cameraTween){const t=Math.min(1,(now-cameraTween.start)/850),e=1-Math.pow(1-t,3);camera.position.lerpVectors(cameraTween.fromP,cameraTween.toP,e);controls.target.lerpVectors(cameraTween.fromT,cameraTween.toT,e);if(t===1)cameraTween=null}if(scanning){const value=(Math.sin(now*.0012)*.5+.5)*100;document.querySelector('#detectorDepth').value=value;updateDepth()}controls.update();renderer.render(scene,camera);frames++;if(now-lastFps>1000){document.querySelector('#fps').textContent=`${frames} FPS`;frames=0;lastFps=now}requestAnimationFrame(animate)}requestAnimationFrame(animate);
