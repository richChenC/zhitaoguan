const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require('electron');
const { spawn } = require('node:child_process');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const ROOT = path.resolve(__dirname, '..');
const PORT = '18765';
const BASE_URL = `http://127.0.0.1:${PORT}`;
const URL = `${BASE_URL}/?build=20260806d`;
const SERVICE_VERSION = '2026.08.06';
let serverProcess = null;
let mainWindow = null;
let serviceLogPath = null;

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

function isServerReady() {
  return new Promise(resolve => {
    const request = http.get(`${BASE_URL}/api/health`, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try {
          const payload = JSON.parse(body);
          resolve(response.statusCode === 200 && payload.ok === true && payload.service === 'thimble-local' && payload.version === SERVICE_VERSION);
        } catch (_) { resolve(false); }
      });
    });
    request.setTimeout(800, () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
  });
}

async function ensureServer() {
  if (await isServerReady()) return;
  const logDirectory = path.join(app.getPath('userData'), 'logs');
  fs.mkdirSync(logDirectory, { recursive: true });
  serviceLogPath = path.join(logDirectory, 'desktop-service.log');
  const writeLog = chunk => {
    if (!serviceLogPath) return;
    fs.appendFile(serviceLogPath, Buffer.isBuffer(chunk) ? chunk : String(chunk), () => {});
  };
  const environment = { ...process.env, THIMBLE_PORT: PORT };
  if (app.isPackaged) {
    environment.THIMBLE_DATA_DIR ||= path.join(app.getPath('userData'), 'data');
    environment.THIMBLE_OUTPUT_DIR ||= path.join(app.getPath('userData'), 'output', 'excel');
    environment.THIMBLE_LOG_PATH ||= path.join(app.getPath('userData'), 'logs', 'server.log');
  }
  for (const command of pythonCandidates()) {
    let spawnError = null;
    serverProcess = spawn(command, ['server.py'], {
      cwd: ROOT,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: environment
    });
    serverProcess.stdout.on('data', writeLog);
    serverProcess.stderr.on('data', writeLog);
    serverProcess.once('error', error => { spawnError = error; });
    serverProcess.once('exit', (code, signal) => { writeLog(`\n[desktop] service (${command}) exited code=${code} signal=${signal}\n`); });
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 200));
      if (await isServerReady()) return;
      if (spawnError) break;
    }
    if (serverProcess && !serverProcess.killed) serverProcess.kill();
    writeLog(`[desktop] runtime failed: ${command}${spawnError ? ` - ${spawnError.message}` : ''}\n`);
  }
  throw new Error(`本地数据服务启动失败，请查看 ${path.join(logDirectory, 'desktop-service.log')}。`);
}

async function createWindow() {
  try {
    await ensureServer();
  } catch (error) {
    dialog.showErrorBox('指套管检测工作站', error.message);
    app.quit();
    return;
  }
  mainWindow = new BrowserWindow({
    title: '指套管检测工作站',
    width: 1480,
    height: 960,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: '#f3f5f6',
    show: false,
    autoHideMenuBar: true,
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.cjs') }
  });
  Menu.setApplicationMenu(null);
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:/i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  await mainWindow.loadURL(URL);
  mainWindow.maximize();
  mainWindow.show();
}

app.whenReady().then(createWindow);
ipcMain.handle('select-directory', async () => {
  const result = await dialog.showOpenDialog({ title: '选择指套管检测数据文件夹', properties: ['openDirectory'] });
  return result.canceled ? null : result.filePaths[0];
});
ipcMain.handle('select-excel', async () => {
  const result = await dialog.showOpenDialog({
    title: '选择指套管解析结果 Excel',
    properties: ['openFile'],
    filters: [{ name: 'Excel 工作簿', extensions: ['xlsx', 'xlsm'] }]
  });
  return result.canceled ? null : result.filePaths[0];
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', () => {
  if (serverProcess && !serverProcess.killed) serverProcess.kill();
});
