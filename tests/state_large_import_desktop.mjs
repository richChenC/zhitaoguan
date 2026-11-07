import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root=path.resolve(fileURLToPath(new URL('..',import.meta.url)));
const samples=path.resolve(root,'../../05_测试与验证/01_模拟数据/管子生命周期模拟数据_v2_非真实');
const source=path.join(samples,'模拟状态维护导入_全量.csv');
const original=path.join(root,'data/thimble.db');
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const before={data:hash(original),sample:hash(source)};
const output=path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root,'tmp'),`state-large-import-${Date.now()}`);
fs.mkdirSync(output,{recursive:true});
const {_electron}=await import(pathToFileURL(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;
const app=await _electron.launch({
  executablePath:packaged||path.join(root,'node_modules/electron/dist/electron.exe'),
  args:[...(packaged?[]:[root]),'--disable-gpu'],cwd:root,
  env:{...process.env,THIMBLE_ALLOW_MULTI_INSTANCE:'1',THIMBLE_PORT:'18846',
    THIMBLE_PYTHON:path.join(root,'.venv/Scripts/python.exe'),THIMBLE_DB_PATH:path.join(output,'test.db'),
    THIMBLE_USER_DATA_DIR:path.join(output,'profile'),THIMBLE_LOG_PATH:path.join(output,'service.log'),
    THIMBLE_OUTPUT_DIR:path.join(output,'exports'),THIMBLE_REPORT_DIR:path.join(output,'reports')},
});
if(packaged)assert.equal(await app.evaluate(({app})=>app.isPackaged),true);
const evidence={errors:[]};
let page;
try{
  page=await app.firstWindow();page.setDefaultTimeout(90000);await ensureLocalLogin(page);
  page.on('pageerror',error=>evidence.errors.push(error.message));
  await page.locator('[data-view="states"]').click();
  await page.locator('#stateImportFile').setInputFiles(source);
  await page.locator('.state-import-preview').waitFor();
  assert.equal(await page.locator('.state-import-preview tbody tr').count(),100);
  assert.match(await page.locator('.state-preview-tools [role="status"]').textContent(),/识别 12600 条 · 已选 12600 条/);
  assert.match(await page.locator('.state-preview-pagination span').textContent(),/第 1 \/ 126 页/);
  const first=await page.locator('.state-import-preview tbody tr').first().evaluate(row=>({
    checkbox:row.querySelector('input[type="checkbox"]').getAttribute('aria-label'),
    note:row.querySelector('textarea').getAttribute('aria-label'),
  }));
  const edited='分页核验：保留跨页编辑的原始备注';
  await page.getByRole('textbox',{name:first.note,exact:true}).fill(edited);
  await page.getByRole('button',{name:'下一页识别结果',exact:true}).click();
  await page.locator('.state-import-preview tbody tr input[type="checkbox"]').first().uncheck();
  assert.match(await page.locator('.state-preview-tools [role="status"]').textContent(),/已选 12599 条/);
  await page.getByRole('button',{name:'上一页识别结果',exact:true}).click();
  assert.equal(await page.getByRole('textbox',{name:first.note,exact:true}).inputValue(),edited);
  await page.screenshot({path:path.join(output,'preview-12600-records.png')});
  const completed=page.waitForResponse(response=>response.url().endsWith('/api/states/batch')&&response.request().method()==='POST');
  await page.locator('.state-import-preview [value="apply"]').click();
  const response=await completed,result=await response.json();
  assert.equal(response.status(),200,JSON.stringify(result));
  assert.equal(result.changed,12599);
  const saved=await page.evaluate(()=>window.api('/api/states'));
  assert.equal(saved.items.length,12599);
  assert(saved.items.some(row=>row.note===edited),'Cross-page edits must be committed');
  evidence.result=result;evidence.saved=saved.items.length;
  assert.deepEqual(evidence.errors,[]);evidence.passed=true;
  console.log('PASS 12600-record import, 100-row preview pagination, cross-page selection and editing');
}catch(error){
  evidence.failure=error.stack;
  if(page)await page.screenshot({path:path.join(output,'failure.png'),timeout:10000}).catch(()=>{});
  throw error;
}finally{
  await app.close();
  evidence.sourceUnchanged=hash(original)===before.data&&hash(source)===before.sample;
  fs.writeFileSync(path.join(output,'evidence.json'),JSON.stringify(evidence,null,2));
  console.log('Evidence:',output);
  assert(evidence.sourceUnchanged);
}
