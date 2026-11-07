// F08 导入链路浏览器级验证：多文件队列 + 自动识别 + 字段映射向导。
// 启动真实 Python 服务（临时 DB），用 Edge headless 驱动导入对话框。
// 运行：node tests/import_wizard_verify.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync, spawn } from 'node:child_process';
import {ensureLocalLogin} from './local_account_fixture.mjs';

const root = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const nodeModules = process.env.CODEX_NODE_MODULES || path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'node', 'node_modules');
const { chromium, _electron } = await import(pathToFileURL(path.join(nodeModules, 'playwright', 'index.mjs')).href);
const packaged=process.env.THIMBLE_TEST_EXECUTABLE;

const PORT = process.env.THIMBLE_WIZARD_PORT || '18772';
const BASE = `http://127.0.0.1:${PORT}`;
const tempRoot = fs.mkdtempSync(path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||os.tmpdir(), 'thimble-wizard-'));
const screenshots = path.join(process.env.THIMBLE_TEST_OUTPUT_ROOT||path.join(root, 'output', 'playwright'), 'import-layout');
fs.mkdirSync(screenshots, { recursive: true });
const failures = [];
const check = (label, condition, detail = '') => {
  console.log(`${condition ? 'PASS' : 'FAIL'} ${label}${condition || !detail ? '' : ` :: ${detail}`}`);
  if (!condition) failures.push(label);
};

// ---- 夹具：一张可自动识别的 xlsx + 两张无法识别的 xlsx（走映射向导） ----
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const pickerFolder=path.join(tempRoot,'picker');
fs.mkdirSync(pickerFolder);
const goodXlsx = path.join(pickerFolder, 'good.xlsx');
const weirdXlsx = path.join(pickerFolder, 'weird.xlsx');
const weird2Xlsx = path.join(tempRoot, 'weird2.xlsx');
execFileSync(python, ['-c', `
from openpyxl import Workbook
good = Workbook()
good.active.title = '缺陷明细表'
good.active.append(['大修号','机组号','通道编号','在堆芯内的位置','幅值','三字码','磨损位置'])
good.active.append(['H209', 2, 1, '', 5.07, 'WAR', 'P1+10'])
good.active.append(['H209', 2, 2, '', 4.91, 'NDD', ''])
summary = good.create_sheet('管子汇总表')
summary.append(['站点代码','机组号','大修号','通道编号','堆芯位置','最大报告百分比'])
summary.append(['H', 2, 'H209', 1, 'A1', 48])
good.save(${JSON.stringify(goodXlsx)})
good.close()
weird = Workbook()
weird.active.title = 'Sheet1'
weird.active.append(['编号','名称','数量','备注','批次'])
weird.active.append([2, 1, 5.07, 'WAR', 'H209'])
weird.active.append([2, 2, 4.91, 'NDD', 'H209'])
weird.save(${JSON.stringify(weirdXlsx)})
weird.close()
weird2 = Workbook()
weird2.active.title = '数据'
weird2.active.append(['编号','名称','数量','备注','批次'])
weird2.active.append([2, 3, 3.2, 'WAR', 'H208'])
weird2.save(${JSON.stringify(weird2Xlsx)})
weird2.close()
print('fixtures ok')
`], { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, '.vendor') }, encoding: 'utf8' });

// ---- 启动后端（临时 DB） ----
const serviceEnv={ ...process.env, THIMBLE_PORT: PORT, THIMBLE_DATA_DIR:tempRoot, THIMBLE_DB_PATH: path.join(tempRoot, 'wizard.db'),
  THIMBLE_OUTPUT_DIR: path.join(tempRoot, 'exports'), THIMBLE_REPORT_DIR:path.join(tempRoot,'reports'),
  THIMBLE_LOG_PATH: path.join(tempRoot, 'service.log'),
  THIMBLE_USER_DATA_DIR:path.join(tempRoot,'profile'),THIMBLE_ALLOW_MULTI_INSTANCE:'1',
  PYTHONPATH: path.join(root, '.vendor') };
const server = packaged?null:spawn(python, [path.join(root, 'src', 'backend', 'server.py')], {
  env: { ...process.env, THIMBLE_PORT: PORT, THIMBLE_DATA_DIR:tempRoot, THIMBLE_DB_PATH: path.join(tempRoot, 'wizard.db'),
         THIMBLE_OUTPUT_DIR: path.join(tempRoot, 'exports'), THIMBLE_LOG_PATH: path.join(tempRoot, 'service.log'),
         PYTHONPATH: path.join(root, '.vendor') },
  stdio: 'ignore'
});
const desktop=packaged?await _electron.launch({executablePath:packaged,args:['--disable-gpu'],
  cwd:root,env:serviceEnv}):null;
const browser = packaged?null:await chromium.launch({ headless: true, executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' });
try {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const health = await fetch(`${BASE}/api/health`).then(response => response.json());
      if (health.version) break;
    } catch (_) { /* 服务未就绪 */ }
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  const page = desktop?await desktop.firstWindow():await browser.newPage({ viewport: { width: 1440, height: 900 } });
  if(desktop&&!await desktop.evaluate(({app})=>app.isPackaged))throw Error('Expected packaged runtime');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') {
    const location=message.location();
    errors.push(`${message.text()} (${location.url}:${location.lineNumber})`);
  } });
  if(!desktop)await page.addInitScript(() => {
    window.desktopAPI = {
      selectExcel: async () => (window.__excelPickerStub?.files) || [],
      selectExcelFolder: async () => window.__excelPickerStub?.folder || null,
      selectDirectory: async () => window.__excelPickerStub?.directory || null,
      saveCoreImage: async () => null
    };
  });
  if(!desktop)await page.goto(BASE, { waitUntil: 'networkidle' });
  await ensureLocalLogin(page);
  const setPicker=async stub=>{
    if(desktop)await desktop.evaluate(({dialog},stub)=>{
      dialog.showOpenDialog=async(_owner,options)=>({
        canceled:false,filePaths:options.properties.includes('openDirectory')?[stub.folder.folder]:stub.files,
      });
    },stub);
    else await page.evaluate(stub=>{window.__excelPickerStub=stub;},stub);
  };
  await page.locator('nav').waitFor();
  await page.locator('[data-view="workspace"]').click();

  // 打开导入对话框，确认新控件存在
  await page.locator('#openImportFlow').click();
  await page.locator('#importDialog selectExcelBtn, #selectExcelBtn').first().waitFor();
  check('导入对话框包含“选择文件夹”按钮', await page.locator('#selectExcelFolderBtn').count() === 1);
  check('文件队列初始为空', (await page.locator('#excelFileList').textContent()).includes('尚未选择文件'));
  check('队列摘要明确显示空队列', (await page.locator('#excelQueueSummary').textContent()).includes('尚未添加文件'));
  check('无待处理文件或已确认 Report 时禁用开始导入', await page.locator('#runImport').isDisabled());
  check('Excel / RPT 来源切换明确显示当前选项', await page.locator('#excelImportTab').getAttribute('aria-selected') === 'true'
    && await page.locator('#rptImportTab').getAttribute('aria-selected') === 'false');
  check('RPT 路线可直接切换且共用待导入队列', await page.locator('#rptImportPanel').isHidden()
    && await page.locator('#importQueuePanel').isVisible());
  for (const width of [1440, 800, 390]) {
    await page.setViewportSize({width, height: width === 390 ? 780 : 900});
    const fits = await page.locator('#importDialog').evaluate(el => {
      const r = el.getBoundingClientRect();
      return r.left >= 0 && r.right <= innerWidth + 1 && r.bottom <= innerHeight + 1 && el.scrollWidth <= el.clientWidth + 1;
    });
    check(`导入窗口在 ${width}px 宽度无横向溢出`, fits);
    await page.screenshot({path: path.join(screenshots, `import-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:900});
  const compactHeight=await page.locator('#importDialog').evaluate(el=>el.getBoundingClientRect().height);
  check('Excel 导入路线保持紧凑', compactHeight < 600, `高度 ${compactHeight}`);
  await page.setViewportSize({width:1440,height:900});
  await page.locator('#rptImportTab').click();
  const expandedDesktop=await page.locator('#importDialog').evaluate(el=>{
    const dialog=el.getBoundingClientRect(),actions=el.querySelector('.dialog-actions').getBoundingClientRect();
    const body=el.querySelector('#rptImportPanel .folder-import-content').getBoundingClientRect();
    return dialog.bottom<=innerHeight+1&&actions.bottom<=dialog.bottom+1&&body.height>100
      &&getComputedStyle(el.querySelector('#rptImportPanel')).display!=='none';
  });
  check('桌面 RPT 路线完整显示且底部操作仍可见',expandedDesktop);
  await page.screenshot({path:path.join(screenshots,'import-rpt-1440.png')});
  await page.setViewportSize({width:390,height:780});
  const expandedMobile=await page.locator('#importDialog').evaluate(el=>{
    const dialog=el.getBoundingClientRect(),actions=el.querySelector('.dialog-actions').getBoundingClientRect();
    const picker=el.querySelector('#selectFolderBtn').getBoundingClientRect();
    return dialog.left>=0&&dialog.right<=innerWidth+1&&dialog.bottom<=innerHeight+1
      &&actions.bottom<=dialog.bottom+1&&picker.right<=dialog.right+1&&picker.width>100;
  });
  check('手机 RPT 路线标题、选目录按钮和底部操作不溢出',expandedMobile);
  await page.screenshot({path:path.join(screenshots,'import-rpt-390.png')});
  await page.locator('#excelImportTab').click();
  await page.setViewportSize({width:1440,height:900});

  // 多选文件
  await setPicker({ files: [goodXlsx] });
  await page.locator('#selectExcelBtn').click();
  await page.waitForFunction(() => document.querySelectorAll('#excelFileList .excel-file-chip').length === 1);
  check('多选后队列显示 1 个文件', await page.locator('#excelFileList .excel-file-chip').count() === 1);
  check('队列摘要同步显示待处理文件数', (await page.locator('#excelQueueSummary').textContent()).includes('1 个待处理'));

  // 选择文件夹：good 去重，weird 入队
  await setPicker({ folder: { folder: pickerFolder, files: [goodXlsx, weirdXlsx], truncated: false } });
  await page.locator('#selectExcelFolderBtn').click();
  await page.waitForFunction(() => document.querySelectorAll('#excelFileList .excel-file-chip').length === 2);
  check('文件夹加入后队列为 2 个文件（去重生效）', await page.locator('#excelFileList .excel-file-chip').count() === 2);
  check('队列摘要同步更新总数', (await page.locator('#excelQueueSummary').textContent()).includes('2 个文件'));

  // 一键导入：good 自动识别（汇总表被排除），weird 弹映射向导
  let releaseInspect;
  const inspectGate = new Promise(resolve => { releaseInspect = resolve; });
  const inspectRoute = async route => { await inspectGate; await route.continue(); };
  await page.route('**/api/import-excel-inspect', inspectRoute);
  await page.locator('#runImport').click();
  await page.locator('#importProgressPanel').waitFor();
  check('导入时显示阶段与文件序号', (await page.locator('#importProgressMeta').textContent()).includes('文件 1 / 2'));
  check('进度条旁显示明确百分比', await page.locator('#importProgressPercent').isVisible()
    && /^\d+%$/.test(await page.locator('#importProgressPercent').textContent()));
  await page.waitForTimeout(1100);
  check('进度条显示已用时间和预计剩余时间', (await page.locator('#importProgressEta').textContent()).includes('已用')
    && /预计|估算/.test(await page.locator('#importProgressEta').textContent()));
  check('导入时禁止修改队列及重复提交', await page.locator('#selectExcelBtn').isDisabled()
    && await page.locator('#runImport').isDisabled()
    && await page.locator('#excelFileList [data-remove]').first().isDisabled());
  await page.screenshot({path:path.join(screenshots,'import-progress.png')});
  releaseInspect();
  const wizard = page.locator('.excel-mapping-dialog');
  await wizard.waitFor({ timeout: 30000 });
  await wizard.locator('#mappingConfirm').waitFor({state:'visible'});
  await page.waitForFunction(() => !document.querySelector('#mappingConfirm').disabled);
  await page.unroute('**/api/import-excel-inspect', inspectRoute);
  check('无法识别的文件触发字段映射向导', await wizard.isVisible());
  check('向导工作表下拉包含 Sheet1', (await wizard.locator('#mappingSheet').textContent()).includes('Sheet1'));
  check('向导默认表头行为 1', await wizard.locator('#mappingHeaderRow').inputValue() === '1');

  await wizard.locator('select[data-field="大修号"]').selectOption('5');
  await wizard.locator('select[data-field="机组号"]').selectOption('1');
  await wizard.locator('select[data-field="通道编号"]').selectOption('2');
  await wizard.locator('select[data-field="幅值"]').selectOption('3');
  await wizard.locator('select[data-field="三字码"]').selectOption('4');
  await wizard.locator('#mappingConfirm').click();
  await page.waitForFunction(() => document.querySelector('#importStatus')?.textContent.includes('Excel 导入完成'), null, { timeout: 60000 });
  const status = await page.locator('#importStatus').textContent();
  check('完成后明确显示导入成功结果', status.includes('导入成功') && await page.locator('#importStatus').getAttribute('data-outcome') === 'success');
  check('队列全部导入完成（2 个文件）', status.includes('2 个文件'), status.slice(0, 120));
  check('good 与 weird 各入库 2 条（共 4 条）', status.includes('新增 4 条'), status.slice(0, 120));
  check('good 仅导入 1 张数据表（汇总表已排除）', status.includes('good.xlsx：解析 2、新增 2、跳过 0') && !status.includes('2 张数据表'), status.slice(0, 200));
  check('两个文件芯片均标记已导入', await page.locator('#excelFileList .excel-file-chip.done').count() === 2);
  await page.waitForFunction(() => document.querySelector('#importDialog').dataset.busy === 'false');
  check('导入完成后进度动画停止且按钮恢复', !await page.locator('#importProgressPanel').isVisible()
    && await page.locator('#selectExcelBtn').isEnabled());

  // 缺必填列时向导应阻止确认（用第三个文件测芯片上的手动“映射”入口）
  await setPicker({ files: [weird2Xlsx] });
  await page.locator('#selectExcelBtn').click();
  await page.waitForFunction(() => document.querySelectorAll('#excelFileList .excel-file-chip').length === 3);
  await page.locator('#excelFileList .excel-file-chip').last().locator('[data-map]').click();
  await wizard.waitFor();
  await page.waitForFunction(() => !document.querySelector('#mappingConfirm').disabled);
  check('芯片“映射”按钮可手动打开向导', await wizard.isVisible());
  await wizard.locator('select[data-field="机组号"]').selectOption('');
  await wizard.locator('#mappingConfirm').click();
  check('缺少“机组号”时向导拒绝导入', (await wizard.locator('#mappingError').textContent()).includes('机组号'));
  await wizard.locator('select[data-field="机组号"]').selectOption('1');
  await wizard.locator('select[data-field="通道编号"]').selectOption('2');
  await wizard.locator('select[data-field="幅值"]').selectOption('');
  await wizard.locator('select[data-field="三字码"]').selectOption('');
  await wizard.locator('#mappingConfirm').click();
  const measureError = await wizard.locator('#mappingError').textContent();
  check('缺少测量列时向导拒绝导入', measureError.includes('幅值'), `实际提示：${measureError}`);
  await wizard.locator('[value="cancel"]').click();
  check('关闭映射后加载动画停止', !await page.locator('#importProgressPanel').isVisible());
  await page.locator('#importDialog .dialog-actions button[value="cancel"]').click();
  check('任务完成后可关闭导入窗口', !await page.locator('#importDialog').isVisible());

  await page.route('**/api/report-options',route=>route.fulfill({json:{reports:[
    {path:'G:/raw/group/Report-v9.rpt',name:'Report-v9.rpt',site_code:'H',unit_id:2,outage:'H209',group:'TH2I09CAL0001',modified_ns:100,records:1,analysts:['OLD'],sha256:'old'},
    {path:'G:/raw/group/Report-v2.rpt',name:'Report-v2.rpt',site_code:'H',unit_id:2,outage:'H209',group:'TH2I09CAL0001',modified_ns:200,records:2,analysts:['NEW'],sha256:'new'},
    {path:'G:/raw/group2/Report-v2.rpt',name:'Report-v2.rpt',site_code:'H',unit_id:2,outage:'H209',group:'TH2I09CAL0002',modified_ns:150,records:3,analysts:['OTHER'],sha256:'other'},
    {path:'G:/raw/group2/Report-v10.rpt',name:'Report-v10.rpt',site_code:'H',unit_id:2,outage:'H209',group:'TH2I09CAL0002',modified_ns:150,records:3,analysts:['OTHER'],sha256:'other10'}
  ]}}));
  await page.locator('#openImportFlow').click();
  await page.locator('#rptImportTab').click();
  check('RPT 策略只提供手动选择和预选最新两项',
    JSON.stringify(await page.locator('#importReportPolicy option').evaluateAll(options=>options.map(option=>option.value)))===
    JSON.stringify(['manual','auto_latest']));
  await page.locator('#importPath').evaluate(input=>{input.value='G:/raw'});
  await page.locator('#importReportPolicy').selectOption('auto_latest');
  await page.locator('#scanReports').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  check('自动预选仍未确认且禁止导入',!await page.evaluate(()=>window.__reportSelectionComplete)&&await page.locator('#runImport').isDisabled());
  const autoGroupCount=await page.locator('#reportWizardOverview button').count();
  const autoLatestSelection=[];
  for(let index=0;index<autoGroupCount;index++){
    check(`自动预选第 ${index+1} 组需用户确认`,
      await page.locator('#reportWizardOptions input:checked').count()===1
      &&!await page.evaluate(()=>window.__reportSelectionComplete));
    autoLatestSelection.push(await page.locator('#reportWizardOptions input:checked').evaluate(input=>input.closest('.wizard-report-option').querySelector('em[title]').textContent.trim()));
    await page.locator('#confirmReportChoice').click();
  }
  check('自动预选优先修改时间，同时间按数字版本稳定选择',JSON.stringify(autoLatestSelection)===JSON.stringify(['G:/raw/group/Report-v2.rpt','G:/raw/group2/Report-v10.rpt']));
  const autoLatestSelectionFinal=await page.evaluate(()=>window.__selectedReports);
  check('逐组确认后才允许自动预选结果导入',await page.evaluate(()=>window.__reportSelectionComplete)&&!await page.locator('#runImport').isDisabled());
  check('自动预选的报告按时间及版本稳定选择',JSON.stringify(autoLatestSelectionFinal)===JSON.stringify(['G:/raw/group/Report-v2.rpt','G:/raw/group2/Report-v10.rpt']));
  await page.locator('#scanReports').click();
  await page.locator('#reportWizardOptions input:not(:checked)').first().check();
  await page.locator('#cancelReportWizard').click();
  check('改动已确认的自动预选结果后需重新确认',!await page.evaluate(()=>window.__reportSelectionComplete)&&await page.locator('#runImport').isDisabled());
  await page.screenshot({path:path.join(screenshots,'rpt-auto-latest.png')});
  await page.locator('#importReportPolicy').selectOption('manual');
  await page.locator('#scanReports').click();
  await page.locator('#reportChoiceDialog[open]').waitFor();
  check('手动策略不会预选 RPT 且未选完时禁止导入',
    await page.locator('#reportWizardOptions input:checked').count()===0
    &&!await page.evaluate(()=>window.__reportSelectionComplete)
    &&await page.locator('#runImport').isDisabled());
  await page.locator('#confirmReportChoice').click();
  check('手动策略不允许空选确认',!await page.evaluate(()=>window.__reportSelectionComplete)
    &&await page.locator('#reportChoiceDialog').isVisible());
  const manualGroupCount=await page.locator('#reportWizardOverview button').count();
  await page.locator('#reportWizardOptions input').first().check();
  await page.locator('#confirmReportChoice').click();
  for(let index=1;index<manualGroupCount;index++){
    check(`手动策略第 ${index+1} 组仍需单独选取`,
      await page.locator('#reportWizardOptions input:checked').count()===0);
    await page.locator('#confirmReportChoice').click();
    check(`手动策略第 ${index+1} 组不允许空选确认`,
      !await page.evaluate(()=>window.__reportSelectionComplete)&&await page.locator('#reportChoiceDialog').isVisible());
    await page.locator('#reportWizardOptions input').first().check();
    await page.locator('#confirmReportChoice').click();
  }
  check('手动策略逐组确认后才允许导入',
    await page.evaluate(()=>window.__reportSelectionComplete)&&!await page.locator('#runImport').isDisabled());
  check('手动选择的每组报告均按用户选择保留',
    JSON.stringify(await page.evaluate(()=>window.__selectedReports))===
    JSON.stringify(['G:/raw/group/Report-v9.rpt','G:/raw/group2/Report-v2.rpt']));
  check('自动策略按修改时间和版本号预选每组最新报告',
    JSON.stringify(autoLatestSelectionFinal)===JSON.stringify(['G:/raw/group/Report-v2.rpt','G:/raw/group2/Report-v10.rpt']));
  await page.locator('#scanReports').click();
  await page.locator('#cancelReportWizard').click();

  check('浏览器无 JS 错误', errors.length === 0, errors.join(' | ').slice(0, 300));
} finally {
  await desktop?.close();
  await browser?.close();
  server?.kill();
  if(server)await new Promise(resolve => {
    if (server.exitCode !== null) return resolve();
    server.once('exit', resolve);
    setTimeout(resolve, 5000);
  });
  console.log(`保留隔离数据库与导入证据：${tempRoot}`);
}

if (failures.length) {
  console.log(`\nWIZARD VERIFY FAILED: ${failures.join(' / ')}`);
  process.exit(1);
}
console.log('\nWIZARD VERIFY ALL PASS');
