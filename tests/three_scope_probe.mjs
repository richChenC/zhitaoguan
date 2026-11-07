import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const source=path.resolve(process.env.THIMBLE_TEST_SOURCE_DB||'data/thimble.db');
const out=path.join(root,'tmp',`three-scope-probe-${Date.now()}`);fs.mkdirSync(out,{recursive:true});
const db=path.join(out,'test.db'),python=path.join(root,'.venv/Scripts/python.exe');
execFileSync(python,['-X','utf8','-c',`import sqlite3,sys
from pathlib import Path
with sqlite3.connect(Path(sys.argv[1]).as_uri()+'?mode=ro',uri=True) as src:
 with sqlite3.connect(sys.argv[2]) as dst:src.backup(dst)`,source,db],{cwd:root});
const socket=net.createServer();await new Promise((resolve,reject)=>{socket.once('error',reject);socket.listen(0,'127.0.0.1',resolve)});
const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
const runtime=path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const {_electron}=await import(pathToFileURL(runtime).href);
const app=await _electron.launch({executablePath:path.join(root,'node_modules/electron/dist/electron.exe'),args:[root,'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:String(port),THIMBLE_PYTHON:python,
    THIMBLE_DB_PATH:db,THIMBLE_USER_DATA_DIR:path.join(out,'profile'),THIMBLE_OUTPUT_DIR:path.join(out,'exports'),
    THIMBLE_REPORT_DIR:path.join(out,'reports'),THIMBLE_LOG_PATH:path.join(out,'service.log')}});
try {
  const page=await app.firstWindow();page.setDefaultTimeout(60000);
  await page.locator('#rows tr[data-i]').first().waitFor();
  const openedAt=Date.now();
  await page.locator('[data-view="threeD"]').click();
  const navigationMs=Date.now()-openedAt;
  const frame=page.locator('#threeModelFrame').contentFrame();await frame.locator('#standardView').waitFor();
  const snapshot=async()=>page.locator('#threeSite,#threeUnit,#threeOutage').evaluateAll(items=>items.map(el=>({
    id:el.id,value:el.value,disabled:el.disabled,options:[...el.options].map(o=>({value:o.value,label:o.textContent,disabled:o.disabled}))
  })));
  const stages=[{step:'initial',controls:await snapshot()}];
  await page.locator('#threeSite').selectOption('H');stages.push({step:'site H',controls:await snapshot()});
  await page.locator('#threeUnit').selectOption('2');stages.push({step:'unit 2',controls:await snapshot()});
  console.log(JSON.stringify({database:source,navigationMs,stages},null,2));
  assert.equal(await page.locator('#threeOutage').isEnabled(),true);
  await page.locator('#threeOutage').selectOption('H209');
} finally { await app.close(); }
