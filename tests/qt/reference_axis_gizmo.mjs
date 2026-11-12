// Execute the preserved reference's real axis handlers without loading its UI.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

const viewer = path.join(path.resolve(process.argv[2]), 'src/desktop-ui/visualizations/reference-thimble');
const THREE = await import(pathToFileURL(path.join(viewer, 'vendor/three.core.js')));
const source = fs.readFileSync(path.join(viewer, 'app.js'), 'utf8');
const start = source.indexOf('const AXIS_DEFS =');
const end = source.indexOf('/** PRV', start);
const helperStart = source.indexOf("$('optAxis').onchange =");
const helperEnd = source.indexOf("$('optFat').onchange =", helperStart);
if ([start, end, helperStart, helperEnd].some(index => index < 0)) {
  throw new Error('Reference axis function boundaries changed');
}
class Element {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.attributes = {};
    this.off = false;
    this.classList = {toggle: (_name, value) => { this.off = value; }};
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  appendChild(child) {
    this.children = this.children.filter(item => item !== child);
    this.children.push(child);
  }
  getBBox() {
    const points = [];
    const visit = element => {
      const a = element.attributes;
      if (element.tag === 'circle') {
        points.push([Number(a.cx)-Number(a.r), Number(a.cy)-Number(a.r)],
          [Number(a.cx)+Number(a.r), Number(a.cy)+Number(a.r)]);
      } else if (element.tag === 'line') {
        points.push([Number(a.x1), Number(a.y1)], [Number(a.x2), Number(a.y2)]);
      }
      element.children.forEach(visit);
    };
    visit(this);
    const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
    return {x:Math.min(...xs), y:Math.min(...ys),
      width:Math.max(...xs)-Math.min(...xs), height:Math.max(...ys)-Math.min(...ys)};
  }
}
let input = '';
for await (const chunk of process.stdin) input += chunk;
const outputs = [];
for (const item of JSON.parse(input)) {
  const host = new Element('host');
  const context = {
    THREE, Math, state:{axes:item.axes, mode:item.mode},
    camera:{quaternion:new THREE.Quaternion(...item.quaternion),
      isOrthographicCamera:item.mirrored, left:1, right:item.mirrored ? -1 : 2},
    document:{getElementById:() => host, createElementNS:(_ns, tag) => new Element(tag)},
  };
  vm.runInNewContext(source.slice(start, end) + '\nbuildAxisGizmo(); updateAxisGizmo();', context);
  const svg = host.children[0];
  outputs.push({visible:!host.off, viewBox:svg.attributes.viewBox,
    axes:svg.children.filter(element => element.tag === 'g').map(group => ({
      text:group.children[3].textContent, line:group.children[1].attributes,
      stub:group.children[0].attributes, dot:group.children[2].attributes,
    }))});
}
const controls = {};
const context = {THREE, state:{}, root:new THREE.Group(), $:id => controls[id] ||= {}};
vm.runInNewContext(source.slice(helperStart, helperEnd), context);
controls.optAxis.onchange({target:{checked:true}});
const helpers = context.root.children.map(helper => ({
  positions:Array.from(helper.geometry.attributes.position.array),
  colors:Array.from(helper.geometry.attributes.color.array),
}));
controls.optAxis.onchange({target:{checked:false}});
process.stdout.write(JSON.stringify({revision:THREE.REVISION, outputs, helpers,
  helpersRemoved:context.root.children.length === 0}));
