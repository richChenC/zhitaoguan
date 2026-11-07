const { app, BrowserWindow, dialog, ipcMain, Menu, shell, session } = require('electron');
const { spawn, spawnSync } = require('node:child_process');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const { randomBytes, createHash } = require('node:crypto');
const { createWindowCloseGuard } = require('./window-close-guard.cjs');
const { loadWindowPage } = require('./window-loading.cjs');
const { saveArtifact } = require('./artifact-save.cjs');
const { observeDownloads } = require('./download-feedback.cjs');
const { allowedURL, protectDirectory } = require('./offline-policy.cjs');
const { startupFailureMessage } = require('./service-diagnostics.cjs');
for (const flag of ['disable-background-networking','disable-component-update','disable-domain-reliability','disable-sync','no-pings']) app.commandLine.appendSwitch(flag);

// Keep Chromium's GPU work in the Electron process on machines where the
// separately spawned GPU process cannot load its system graphics component.
app.commandLine.appendSwitch('in-process-gpu');
// Native Windows presentation can stay blank even when capturePage sees the UI.
// Use software window compositing while leaving WebGL available to the 3D view.
app.commandLine.appendSwitch('disable-gpu-compositing');

// Windows 高 DPI 支持：跟随系统缩放（125%/150%），确保界面清晰不模糊
app.commandLine.appendSwitch('high-dpi-support', '1');

const LEGACY_USER_DATA = app.getPath('userData');
if (process.env.THIMBLE_USER_DATA_DIR) {
  app.setPath('userData', path.resolve(process.env.THIMBLE_USER_DATA_DIR));
} else {
  app.setPath('userData', path.join(app.getPath('appData'), 'ThimbleInspection'));
}

const ROOT = path.resolve(__dirname, '..', '..');
const PRODUCT_NAME = '在役检查系统-指套管数据管理工具';
const APP_ICON = path.join(ROOT, 'assets', 'app-icon.ico');
app.setName(PRODUCT_NAME);
const PACKAGED_SERVER = 'thimble-backend.exe';
const PORT = process.env.THIMBLE_PORT || '18767';
const SERVICE_INSTANCE = randomBytes(24).toString('hex');
let BASE_URL = `http://127.0.0.1:${PORT}`;
function artifactName(kind, scope, extension) {
  const segment = value => String(value || '范围未指定').trim()
    .replace(/[<>:"/\\|?*\x00-\x1f\s]+/g, '-').replace(/-+/g, '-')
    .replace(/^[ ._-]+|[ ._-]+$/g, '').slice(0, 36) || '范围未指定';
  const now = new Date();
  const pad = value => String(value).padStart(2, '0');
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}-${String(now.getMilliseconds()).padStart(3, '0')}`;
  return `TH_${segment(kind)}_${segment(scope)}_${stamp}_${randomBytes(6).toString('hex')}.${extension}`;
}
// Bump this whenever packaged frontend assets change; Chromium may otherwise
// keep an older renderer cached across portable-app upgrades.
let URL = `${BASE_URL}/?build=20261102-release-review`;
const SERVICE_VERSION = '2026.10.26.1';
let serverProcess = null;
let mainWindow = null;
let settingsWindow = null;
let settingsReady = null;
let requestedSettingsSection = 'settingsDataPane';
const settingsSections = new Set(['settingsDataPane', 'settingsPreferencesPane', 'settingsImportPane', 'settingsRulesPane', 'settingsAccountsPane', 'settingsMaintenancePane']);
let serviceLogPath = null;

function logWindow(kind, message) {
  if (!serviceLogPath) return;
  fs.appendFile(serviceLogPath, `[${new Date().toISOString()}] [${kind}] ${message}\n`, () => {});
}

function observeWindow(window, kind) {
  const contents = window.webContents;
  contents.on('did-fail-load', (_event, code, description, _url, isMainFrame) => {
    if (isMainFrame) logWindow(kind, `navigation failed ${code}: ${description}`);
  });
  contents.on('preload-error', (_event, _file, error) => logWindow(kind, `preload failed: ${error.message}`));
  contents.on('render-process-gone', (_event, details) => {
    logWindow(kind, `renderer exited: ${details.reason}, code=${details.exitCode}`);
    if (appQuitting || window.isDestroyed() || details.reason === 'clean-exit') return;
    void dialog.showMessageBox(window, {
      type:'error', title:PRODUCT_NAME, message:'界面显示已中断',
      detail:'已保存的数据不受影响。重新加载会丢弃尚未保存的界面修改。',
      buttons:['重新加载界面', '关闭窗口'], defaultId:0, cancelId:1, noLink:true
    }).then(async ({response}) => {
      if (window.isDestroyed()) return;
      if (response === 1) { window.close(); return; }
      try {
        if (await loadWindowPage(window, contents.getURL() || URL, {log:message => logWindow(kind, message)})) window.show();
      } catch (error) {
        logWindow(kind, error.message);
        dialog.showErrorBox(PRODUCT_NAME, `界面重新加载失败，请关闭后重启软件。\n日志：${serviceLogPath}`);
      }
    }).catch(error => logWindow(kind, error.message));
  });
}

function stopServer() {
  const child = serverProcess;
  serverProcess = null;
  if (!child || !child.pid || child.exitCode !== null || child.killed) return;
  // PyInstaller onefile keeps the HTTP service in a child of its launcher.
  if (process.platform === 'win32') {
    const result = spawnSync(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'),
      ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore', timeout: 5000 });
    if (result.status === 0) return;
  }
  child.kill();
}

function pythonCandidates() {
  const candidates = [
    process.env.THIMBLE_PYTHON,
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'python', 'python.exe'),
    path.join(process.resourcesPath || '', 'python', 'python.exe'),
  ].filter(Boolean).filter(candidate => !path.isAbsolute(candidate) || fs.existsSync(candidate));
  candidates.push(process.platform === 'win32' ? 'py' : 'python3');
  return [...new Set(candidates)];
}

function serverCandidates() {
  // 自动化框架拉起时 Electron 可能把开发态误判为已打包，此时打包后端并不存在；
  // 文件缺失时回退 python 候选，避免本地数据服务未启动应用就退出。
  if (app.isPackaged) {
    const executable = path.join(process.resourcesPath, 'backend', PACKAGED_SERVER);
    if (fs.existsSync(executable)) return [{ command: executable, args: [] }];
  }
  return pythonCandidates().map(command => ({ command, args: [path.join(ROOT, 'src', 'backend', 'server.py')] }));
}

function isServerReady() {
  return new Promise(resolve => {
    const request = http.get(`${BASE_URL}/api/health`, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try {
          const payload = JSON.parse(body);
          resolve(response.statusCode === 200 && payload.ok === true && payload.service === 'thimble-local' &&
            payload.version === SERVICE_VERSION && payload.desktop_instance === SERVICE_INSTANCE);
        } catch (_) { resolve(false); }
      });
    });
    request.setTimeout(800, () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
  });
}

function availablePort(port) {
  return new Promise((resolve, reject) => {
    const listener = net.createServer();
    listener.unref();
    listener.once('error', error => {
      if (error.code === 'EADDRINUSE' || error.code === 'EACCES') resolve(null);
      else reject(error);
    });
    listener.listen({ port: Number(port), host: '127.0.0.1', exclusive: true }, () => {
      const selected = listener.address().port;
      listener.close(error => error ? reject(error) : resolve(selected));
    });
  });
}

async function selectPort(preferred) {
  const configured = Number(preferred);
  if (!Number.isInteger(configured) || configured < 1 || configured > 65535) {
    throw new Error('本地数据服务端口设置无效。');
  }
  return await availablePort(configured) || await availablePort(0);
}

async function ensureServer() {
  protectDirectory(app.getPath('userData'));
  const logDirectory = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDirectory, { recursive: true });
  serviceLogPath = path.join(logDirectory, 'desktop-service.log');
  const writeLog = chunk => {
    if (!serviceLogPath) return;
    fs.appendFile(serviceLogPath, Buffer.isBuffer(chunk) ? chunk : String(chunk), () => {});
  };
  const environment = { ...process.env, THIMBLE_DESKTOP_INSTANCE: SERVICE_INSTANCE };
  if (!process.env.THIMBLE_DATA_DIR && !process.env.THIMBLE_DB_PATH && !process.env.THIMBLE_USER_DATA_DIR) {
    environment.THIMBLE_MIGRATE_LEGACY = '1';
    environment.THIMBLE_LEGACY_DATA_DIRS = JSON.stringify([path.join(ROOT,'data'),path.join(ROOT,'.user-data','data'),path.join(LEGACY_USER_DATA,'data'),path.join(app.getPath('appData'),PRODUCT_NAME,'data')]);
  }
  const vendorPath = path.join(ROOT, '.vendor');
  environment.PYTHONPATH = [vendorPath, environment.PYTHONPATH].filter(Boolean).join(path.delimiter);
  {
    environment.THIMBLE_DATA_DIR ||= path.join(app.getPath('userData'), 'data');
    environment.THIMBLE_OUTPUT_DIR ||= path.join(app.getPath('userData'), 'output', 'excel');
    environment.THIMBLE_REPORT_DIR ||= path.join(app.getPath('userData'), 'output', 'reports');
    environment.THIMBLE_LOG_PATH ||= path.join(app.getPath('userData'), 'logs', 'server.log');
  }
  for (const { command, args } of serverCandidates()) {
    const selectedPort = await selectPort(PORT);
    environment.THIMBLE_PORT = String(selectedPort);
    BASE_URL = `http://127.0.0.1:${selectedPort}`;
    URL = `${BASE_URL}/?build=20261102-release-review`;
    if (String(selectedPort) !== String(PORT)) {
      writeLog(`[desktop] port ${PORT} is occupied; using ${selectedPort}\n`);
    }
    let spawnError = null;
    let processExited = false;
    serverProcess = spawn(command, args, {
      cwd: app.isPackaged ? app.getPath('userData') : ROOT,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: environment
    });
    serverProcess.stdout.on('data', writeLog);
    serverProcess.stderr.on('data', writeLog);
    serverProcess.once('error', error => { spawnError = error; });
    serverProcess.once('exit', (code, signal) => {
      processExited = true;
      writeLog(`\n[desktop] service (${command}) exited code=${code} signal=${signal}\n`);
    });
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 500));
      if (await isServerReady()) return;
      if (spawnError || processExited) break;
    }
    stopServer();
    writeLog(`[desktop] runtime failed: ${command}${spawnError ? ` - ${spawnError.message}` : ''}${processExited ? ' - process exited before health check' : ' - health check timed out'}\n`);
  }
  const error = new Error('本地数据服务启动失败');
  error.code = 'SERVICE_START_FAILED';
  throw error;
}

async function createWindow() {
  try {
    await ensureServer();
  } catch (error) {
    dialog.showErrorBox(PRODUCT_NAME, startupFailureMessage(error, {
      userData: app.getPath('userData'),
      dataDirectory: process.env.THIMBLE_DB_PATH ? path.dirname(path.resolve(process.env.THIMBLE_DB_PATH)) :
        process.env.THIMBLE_DATA_DIR || path.join(app.getPath('userData'), 'data'),
      tempDirectory: os.tmpdir(),
      logPath: serviceLogPath
    }));
    app.quit();
    return;
  }
  mainWindow = new BrowserWindow({
    title: PRODUCT_NAME,
    icon: APP_ICON,
    width: 1480,
    height: 960,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: '#f3f5f6',
    show: false,
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.cjs'), zoomFactor: 1.0 }
  });
  observeWindow(mainWindow, 'main');
  Menu.setApplicationMenu(null);
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(`${BASE_URL}/`)) event.preventDefault();
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    return { action: 'deny' };
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  // 稳层防护：有未提交的行内编辑时，先弹确认再关窗，避免静默丢失修改。
  // 渲染层通过 window.__thimbleUnsavedEdits() 汇报脏状态；查询失败按无脏处理。
  const guardClose = createWindowCloseGuard({
    isDirty: async () => {
      try {
        return await Promise.race([
          mainWindow.webContents.executeJavaScript('window.__thimbleUnsavedEdits?.() === true', true),
          new Promise(resolve => setTimeout(() => resolve(false), 1500))
        ]);
      } catch (_) { return false; }
    },
    confirmDiscard: async () => {
      const { response } = await dialog.showMessageBox(mainWindow, {
        type: 'warning',
        title: PRODUCT_NAME,
        message: '有未提交的修改',
        detail: '关闭窗口将丢弃正在编辑但尚未保存的内容；已保存的数据不受影响。',
        buttons: ['放弃修改并关闭', '继续编辑'],
        defaultId: 1,
        cancelId: 1,
        noLink: true
      });
      return response === 0;
    },
    close: () => mainWindow.close()
  });
  mainWindow.on('close', event => { if (!appQuitting) void guardClose(event); });
  // 监听 Windows DPI 变化（用户调整显示缩放或拖到不同 DPI 屏幕）
  mainWindow.webContents.on('preferred-size-changed', (_event, { width, height }) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const [currentW, currentH] = mainWindow.getContentSize();
      const [minimumW, minimumH] = mainWindow.getMinimumSize();
      // 仅在差异超过 10px 时才调整，避免抖动
      if (Math.abs(width - currentW) > 10 || Math.abs(height - currentH) > 10) {
        mainWindow.setContentSize(Math.max(width, minimumW), Math.max(height, minimumH));
      }
    }
  });
  try {
    if (!await loadWindowPage(mainWindow, URL, {log:message => logWindow('main', message)})) return;
  } catch (error) {
    logWindow('main', error.message);
    dialog.showErrorBox(PRODUCT_NAME, `主界面加载失败，请重新启动软件。\n日志：${serviceLogPath}`);
    app.quit();
    return;
  }
  mainWindow.maximize();
  mainWindow.show();
}

const singleInstance = process.env.THIMBLE_ALLOW_MULTI_INSTANCE === '1' || app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.whenReady().then(() => {
    observeDownloads(session.defaultSession);
    session.defaultSession.webRequest.onBeforeRequest({urls:['<all_urls>']}, (details,callback) => callback({cancel:!allowedURL(details.url,BASE_URL)}));
    session.defaultSession.setPermissionRequestHandler((_contents,_permission,callback) => callback(false));
    session.defaultSession.setPermissionCheckHandler(() => false);
    app.on('web-contents-created',(_event,contents) => {
      contents.on('will-navigate',(event,url) => {if(!allowedURL(url,BASE_URL))event.preventDefault();});
      contents.on('will-attach-webview',event => event.preventDefault());
      contents.setWindowOpenHandler(() => ({action:'deny'}));
    });
    return createWindow();
  }).catch(error => {dialog.showErrorBox(PRODUCT_NAME,error.message);app.quit();});
}
function dialogOwner(event) {
  const owner = event?.sender && BrowserWindow.fromWebContents(event.sender);
  return owner && !owner.isDestroyed() ? owner : mainWindow && !mainWindow.isDestroyed() ? mainWindow : null;
}
async function showOwnedDialog(event, kind, options) {
  const owner = dialogOwner(event);
  if (owner) {
    if (owner.isMinimized()) owner.restore();
    return dialog[kind](owner, options);
  }
  return dialog[kind](options);
}

ipcMain.handle('select-directory', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', { title: '选择指套管检测数据文件夹', properties: ['openDirectory'] });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle('open-settings-window', async (_event, section = 'settingsDataPane') => {
  requestedSettingsSection = settingsSections.has(section) ? section : 'settingsDataPane';
  if (settingsWindow && !settingsWindow.isDestroyed()) {
    const existing = settingsWindow;
    await settingsReady;
    if (existing.isDestroyed()) return;
    if (existing.isMinimized()) existing.restore();
    existing.webContents.send('settings-section', requestedSettingsSection);
    existing.show();
    existing.focus();
    return;
  }
  settingsWindow = new BrowserWindow({
    title: `${PRODUCT_NAME} - 软件设置`,
    icon: APP_ICON,
    show: false,
    width: 1180,
    height: 860,
    minWidth: 820,
    minHeight: 620,
    parent: mainWindow && !mainWindow.isDestroyed() ? mainWindow : undefined,
    backgroundColor: '#f4f7f8',
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.cjs'), zoomFactor: 1.0 }
  });
  const owner = settingsWindow;
  observeWindow(owner, 'settings');
  owner.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(`${BASE_URL}/`)) event.preventDefault();
  });
  settingsWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  owner.on('closed', () => { if (settingsWindow === owner) { settingsWindow = null; settingsReady = null; } });
  const settingsURL = `${URL}&window=settings&section=${encodeURIComponent(requestedSettingsSection)}`;
  settingsReady = (async () => {
    try {
      if (!await loadWindowPage(owner, settingsURL, {log:message => logWindow('settings', message)})) return;
      owner.webContents.send('settings-section', requestedSettingsSection);
      owner.show();
    } catch (error) {
      logWindow('settings', error.message);
      if (!owner.isDestroyed()) {
        owner.close();
        dialog.showErrorBox(PRODUCT_NAME, `设置界面加载失败，请重新打开设置。\n日志：${serviceLogPath}`);
      }
    }
  })();
  await settingsReady;
});
ipcMain.handle('close-settings-window', event => {
  const owner = BrowserWindow.fromWebContents(event.sender);
  if (owner && owner === settingsWindow) owner.close();
});
const visualizationWindows = new Set();
ipcMain.handle('open-visualization-window', async (event, payload = {}) => {
  const allowed = new Set(['chart31','chart32','chart34','chartTubeTrend','chartDistHistogram',
    'chartDistScatter','vwCoverage','vwDepthDistribution','vwFrequencyChart','vwUnitOverview','vwRiskContent','c32PositionShare']);
  if (!event.sender.getURL().startsWith(`${BASE_URL}/`) || !allowed.has(payload.panel)) throw new Error('可视化窗口参数无效');
  const state = JSON.stringify(payload.state || {});
  if (state.length > 16000) throw new Error('可视化筛选条件过长');
  const window = new BrowserWindow({title:PRODUCT_NAME + ' - 图表对比',icon:APP_ICON,width:1100,height:780,
    minWidth:640,minHeight:480,show:false,autoHideMenuBar:true,backgroundColor:'#f3f5f6',
    webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true,preload:path.join(__dirname,'preload.cjs')}});
  visualizationWindows.add(window);
  window.on('closed', () => visualizationWindows.delete(window));
  window.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(`${BASE_URL}/`)) e.preventDefault(); });
  window.webContents.setWindowOpenHandler(() => ({action:'deny'}));
  observeWindow(window, 'visualization');
  try {
    const target = `${URL}&visualization=${encodeURIComponent(payload.panel)}&visualizationState=${encodeURIComponent(state)}`;
    if (!await loadWindowPage(window, target, {log:message => logWindow('visualization',message)})) {
      if (!window.isDestroyed()) window.close();
      throw new Error('图表窗口加载失败');
    }
    window.show();
  } catch (error) {
    if (!window.isDestroyed()) window.close();
    throw new Error('图表窗口加载失败，请重试');
  }
});
ipcMain.handle('get-workspace-report-scope', async event => {
  const sender = BrowserWindow.fromWebContents(event.sender);
  if (!mainWindow || mainWindow.isDestroyed() || (sender !== mainWindow && sender !== settingsWindow)) return null;
  return mainWindow.webContents.executeJavaScript(`({
    scope: Object.fromEntries(['site','unit','outage'].map(id => [id, document.getElementById(id)?.value || ''])),
    records: [...(window.__thimbleState?.selectedRecords?.values() || [])].map(({id,site_code,unit_id,outage}) => ({id,site_code,unit_id,outage}))
  })`);
});
ipcMain.handle('open-local-document', async (_event, relativePath = '') => {
  const docsRoot = app.isPackaged
    ? path.resolve(process.resourcesPath, 'app.asar.unpacked', 'docs')
    : path.resolve(ROOT, 'docs');
  const target = path.resolve(docsRoot, String(relativePath || ''));
  if (docsRoot !== target && !target.startsWith(`${docsRoot}${path.sep}`)) {
    throw new Error('文档路径无效。');
  }
  if (!fs.existsSync(target) || !fs.statSync(target).isFile()) {
    throw new Error('文档不存在，请检查 docs 文件夹。');
  }
  const [safeRoot, safeTarget] = await Promise.all([fs.promises.realpath(docsRoot), fs.promises.realpath(target)]);
  const relativeTarget = path.relative(safeRoot, safeTarget);
  if (!relativeTarget || relativeTarget.startsWith('..') || path.isAbsolute(relativeTarget)) {
    throw new Error('文档路径无效。');
  }
  const error = await shell.openPath(safeTarget);
  if (error) throw new Error(error);
  return { path: target };
});
ipcMain.handle('open-documents-folder', async () => {
  const docsRoot = app.isPackaged
    ? path.resolve(process.resourcesPath, 'app.asar.unpacked', 'docs')
    : path.resolve(ROOT, 'docs');
  if (!fs.existsSync(docsRoot)) throw new Error('说明文档目录不存在。');
  const error = await shell.openPath(docsRoot);
  if (error) throw new Error(error);
  return { path: docsRoot };
});
const EXCEL_EXTENSIONS = new Set(['.xls', '.xlsx', '.xlsm']);
const EXCEL_SCAN_LIMIT = 500;

function scanExcelFiles(directory, depth = 0, collected = []) {
  if (collected.length >= EXCEL_SCAN_LIMIT || depth > 4) return collected;
  let entries = [];
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch (_) {
    return collected;
  }
  for (const entry of entries) {
    if (collected.length >= EXCEL_SCAN_LIMIT) break;
    const full = path.join(directory, entry.name);
    if (entry.isFile() && EXCEL_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
      collected.push(full);
    } else if (entry.isDirectory() && depth < 4 && !entry.name.startsWith('.')) {
      scanExcelFiles(full, depth + 1, collected);
    }
  }
  return collected;
}

ipcMain.handle('select-excel', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', {
    title: '选择指套管解析结果 Excel（可多选）',
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'Excel 工作簿', extensions: ['xlsx', 'xlsm', 'xls'] }]
  });
  return result.canceled ? [] : result.filePaths;
});
ipcMain.handle('select-excel-folder', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', {
    title: '选择包含解析结果 Excel 的文件夹',
    properties: ['openDirectory']
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const folder = result.filePaths[0];
  const files = scanExcelFiles(folder);
  return { folder, files, truncated: files.length >= EXCEL_SCAN_LIMIT };
});
async function authorizedExport(event, data = null) {
  if (!event?.sender || !event.sender.getURL().startsWith(BASE_URL + '/')) throw new Error('导出请求来源无效');
  const cookies = await event.sender.session.cookies.get({url:BASE_URL});
  const cookie = cookies.filter(item => item.name === 'thimble_session').map(item => `${item.name}=${item.value}`).join('; ');
  const route = data ? '/api/security/image-export' : '/api/auth/me';
  const body = data ? JSON.stringify(data) : null;
  return new Promise((resolve,reject) => {
    const headers = {Cookie:cookie};
    if(body)Object.assign(headers,{'Content-Type':'application/json','X-Thimble-Request':'1','Content-Length':Buffer.byteLength(body)});
    const request=http.request(BASE_URL + route,{method:body?'POST':'GET',headers},response => {
      let raw='';response.setEncoding('utf8');response.on('data',chunk => {raw+=chunk;});
      response.on('end',() => {
        try {
          const result=JSON.parse(raw);
          if(response.statusCode!==200)throw new Error(result.error||'请先登录具有导出权限的本地账户');
          if(!data && !result.user.permissions.includes('export.create'))throw new Error('当前账户没有导出权限');
          resolve(result);
        } catch(error){reject(error);}
      });
    });
    request.setTimeout(10000,() => request.destroy(new Error('导出权限校验超时')));
    request.on('error',reject);request.end(body);
  });
}

async function saveExport(event, filePath, content) {
  const session = await authorizedExport(event);
  if (path.extname(filePath).toLowerCase() === '.png') {
    content = require('./png-author.cjs').withPngAuthor(content, session.user.username);
  }
  await saveArtifact(filePath, content);
  try {
    await authorizedExport(event, {
      name:path.basename(filePath),sha256:createHash('sha256').update(content).digest('hex'),
      size_bytes:Buffer.byteLength(content),
    });
  } catch (error) {
    await showOwnedDialog(event, 'showMessageBox', {
      type:'warning', title:'导出记录未登记',
      message:'文件已保存，导出记录暂未登记。',
      detail:`保存位置：${filePath}\n原因：${error.message}\n文件可正常使用，无需重复导出。`,
      buttons:['知道了'],
    });
  }
  return filePath;
}

async function saveOfficeFile(event, payload, title) {
  await authorizedExport(event);
  if (!(payload.bytes instanceof Uint8Array) || payload.bytes.byteLength < 4 ||
      payload.bytes.byteLength > 50 * 1024 * 1024) {
    throw new Error('导出文件大小或格式无效，请重新导出。');
  }
  const workbook = Buffer.from(payload.bytes);
  if (workbook.subarray(0, 4).toString('hex') !== '504b0304') {
    throw new Error('导出文件格式无效，请重新导出。');
  }
  const name = String(payload.defaultName || '')
    .replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
  const ext = path.extname(name).toLowerCase();
  if (!['.xlsx','.docx'].includes(ext)) throw new Error('不支持的导出文件格式。');
  const result = await showOwnedDialog(event, 'showSaveDialog', {
    title,
    defaultPath: path.join(app.getPath('documents'), name),
    filters: [{name:ext === '.xlsx' ? 'Excel 工作簿' : 'Word 文档', extensions:[ext.slice(1)]}],
  });
  if (result.canceled || !result.filePath) return null;
  return saveExport(event, result.filePath, workbook);
}
ipcMain.handle('save-ledger', (event, payload = {}) => saveOfficeFile(event, payload, '保存管子综合台账'));
ipcMain.handle('save-office-file', (event, payload = {}) => saveOfficeFile(event, payload, '保存导出文件'));
ipcMain.handle('save-provenance', async (event, payload = {}) => {
  await authorizedExport(event);
  if (!(payload.bytes instanceof Uint8Array) || !payload.bytes.byteLength || payload.bytes.byteLength > 50 * 1024 * 1024) {
    throw new Error('来源凭证大小或格式无效，请重新导出。');
  }
  const name = String(payload.defaultName || '').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_');
  if (!name.toLowerCase().endsWith('.provenance.json')) throw new Error('来源凭证文件名无效。');
  const content = Buffer.from(payload.bytes);
  try {
    const evidence = JSON.parse(content.toString('utf8'));
    if (!evidence || !(typeof evidence.export_kind === 'string' || typeof evidence.snapshot_id === 'string') ||
        !/^[a-f0-9]{64}$/i.test(evidence.sha256)) throw new Error();
  } catch {
    throw new Error('来源凭证内容无效，请重新导出。');
  }
  const result = await showOwnedDialog(event, 'showSaveDialog', {
    title:'保存来源与核查凭证',
    defaultPath:path.join(app.getPath('documents'), name),
    filters:[{name:'JSON 凭证',extensions:['json']}],
  });
  if (result.canceled || !result.filePath) return null;
  return saveExport(event, result.filePath, content);
});

ipcMain.handle('save-core-image', async (_event, payload = {}) => {
  await authorizedExport(_event);
  const match = String(payload.dataUrl || '').match(/^data:image\/png;base64,([A-Za-z0-9+/=]+)$/);
  if (!match) throw new Error('管板图片数据格式无效');
  const image = Buffer.from(match[1], 'base64');
  if (image.length < 100 || image.length > 20 * 1024 * 1024 || image.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
    throw new Error('管板图片数据校验失败');
  }
  const defaultName = String(payload.defaultName || artifactName('管板缺陷分布', '当前范围', 'png')).replace(/[<>:"/\\|?*]/g, '_');
  const result = await showOwnedDialog(_event, 'showSaveDialog', {
    title: '导出指套管缺陷分布图',
    defaultPath: path.join(app.getPath('documents'), defaultName),
    filters: [{ name: 'PNG 图片', extensions: ['png'] }]
  });
  if (result.canceled || !result.filePath) return null;
  return saveExport(_event, result.filePath, image);
});
ipcMain.handle('save-visualization-image', async (_event, payload = {}) => {
  await authorizedExport(_event);
  const match = String(payload.dataUrl || '').match(/^data:image\/png;base64,([A-Za-z0-9+/=]+)$/);
  if (!match) throw new Error('可视化图片数据格式无效');
  const image = Buffer.from(match[1], 'base64');
  if (image.length < 100 || image.length > 24 * 1024 * 1024 || image.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') {
    throw new Error('可视化图片数据校验失败');
  }
  const defaultName = String(payload.defaultName || artifactName('可视化图表', '当前范围', 'png')).replace(/[<>:"/\\|?*]/g, '_');
  const result = await showOwnedDialog(_event, 'showSaveDialog', {
    title: '导出可视化图表 PNG',
    defaultPath: path.join(app.getPath('documents'), defaultName),
    filters: [{ name: 'PNG 图片', extensions: ['png'] }]
  });
  if (result.canceled || !result.filePath) return null;
  return saveExport(_event, result.filePath, image);
});
ipcMain.handle('open-report-header', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', { title: '导入报告表头设置', properties: ['openFile'], filters: [{ name: '报告表头设置', extensions: ['json'] }] });
  if (result.canceled || !result.filePaths[0]) return null;
  const stat = await fs.promises.stat(result.filePaths[0]);
  if (!stat.isFile() || stat.size > 256 * 1024) throw new Error('报告表头设置文件过大或无效');
  return fs.promises.readFile(result.filePaths[0], 'utf8');
});
ipcMain.handle('save-report-header', async (_event, payload = {}) => {
  await authorizedExport(_event);
  const content = String(payload.content || '');
  if (!content || Buffer.byteLength(content, 'utf8') > 256 * 1024) throw new Error('报告表头设置内容无效');
  JSON.parse(content);
  const defaultName = String(payload.defaultName || artifactName('报告表头设置', '指套管', 'json')).replace(/[<>:"/\\|?*]/g, '_');
  const result = await showOwnedDialog(_event, 'showSaveDialog', { title: '导出报告表头设置', defaultPath: path.join(app.getPath('documents'), defaultName), filters: [{ name: '报告表头设置', extensions: ['json'] }] });
  if (result.canceled || !result.filePath) return null;
  return saveExport(_event, result.filePath, content);
});
ipcMain.handle('select-backup-directory', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', { title: '选择数据库备份的保存文件夹', properties: ['openDirectory', 'createDirectory'] });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle('select-backup-file', async event => {
  const result = await showOwnedDialog(event, 'showOpenDialog', {
    title: '选择要恢复的数据库备份文件',
    properties: ['openFile'],
    filters: [{ name: '数据库备份', extensions: ['db'] }]
  });
  return result.canceled ? null : result.filePaths[0];
});
app.on('window-all-closed', () => app.quit());
let appQuitting = false;
app.on('before-quit', () => { appQuitting = true; });
app.on('before-quit', stopServer);
