import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const files=[],errors=[],counts={};
function walk(folder){for(const item of fs.readdirSync(folder,{withFileTypes:true})){if(['vendor','node_modules','__pycache__'].includes(item.name))continue;const name=path.join(folder,item.name);if(item.isDirectory())walk(name);else files.push(name);}}
for(const folder of ['qt_shell','src','scripts','tests'])walk(path.join(root,folder));
for(const item of fs.readdirSync(root,{withFileTypes:true})){
  if(item.isFile()&&['.js','.mjs','.cjs','.py','.json','.ps1','.cmd'].includes(path.extname(item.name).toLowerCase()))files.push(path.join(root,item.name));
}
const inventory=[];
for(const file of files.sort()){
  const ext=path.extname(file).toLowerCase(),relative=path.relative(root,file),bytes=fs.readFileSync(file);
  counts[ext]=(counts[ext]||0)+1;
  inventory.push({path:relative,bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')});
  if(!bytes.length&&path.basename(file)!=='__init__.py'){errors.push(relative+': empty file');continue;}
  try{
    if(['.js','.mjs','.cjs'].includes(ext)){
      const module=ext==='.mjs'||(ext==='.js'&&/(^|\n)\s*(import\s|export\s|import\()/.test(bytes.toString()));
      execFileSync(process.execPath,['--check','--input-type='+ (module?'module':'commonjs')],{input:bytes,stdio:['pipe','pipe','pipe']});
    }
    if(ext==='.json')JSON.parse(bytes.toString().replace(/^\uFEFF/,''));
    const references=[];
    if(ext==='.html')for(const match of bytes.toString().matchAll(/(?:src|href)=["']([^"']+)["']/g))references.push(match[1]);
    if(ext==='.css')for(const match of bytes.toString().matchAll(/url\(\s*["']?([^"')\s]+)["']?\s*\)/g))references.push(match[1]);
    if(file.startsWith(path.join(root,'src'))&&['.js','.mjs'].includes(ext))for(const match of bytes.toString().matchAll(/(?:from\s+|import\s*\()(['"])(\.[^'"]+)\1/g))references.push(match[2]);
    for(const ref of references){
      if(/^(?:[a-z]+:|#|\/\/)/i.test(ref)||ref.includes('${'))continue;
      const target=ref.split(/[?#]/)[0];if(!target)continue;
      const absolute=target.startsWith('/')?path.join(root,'src','desktop-ui',target.slice(1)):path.resolve(path.dirname(file),target);
      if(!fs.existsSync(absolute))errors.push(relative+': missing resource '+ref);
    }
  }catch(error){errors.push(relative+': '+(error.stderr?.toString()||error.message).slice(0,600));}
}
try{
  const pythonCandidates = process.platform === 'win32'
    ? [path.join(root,'.venv-qt','Scripts','python.exe'), path.join(root,'.venv','Scripts','python.exe'), 'python.exe']
    : [path.join(root,'.venv-qt','bin','python'), path.join(root,'.venv','bin','python'), 'python3'];
  const python = pythonCandidates.find(candidate => candidate === 'python.exe' || candidate === 'python3' || fs.existsSync(candidate));
  if(!python) throw new Error('Python runtime not found; tried '+pythonCandidates.join(', '));
  execFileSync(python,['-c',`import ast,pathlib;root=pathlib.Path.cwd();files=list(root.glob('*.py'))+[p for d in ['qt_shell','src','scripts','tests'] for p in (root/d).rglob('*.py') if '__pycache__' not in p.parts];[ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p)) for p in files];print('Python AST:',len(files))`],{cwd:root,stdio:'pipe'});
}catch(error){errors.push(error.stderr?.toString()||error.message);}
if(process.platform==='win32'){
  try{execFileSync('powershell.exe',['-NoProfile','-Command',`$auditFiles=Get-ChildItem -LiteralPath scripts,src,tests -Recurse -File -Filter *.ps1;foreach($auditFile in $auditFiles){$auditTokens=$null;$auditErrors=$null;[System.Management.Automation.Language.Parser]::ParseFile($auditFile.FullName,[ref]$auditTokens,[ref]$auditErrors)|Out-Null;if($auditErrors.Count){Write-Error ($auditFile.FullName+': '+($auditErrors.Message -join '; '));exit 1}}`],{cwd:root,stdio:'pipe'});}catch(error){errors.push(error.stderr?.toString()||error.message);}
}
console.log(JSON.stringify({files:files.length,counts,errors},null,2));
if(process.env.THIMBLE_TEST_OUTPUT_ROOT)fs.writeFileSync(path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT,'source-inventory.json'),JSON.stringify({files:inventory,counts,errors},null,2));
process.exitCode=errors.length?1:0;
