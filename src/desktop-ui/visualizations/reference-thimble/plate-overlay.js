import * as THREE from 'three';

export class PlateOverlay {
  constructor(scene, vessel, invalidate) {
    this.scene = scene;
    this.vessel = vessel;
    this.invalidate = invalidate;
    this.visible = false;
    this.numbering = 'all';
    this.position = '';
    this.projectionMirror = false;
    this.mesh = null;
    this.svg = null;
    this.revision = 0;
    this.pending = null;
    this.anchors = [];
  }

  async load() {
    if (this.pending) return this.pending;
    if (this.svg) return;
    this.pending = this.loadDrawing();
    try { await this.pending; }
    catch (error) {
      this.mesh?.removeFromParent();
      this.mesh?.geometry.dispose(); this.mesh?.material.map?.dispose(); this.mesh?.material.dispose();
      this.mesh = null; this.svg = null; this.anchors = [];
      throw error;
    } finally { this.pending = null; }
  }

  async loadDrawing() {
    const response = await fetch('./data/plate_plan.svg', {cache:'no-cache'});
    if (!response.ok) throw new Error(`管板图加载失败（${response.status}）`);
    const document = new DOMParser().parseFromString(await response.text(), 'image/svg+xml');
    if (document.querySelector('parsererror')) throw new Error('管板图格式无效');
    this.svg = document.documentElement;
    const ns = this.svg.namespaceURI;
    this.anchors = [...this.svg.querySelectorAll('g.thimble')].map(group => {
      const circle = group.querySelector('circle');
      return {position:group.dataset.pos, x:Number(circle.getAttribute('cx')), y:Number(circle.getAttribute('cy')),
        channel:this.vessel.channels.find(channel => channel.pos === group.dataset.pos)};
    }).filter(anchor => anchor.channel);
    if (this.anchors.length !== 50) throw new Error('管板孔位数量不完整');
    const p = this.anchors[0], q = this.anchors.find(point => Math.hypot(point.x-p.x,point.y-p.y)>1);
    const r = this.anchors.find(point => Math.abs((q.x-p.x)*(point.y-p.y)-(point.x-p.x)*(q.y-p.y))>1);
    const determinant = (q.x-p.x)*(r.y-p.y)-(r.x-p.x)*(q.y-p.y);
    const solve = key => {
      const a = ((q.channel[key]-p.channel[key])*(r.y-p.y)-(r.channel[key]-p.channel[key])*(q.y-p.y))/determinant;
      const b = ((q.x-p.x)*(r.channel[key]-p.channel[key])-(r.x-p.x)*(q.channel[key]-p.channel[key]))/determinant;
      return [a,b,p.channel[key]-a*p.x-b*p.y];
    };
    const [a,b,c] = solve('x'), [d,e,f] = solve('z');
    this.height = Math.max(...this.vessel.channels.map(channel => channel.yTop)) + 18;
    this.worldPoint = (x,y) => new THREE.Vector3(a*x+b*y+c,this.height,d*x+e*y+f);
    // Keep the drawing grid, row/column labels, holes and direction arrows.
    // The paper, title and side legend are not part of the model plane.
    for (const node of [...this.svg.children]) {
      const x = Number(node.getAttribute('x') ?? node.getAttribute('x1') ?? node.getAttribute('cx') ?? 0);
      const y = Number(node.getAttribute('y') ?? node.getAttribute('y1') ?? 96);
      if (node.matches('g.thimble,rect[fill="none"],path') || (x <= 1000 && y >= 96 && y <= 1040)) continue;
      node.remove();
    }
    this.svg.querySelector('rect[width="100%"]')?.remove();
    this.svg.setAttribute('viewBox','0 96 1060 960');
    this.svg.setAttribute('width','2120');
    this.svg.setAttribute('height','1920');
    // The source drawing uses the opposite horizontal convention to model X.
    // Reverse glyphs locally, keeping all hole/grid coordinates unchanged.
    if (a*e-b*d < 0) {
      this.svg.querySelectorAll('text').forEach(text => {
        const x = Number(text.getAttribute('x'));
        text.setAttribute('transform',`translate(${2*x} 0) scale(-1 1)`);
      });
    }
    const background = document.createElementNS(ns,'g');
    background.setAttribute('opacity','.5');
    for (const rect of this.svg.querySelectorAll('rect[fill="none"]')) {
      const cell = rect.cloneNode();
      cell.setAttribute('fill','#f7fafc'); cell.setAttribute('stroke','none');
      background.append(cell);
      rect.setAttribute('stroke','#516a80'); rect.setAttribute('stroke-width','1.6');
    }
    this.svg.prepend(background);
    const corners = [[0,96],[1060,96],[0,1056],[1060,1056]].map(([x,y])=>this.worldPoint(x,y));
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(corners.flatMap(point=>point.toArray()),3));
    geometry.setAttribute('uv',new THREE.Float32BufferAttribute([0,1,1,1,0,0,1,0],2));
    geometry.setIndex([0,1,2,2,1,3]); geometry.computeVertexNormals();
    const material = new THREE.MeshBasicMaterial({transparent:true,side:THREE.DoubleSide,depthWrite:false,
      depthTest:true,toneMapped:false,polygonOffset:true,polygonOffsetFactor:-1});
    this.mesh = new THREE.Mesh(geometry,material);
    this.mesh.name = 'reference-tube-plate';
    this.mesh.userData.kind = 'drawing-overlay';
    this.mesh.renderOrder = 4;
    this.mesh.visible = false;
    this.mesh.raycast = () => {};
    this.scene.add(this.mesh);
    await this.renderTexture();
  }

  async renderTexture() {
    if (!this.svg || !this.mesh) return;
    const revision = ++this.revision;
    const drawing = this.svg.cloneNode(true);
    if (this.projectionMirror) drawing.querySelectorAll('text').forEach(text=>text.removeAttribute('transform'));
    for (const group of drawing.querySelectorAll('g.thimble')) {
      const anchor = this.anchors.find(item=>item.position===group.dataset.pos);
      const labels = [...group.querySelectorAll('text')];
      if (this.numbering !== 'all') {
        const keep = labels[this.numbering==='even' ? 1 : 0];
        labels.filter(label=>label!==keep).forEach(label=>label.remove());
        group.querySelector('line')?.remove();
        keep.setAttribute('x',String(anchor.x));
        keep.setAttribute('font-size','21'); keep.setAttribute('font-weight','700');
        if (!this.projectionMirror) keep.setAttribute('transform',`translate(${2*anchor.x} 0) scale(-1 1)`);
      }
      if (group.dataset.pos === this.position) {
        const circle = group.querySelector('circle');
        circle.setAttribute('fill','#ffe09b'); circle.setAttribute('stroke','#b35e00'); circle.setAttribute('stroke-width','4');
      }
    }
    const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(new XMLSerializer().serializeToString(drawing))}`;
    const image = new Image();
    await new Promise((resolve,reject) => { image.onload=resolve;image.onerror=()=>reject(new Error('管板纹理加载失败'));image.src=url; });
    if (revision !== this.revision) return;
    this.renderedSvg = drawing;
    const canvas = document.createElement('canvas'); canvas.width=2120;canvas.height=1920;
    canvas.getContext('2d').drawImage(image,0,0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 4;
    this.mesh.material.map?.dispose(); this.mesh.material.map=texture;
    this.mesh.material.needsUpdate=true;
    this.mesh.visible = this.visible;
    this.invalidate();
  }

  async update(visible, unit, position, projectionMirror = false) {
    this.visible = Boolean(visible);
    const numbering = Number(unit)>0 ? (Number(unit)%2 ? 'odd' : 'even') : 'all';
    const changed = this.numbering !== numbering || this.position !== (position || '') || this.projectionMirror !== projectionMirror;
    this.numbering = numbering; this.position = position || '';
    this.projectionMirror = projectionMirror;
    if (this.mesh) this.mesh.visible = this.visible && Boolean(this.mesh.material.map);
    if (this.visible) await this.load();
    if (changed && this.mesh) await this.renderTexture();
    this.invalidate();
  }
}
