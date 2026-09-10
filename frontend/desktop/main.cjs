const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, net, protocol, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const BACKEND_PORT = 8765;
const BACKEND_ORIGIN = `http://127.0.0.1:${BACKEND_PORT}`;
const APP_ICON = path.join(__dirname, 'assets', 'knownexus-icon.png');
let packagedUpdateApi = '';
try { packagedUpdateApi = JSON.parse(fs.readFileSync(path.join(__dirname, 'update-config.json'), 'utf8')).apiUrl || ''; } catch {}
const UPDATE_API = String(process.env.KNOWNEXUS_UPDATE_API || packagedUpdateApi).trim();
const frontendRoot = app.isPackaged ? app.getAppPath() : path.resolve(__dirname, '..');
const portableRoot = path.dirname(process.execPath);
const bundledBackend = path.join(portableRoot, 'backend', 'knownexus-backend.exe');
const usesBundledBackend = app.isPackaged && fs.existsSync(bundledBackend);
const backendOutput = [];
let backendProcess = null;
let ownsBackend = false;
let mainWindow = null;
let tray = null;
const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) app.quit();

protocol.registerSchemesAsPrivileged([
  { scheme: 'knownexus-media', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

function findProjectRoot() {
  const candidates = [process.env.PERSONAL_AGENT_PROJECT_ROOT, process.cwd(), path.resolve(__dirname, '..', '..')].filter(Boolean);
  let cursor = path.dirname(process.execPath);
  for (let depth = 0; depth < 7; depth += 1) {
    candidates.push(cursor);
    cursor = path.dirname(cursor);
  }
  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (fs.existsSync(path.join(resolved, 'src', 'study_help_agent')) && fs.existsSync(path.join(resolved, '.venv', 'Scripts', 'python.exe'))) return resolved;
  }
  throw new Error('没有找到项目目录。请确认启动器位于项目根目录，并且 .venv 已创建。');
}

const projectRoot = usesBundledBackend ? portableRoot : findProjectRoot();

function wallpaperStatePath() {
  return path.join(app.getPath('userData'), 'workspace-wallpaper.json');
}

function wallpaperDirectoryPath() {
  return path.join(app.getPath('userData'), 'wallpaper');
}

function wallpaperItemDescriptor(filePath, displayName = '') {
  const id = path.basename(filePath);
  return {
    id,
    path: filePath,
    name: displayName || id.replace(/^\d+-/, ''),
    type: mediaTypeFor(filePath),
    url: `knownexus-media://wallpaper/${encodeURIComponent(id)}?v=${fs.statSync(filePath).mtimeMs}`,
  };
}

function wallpaperDescriptor() {
  try {
    const state = JSON.parse(fs.readFileSync(wallpaperStatePath(), 'utf8'));
    if (!state.path || !fs.existsSync(state.path)) return null;
    return wallpaperItemDescriptor(state.path, state.name);
  } catch {
    return null;
  }
}

function wallpaperLibrary() {
  const directory = wallpaperDirectoryPath();
  if (!fs.existsSync(directory)) return [];
  const active = wallpaperDescriptor();
  return fs.readdirSync(directory)
    .map((name) => path.join(directory, name))
    .filter((filePath) => fs.statSync(filePath).isFile() && mediaTypeFor(filePath) !== 'application/octet-stream')
    .map((filePath) => ({ ...wallpaperItemDescriptor(filePath, active?.path === filePath ? active.name : ''), active: active?.path === filePath }))
    .sort((a, b) => fs.statSync(b.path).mtimeMs - fs.statSync(a.path).mtimeMs);
}

function mediaTypeFor(filePath) {
  const suffix = path.extname(filePath).toLowerCase();
  const types = { '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp', '.gif': 'image/gif', '.bmp': 'image/bmp' };
  return types[suffix] || 'application/octet-stream';
}

function pythonExecutable() {
  if (usesBundledBackend) return bundledBackend;
  if (process.env.PERSONAL_AGENT_PYTHON) return process.env.PERSONAL_AGENT_PYTHON;
  const localPython = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
  return fs.existsSync(localPython) ? localPython : 'python';
}

async function backendIsReady() {
  try {
    const response = await fetch(`${BACKEND_ORIGIN}/health`, { signal: AbortSignal.timeout(1200) });
    if (!response.ok) return false;
    const payload = await response.json();
    return payload.status === 'ok';
  } catch {
    return false;
  }
}

function rememberBackendOutput(chunk) {
  const text = chunk.toString('utf8').trim();
  if (!text) return;
  backendOutput.push(text);
  if (backendOutput.length > 50) backendOutput.shift();
  console.log(`[backend] ${text}`);
}

function startBackend() {
  backendProcess = spawn(
    pythonExecutable(),
    usesBundledBackend ? [] : ['-m', 'uvicorn', 'study_help_agent.app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
    {
      cwd: projectRoot,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONUNBUFFERED: '1',
        LLM_API_KEY: process.env.LLM_API_KEY || 'not-configured',
        DATABASE_PATH: process.env.DATABASE_PATH || path.join(app.getPath('userData'), 'data', 'knownexus.db'),
        RUNTIME_DATA_DIRECTORY: process.env.RUNTIME_DATA_DIRECTORY || path.join(app.getPath('userData'), 'data'),
        RUNTIME_LOG_DIRECTORY: process.env.RUNTIME_LOG_DIRECTORY || path.join(app.getPath('userData'), 'logs'),
        RAG_MODEL_CACHE_DIRECTORY: process.env.RAG_MODEL_CACHE_DIRECTORY || path.join(app.getPath('userData'), 'models', 'huggingface', 'hub'),
        LEARNING_WHISPER_MODEL: process.env.LEARNING_WHISPER_MODEL || (usesBundledBackend ? path.join(portableRoot, 'models', 'whisper-small') : 'small'),
        TESSERACT_CMD: process.env.TESSERACT_CMD || (usesBundledBackend ? path.join(portableRoot, 'tesseract', 'tesseract.exe') : ''),
        TESSDATA_PREFIX: process.env.TESSDATA_PREFIX || (usesBundledBackend ? path.join(portableRoot, 'tesseract', 'tessdata') : ''),
        CODEX_WATCHER_ENABLED: process.env.CODEX_WATCHER_ENABLED || 'false',
        PYTHONPATH: [path.join(projectRoot, 'src'), process.env.PYTHONPATH || ''].filter(Boolean).join(path.delimiter),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
  );
  ownsBackend = true;
  backendProcess.stdout.on('data', rememberBackendOutput);
  backendProcess.stderr.on('data', rememberBackendOutput);
  backendProcess.on('exit', (code) => {
    backendProcess = null;
    if (!app.isQuitting && mainWindow && code !== 0) {
      dialog.showErrorBox('后端已停止', `本地后端意外退出（${code ?? '未知状态'}）。\n\n${backendOutput.slice(-8).join('\n')}`);
    }
  });
}

async function ensureBackend() {
  if (await backendIsReady()) return;
  startBackend();
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if (await backendIsReady()) return;
    if (!backendProcess) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`本地后端启动失败。\n\n${backendOutput.slice(-12).join('\n')}`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1520,
    height: 940,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    backgroundColor: '#080b14',
    autoHideMenuBar: true,
    frame: false,
    icon: APP_ICON,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (event, url) => {
    const currentUrl = mainWindow?.webContents.getURL() || '';
    if (url !== currentUrl && /^https?:\/\//i.test(url)) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
  mainWindow.webContents.on('before-input-event', (event, input) => {
    if (input.key === 'F12' || (input.control && input.shift && input.key.toLowerCase() === 'i')) {
      event.preventDefault();
      mainWindow.webContents.toggleDevTools();
    }
  });
  mainWindow.once('ready-to-show', () => mainWindow.show());
  mainWindow.on('close', (event) => {
    if (app.isQuitting) return;
    event.preventDefault();
    mainWindow.hide();
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  return mainWindow.loadFile(path.join(frontendRoot, 'dist', 'index.html'));
}

function showMainWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createWindow();
    return;
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function createTray() {
  if (tray) return tray;
  let icon = nativeImage.createFromPath(APP_ICON);
  if (!icon.isEmpty()) icon = icon.resize({ width: 24, height: 24, quality: 'best' });
  if (icon.isEmpty()) icon = nativeImage.createFromDataURL('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAIiSURBVFhH1VexTsMwEO3I2JGRT2Bkg6FJJaaOqKlURpZKjB068AcdkfoDbGWqGBkrdemISFJFqlSRqQwdUCfjcy6K7VwSJ2mQeNKTwD77PV/sc936t3A67pXT9W5kYlczGN4G5/2O++BY/tvA9lkOl47tjofd4AKH1sPwOmg7lvfk2N4PIVbAzTMYx6nKQ6TW9r7pyc0ojFv+HU5pDj7ovtqqaUIWcepigDg1SW1amylKZAPTfrKV64SNjFJpwIap+82LCIvrW5+XKKkCUkQNihiyNUOswsy+9VRup8mP8itKJsDV56ReMsCObDGi+0wMAFNZgOJBBSaUDXDs9mxC9JkagBqB0hF44zIdJFMzwJGIlTfAj+UXSkfVjgpSmYiEuyP+dWAzrc88A9JngIuFClApi0hm5lutjxqbwbhCDmyvRwYo1ESmB/wPNmQ1A3zfPQoDUByoAJW6yJYtdtiwOlQzEJdnSAUVoJJY5WjPQmyLUTIDY2EAyi8VoJJO82yFjYgyBuDOEQagCJEBCrO+c9IOKJUBvvmFAQB3E1BBCbMM+Gwyj4+luQGouvz4n6F80T1weqbuAygKVGBz9HoonQBc0cEn5xolVfxdFojVxyi+FetSuwUp8B36Qg+uzaWy87MAQQ2YAPE2SpgBajUxUQXyB4rJyilgmX5PT2pAy//I3XBlABPBZ8n/3RhRvB/jOt8EoreDOxZvRpm8vVyqW61fBbWSwHoTcvIAAAAASUVORK5CYII=');
  tray = new Tray(icon);
  tray.setToolTip(app.getName());
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: '打开主界面', click: showMainWindow },
    { type: 'separator' },
    { label: `退出 ${app.getName()}`, click: () => app.quit() },
  ]));
  tray.on('click', showMainWindow);
  tray.on('double-click', showMainWindow);
  return tray;
}

ipcMain.handle('desktop:pick-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择要关联并加入知识库的文件',
    properties: ['openFile'],
    filters: [
      { name: '支持的文档', extensions: ['pdf', 'doc', 'docx', 'md', 'txt', 'rtf', 'html', 'htm', 'png', 'jpg', 'jpeg'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const sourcePath = result.filePaths[0];
  return { sourcePath, name: path.basename(sourcePath), mediaType: '' };
});

ipcMain.handle('desktop:pick-directory', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 Obsidian Vault 文件夹',
    properties: ['openDirectory', 'createDirectory'],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  return result.filePaths[0];
});

ipcMain.handle('desktop:window-action', (event, action) => {
  const target = BrowserWindow.fromWebContents(event.sender);
  if (!target) return { maximized: false };
  if (action === 'minimize') target.minimize();
  if (action === 'maximize') {
    if (target.isMaximized()) target.unmaximize();
    else target.maximize();
  }
  if (action === 'close') target.close();
  return { maximized: target.isMaximized() };
});

function normalizedVersion(value) {
  return String(value || '').trim().replace(/^v/i, '').split('-')[0]
    .split('.').map((part) => Number.parseInt(part, 10) || 0).slice(0, 3);
}

function isNewerVersion(candidate, current) {
  const next = normalizedVersion(candidate);
  const now = normalizedVersion(current);
  for (let index = 0; index < 3; index += 1) {
    if ((next[index] || 0) !== (now[index] || 0)) return (next[index] || 0) > (now[index] || 0);
  }
  return false;
}

ipcMain.handle('desktop:check-for-updates', async () => {
  const currentVersion = app.getVersion();
  if (!UPDATE_API) return { configured: false, currentVersion, available: false };
  try {
    const response = await net.fetch(UPDATE_API, {
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': `KnowNexus/${currentVersion}` },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const release = await response.json();
    const latestVersion = String(release.tag_name || release.name || '').replace(/^v/i, '');
    const assets = Array.isArray(release.assets) ? release.assets : [];
    const portableAsset = assets.find((asset) => /windows.*portable.*\.zip$/i.test(asset.name || ''))
      || assets.find((asset) => /\.zip$/i.test(asset.name || ''));
    return {
      configured: true,
      currentVersion,
      available: !release.draft && isNewerVersion(latestVersion, currentVersion),
      latestVersion,
      releaseName: release.name || `KnowNexus ${latestVersion}`,
      releaseUrl: release.html_url || '',
      releaseNotes: release.body || '',
      publishedAt: release.published_at || '',
      assetName: portableAsset?.name || '',
      assetSize: portableAsset?.size || 0,
      assetUrl: portableAsset?.browser_download_url || '',
    };
  } catch (error) {
    return { configured: true, currentVersion, available: false, error: error.message };
  }
});

ipcMain.handle('desktop:open-update-page', async (event, releaseUrl) => {
  const url = String(releaseUrl || '');
  if (!/^https:\/\/(github\.com|objects\.githubusercontent\.com)\//i.test(url)) return false;
  await shell.openExternal(url);
  return true;
});

ipcMain.handle('desktop:get-wallpaper', () => wallpaperDescriptor());
ipcMain.handle('desktop:list-wallpapers', () => wallpaperLibrary());

ipcMain.handle('desktop:pick-wallpaper', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择工作区壁纸',
    properties: ['openFile'],
    filters: [
      { name: '图片和视频', extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'mp4', 'webm', 'mov'] },
    ],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  const sourcePath = result.filePaths[0];
  const wallpaperDirectory = wallpaperDirectoryPath();
  fs.mkdirSync(wallpaperDirectory, { recursive: true });
  const target = path.join(wallpaperDirectory, `${Date.now()}-${path.basename(sourcePath)}`);
  fs.copyFileSync(sourcePath, target);
  fs.writeFileSync(wallpaperStatePath(), JSON.stringify({ path: target, name: path.basename(sourcePath), type: mediaTypeFor(target) }), 'utf8');
  return wallpaperDescriptor();
});

ipcMain.handle('desktop:select-wallpaper', (event, id) => {
  const target = path.join(wallpaperDirectoryPath(), path.basename(String(id || '')));
  if (!fs.existsSync(target)) return null;
  fs.writeFileSync(wallpaperStatePath(), JSON.stringify({ path: target, name: path.basename(target).replace(/^\d+-/, ''), type: mediaTypeFor(target) }), 'utf8');
  return wallpaperDescriptor();
});

ipcMain.handle('desktop:clear-wallpaper', () => {
  const current = wallpaperDescriptor();
  if (current?.path) fs.rmSync(current.path, { force: true });
  fs.rmSync(wallpaperStatePath(), { force: true });
  return true;
});

app.on('second-instance', () => showMainWindow());

app.whenReady().then(async () => {
  if (!hasSingleInstanceLock) return;
  try {
    protocol.handle('knownexus-media', (request) => {
      const descriptor = wallpaperDescriptor();
      if (!descriptor || new URL(request.url).hostname !== 'wallpaper') return new Response('Not found', { status: 404 });
      return net.fetch(pathToFileURL(descriptor.path).toString());
    });
    await ensureBackend();
    await createWindow();
    createTray();
  } catch (error) {
    dialog.showErrorBox('KnowNexus 启动失败', error.message);
    app.quit();
  }
});

app.on('activate', () => {
  showMainWindow();
});

app.on('before-quit', () => {
  app.isQuitting = true;
  if (tray) {
    tray.destroy();
    tray = null;
  }
  if (ownsBackend && backendProcess) backendProcess.kill();
});

// Closing the last window keeps the tray application and local backend alive.
app.on('window-all-closed', () => {});
