// Exercise the reference's actual disclosure handlers against measured native group heights.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const input = JSON.parse(process.argv[3]);
const source = fs.readFileSync(path.join(path.resolve(process.argv[2]),
  'src/desktop-ui/visualizations/reference-thimble/app.js'), 'utf8');
const start = source.indexOf('const GRP_COLLAPSED_DEFAULT =');
const end = source.indexOf('\nlet rebuildTimer;', start);
if (start < 0 || end < 0) throw new Error('Reference disclosure boundaries changed');
const keys = ['asm', 'disp', 'cut', 'explode', 'parts'];
let height = input.height;
let stored = input.saved === undefined ? null : JSON.stringify(input.saved);
const groups = keys.map(key => {
  const classes = new Set();
  const handlers = {};
  const heading = {textContent:key, setAttribute(){}, addEventListener(name, fn) { handlers[name] = fn; }};
  return {dataset:{grp:key}, classes, handlers, scrollIntoView(){},
    querySelector:() => heading,
    classList:{contains:name => classes.has(name), add:name => classes.add(name),
      remove:name => classes.delete(name), toggle(name, on) { on ? classes.add(name) : classes.delete(name); }}};
});
const left = {get clientHeight() { return height; },
  get scrollHeight() { return input.base + groups.reduce((sum, group) =>
    sum + (group.classes.has('collapsed') ? 0 : input.bodies[group.dataset.grp]), 0); },
  querySelector(selector) { return groups.find(group => selector.includes(`"${group.dataset.grp}"`)); }};
const context = {document:{querySelector:() => left, querySelectorAll:() => groups},
  localStorage:{getItem:() => stored, setItem(_key, value) { stored = value; }},
  MutationObserver:class { observe(){} }, toast(){}};
vm.runInNewContext(source.slice(start, end) + '\ninitGrpCollapse();', context);
const snapshot = () => JSON.parse(vm.runInNewContext(
  'JSON.stringify({collapsed:[...grpSet].sort(), automatic:[...autoFolded].sort()})', context));
const results = [snapshot()];
for (const action of input.actions) {
  if (action.click) groups.find(group => group.dataset.grp === action.click).handlers.click();
  else { height = action.height; vm.runInNewContext('ensureFit(null, false);', context); }
  results.push(snapshot());
}
process.stdout.write(JSON.stringify(results));
