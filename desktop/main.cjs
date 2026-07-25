const { app, BrowserWindow, dialog, ipcMain, Menu, shell } = require('electron');
const { spawn } = require('node:child_process');
const http = require('node:http');
const path = require('node:path');
const fs = require('node:fs');

const ROOT = path.resolve(__dirname, '..');
const URL = 'http://127.0.0.1:8765';
let serverProcess = null;
let mainWindow = null;

function pythonCommand() {
  const candidates = [
    process.env.THIMBLE_PYTHON,
    path.join(ROOT, '.venv', 'Scripts', 'python.exe'),
    path.join(process.env.USERPROFILE || '', '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'python', 'python.exe'),
    path.join(process.resourcesPath || '', 'python', 'python.exe'),
  ].filter(Boolean);
  return candidates.find(candidate => fs.existsSync(candidate)) || (process.platform === 'win32' ? 'py' : 'python3');
}

function isServerReady() {
  return new Promise(resolve => {
    const request = http.get(`${URL}/api/overview`, response => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.setTimeout(800, () => { request.destroy(); resolve(false); });
    request.on('error', () => resolve(false));
  });
}

async function ensureServer() {
  if (await isServerReady()) return;
  const command = pythonCommand();
  let spawnError = null;
  serverProcess = spawn(command, ['server.py'], {
    cwd: ROOT,
    windowsHide: true,
    stdio: 'ignore'
  });
  serverProcess.once('error', error => { spawnError = error; });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 200));
    if (await isServerReady()) return;
    if (spawnError) throw new Error('无法启动本地 Python 服务（' + command + '）：' + spawnError.message);
  }
  throw new Error('本地数据服务启动失败，请确认 Python 已安装。');
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
