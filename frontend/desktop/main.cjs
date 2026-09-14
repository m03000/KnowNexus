const { app, BrowserWindow, Menu, Tray, dialog, ipcMain, nativeImage, net, protocol, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

// Electron does not load the backend's .env file by itself. Load the
// development copy before any paths are derived so source mode and the
// Python backend see the same storage/model configuration.
function loadDevelopmentEnv() {
  if (app.isPackaged) return;
  const envPath = path.resolve(__dirname, '..', '..', '.env');
  if (!fs.existsSync(envPath)) return;
  for (const rawLine of fs.readFileSync(envPath, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const separator = line.indexOf('=');
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    if (!(key in process.env)) process.env[key] = value;
  }
}

loadDevelopmentEnv();

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
const projectRoot = usesBundledBackend ? portableRoot : findProjectRoot();
const developmentBackendCandidates = [
  process.env.KNOWNEXUS_BACKEND_EXECUTABLE,
  path.join(projectRoot, 'dist', 'knownexus-backend', 'knownexus-backend.exe'),
  path.join(projectRoot, 'dist', 'knownexus-backend.exe'),
].filter(Boolean);
const developmentBackend = !app.isPackaged
  ? developmentBackendCandidates.find((candidate) => fs.existsSync(candidate)) || ''
  : '';
const standaloneBackend = usesBundledBackend ? bundledBackend : developmentBackend;
const usesStandaloneBackend = Boolean(standaloneBackend);
const storageRoot = path.resolve(process.env.KNOWNEXUS_STORAGE_ROOT || (app.isPackaged ? portableRoot : projectRoot));
if (usesStandaloneBackend) {
  const desktopData = path.join(storageRoot, 'data', 'desktop');
  fs.mkdirSync(desktopData, { recursive: true });
  app.setPath('userData', desktopData);
  app.setPath('sessionData', desktopData);
}
const backendOutput = [];
let backendProcess = null;
let ownsBackend = false;
let mainWindow = null;
let tray = null;
const multimodalDownloads = new Map();
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
    if (fs.existsSync(path.join(resolved, 'src', 'study_help_agent')) && fs.existsSync(path.join(resolved, 'pyproject.toml'))) return resolved;
  }
  throw new Error('没有找到项目目录。请确认 frontend 位于包含 src/study_help_agent 与 pyproject.toml 的源码目录中。');
}

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
  if (usesStandaloneBackend) return standaloneBackend;
  if (process.env.PERSONAL_AGENT_PYTHON) return process.env.PERSONAL_AGENT_PYTHON;
  const localPython = path.join(projectRoot, '.venv', 'Scripts', 'python.exe');
  return fs.existsSync(localPython) ? localPython : 'python';
}

async function backendIsReady() {
  try {
    const response = await fetch(`${BACKEND_ORIGIN}/health`, { signal: AbortSignal.timeout(1200) });
    if (!response.ok) return false;
    const payload = await response.json();
    return payload.status === 'ok' && payload.app === 'KnowNexus' && payload.version === '0.1.0';
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
    usesStandaloneBackend ? [] : ['-m', 'uvicorn', 'study_help_agent.app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
    {
      cwd: projectRoot,
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        PYTHONUNBUFFERED: '1',
        LLM_API_KEY: process.env.LLM_API_KEY || 'not-configured',
        ...(usesStandaloneBackend ? {
          KNOWNEXUS_STORAGE_ROOT: storageRoot,
          KNOWNEXUS_CONFIG_DIRECTORY: path.join(storageRoot, 'data'),
        } : {}),
        DATABASE_PATH: process.env.DATABASE_PATH || path.join(usesBundledBackend ? storageRoot : app.getPath('userData'), 'data', 'knownexus.db'),
        RUNTIME_DATA_DIRECTORY: process.env.RUNTIME_DATA_DIRECTORY || path.join(usesBundledBackend ? storageRoot : app.getPath('userData'), 'data'),
        RUNTIME_LOG_DIRECTORY: process.env.RUNTIME_LOG_DIRECTORY || path.join(usesBundledBackend ? storageRoot : app.getPath('userData'), 'logs'),
        OBSERVABILITY_LOG_DIRECTORY: process.env.OBSERVABILITY_LOG_DIRECTORY || path.join(usesBundledBackend ? storageRoot : app.getPath('userData'), 'logs', 'observability'),
        RAG_MODEL_CACHE_DIRECTORY: process.env.RAG_MODEL_CACHE_DIRECTORY || (usesBundledBackend ? path.join(storageRoot, 'model') : path.join(app.getPath('userData'), 'models', 'huggingface', 'hub')),
        LEARNING_WHISPER_MODEL: process.env.LEARNING_WHISPER_MODEL || (usesBundledBackend ? path.join(portableRoot, 'model', 'whisper-small') : (fs.existsSync(path.join(app.getPath('userData'), 'models', 'whisper-small', 'model.bin')) ? path.join(app.getPath('userData'), 'models', 'whisper-small') : 'small')),
        TESSERACT_CMD: process.env.TESSERACT_CMD || (usesBundledBackend ? path.join(portableRoot, 'tesseract', 'tesseract.exe') : (fs.existsSync(path.join(app.getPath('userData'), 'models', 'ocr', 'tesseract', 'tesseract.exe')) ? path.join(app.getPath('userData'), 'models', 'ocr', 'tesseract', 'tesseract.exe') : '')),
        TESSDATA_PREFIX: process.env.TESSDATA_PREFIX || (usesBundledBackend ? path.join(portableRoot, 'tesseract', 'tessdata') : (fs.existsSync(path.join(app.getPath('userData'), 'models', 'ocr', 'tesseract', 'tessdata')) ? path.join(app.getPath('userData'), 'models', 'ocr', 'tesseract', 'tessdata') : '')),
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

function multimodalModelsRoot() {
  return path.join(app.getPath('userData'), 'models');
}

function directoryBytes(directory) {
  if (!fs.existsSync(directory)) return 0;
  return fs.readdirSync(directory, { withFileTypes: true }).reduce((sum, entry) => {
    const target = path.join(directory, entry.name);
    return sum + (entry.isDirectory() ? directoryBytes(target) : fs.statSync(target).size);
  }, 0);
}

function multimodalStatus() {
  const root = multimodalModelsRoot();
  const definitions = [
    { kind: 'ocr', name: 'Tesseract OCR', model_id: 'Tesseract 5.4 · chi_sim + eng', directory: path.join(root, 'ocr', 'tesseract'), expected: 185000000, required: ['tesseract.exe', path.join('tessdata', 'chi_sim.traineddata'), path.join('tessdata', 'eng.traineddata')] },
    { kind: 'whisper', name: 'Whisper 语音识别', model_id: 'Systran/faster-whisper-small', directory: path.join(root, 'whisper-small'), expected: 486000000, required: ['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'] },
  ];
  const items = definitions.map((definition) => {
    const state = multimodalDownloads.get(definition.kind) || {};
    const installed = definition.required.every((relative) => fs.existsSync(path.join(definition.directory, relative)) && fs.statSync(path.join(definition.directory, relative)).size > 0);
    const downloaded = state.downloadedBytes || directoryBytes(definition.directory);
    const expected = state.expectedBytes || definition.expected;
    return { kind: definition.kind, name: definition.name, model_id: definition.model_id, directory: definition.directory, installed, downloading: state.status === 'downloading', phase: state.phase || '', downloaded_bytes: downloaded, expected_bytes: expected, download_progress: installed ? 1 : Math.min(.98, downloaded / Math.max(1, expected)) };
  });
  return { items, ready: items.every((item) => item.installed) };
}

async function downloadMultimodalFile(kind, url, target, completed = 0) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const response = await net.fetch(url, { headers: { 'User-Agent': `KnowNexus/${app.getVersion()}` } });
  if (!response.ok || !response.body) throw new Error(`下载失败：HTTP ${response.status}`);
  const state = multimodalDownloads.get(kind);
  const length = Number(response.headers.get('content-length') || 0);
  state.expectedBytes = Math.max(state.expectedBytes || 0, completed + length);
  const temporary = `${target}.incomplete`;
  const output = fs.createWriteStream(temporary);
  const reader = response.body.getReader();
  let written = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      output.write(Buffer.from(value));
      written += value.byteLength;
      state.downloadedBytes = completed + written;
    }
  } finally {
    await new Promise((resolve, reject) => output.end((error) => error ? reject(error) : resolve()));
  }
  if (written < 1000) throw new Error(`下载文件不完整：${path.basename(target)}`);
  fs.renameSync(temporary, target);
  return written;
}

async function installDesktopMultimodal(kind) {
  const root = multimodalModelsRoot();
  const state = { status: 'downloading', phase: '', downloadedBytes: 0, expectedBytes: kind === 'ocr' ? 60000000 : 486000000 };
  multimodalDownloads.set(kind, state);
  try {
    if (kind === 'ocr') {
      const runtime = path.join(root, 'ocr', 'tesseract');
      const installer = path.join(root, 'ocr', 'tesseract-installer.exe');
      state.phase = '下载 OCR 引擎';
      let completed = await downloadMultimodalFile(kind, 'https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe', installer);
      state.phase = '安装 OCR 引擎';
      fs.mkdirSync(runtime, { recursive: true });
      await new Promise((resolve, reject) => {
        const child = spawn(installer, ['/S', `/D=${runtime}`], { windowsHide: true });
        child.once('error', reject); child.once('exit', (code) => code === 0 ? resolve() : reject(new Error(`OCR 引擎安装失败（${code}）`)));
      });
      for (const language of ['chi_sim', 'eng']) {
        state.phase = `下载 ${language} 语言模型`;
        completed += await downloadMultimodalFile(kind, `https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/${language}.traineddata`, path.join(runtime, 'tessdata', `${language}.traineddata`), completed);
      }
      fs.rmSync(installer, { force: true });
    } else if (kind === 'whisper') {
      const directory = path.join(root, 'whisper-small');
      let completed = 0;
      for (const file of ['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt']) {
        state.phase = `下载 Whisper ${file}`;
        completed += await downloadMultimodalFile(kind, `https://huggingface.co/Systran/faster-whisper-small/resolve/main/${file}?download=true`, path.join(directory, file), completed);
      }
    } else throw new Error('不支持的多模态模型');
    return multimodalStatus();
  } finally {
    multimodalDownloads.delete(kind);
  }
}

async function testDesktopMultimodal(kind) {
  const status = multimodalStatus();
  const item = status.items.find((entry) => entry.kind === kind);
  if (!item?.installed) throw new Error('请先完成安装');
  if (kind === 'ocr') {
    await new Promise((resolve, reject) => {
      const child = spawn(path.join(item.directory, 'tesseract.exe'), ['--list-langs'], { windowsHide: true, env: { ...process.env, TESSDATA_PREFIX: path.join(item.directory, 'tessdata') } });
      child.once('error', reject); child.once('exit', (code) => code === 0 ? resolve() : reject(new Error(`OCR 测试失败（${code}）`)));
    });
  }
  return { ...status, test: { ok: true, kind, message: kind === 'ocr' ? 'OCR 引擎与中英文模型测试通过' : 'Whisper small 模型文件完整；重启后将由本地推理引擎加载' } };
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

ipcMain.handle('desktop:multimodal-status', () => multimodalStatus());
ipcMain.handle('desktop:multimodal-install', (event, kind) => installDesktopMultimodal(String(kind || '')));
ipcMain.handle('desktop:multimodal-test', (event, kind) => testDesktopMultimodal(String(kind || '')));

ipcMain.handle('desktop:pick-cookie-file', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: '选择 Netscape 格式的 cookies.txt',
    properties: ['openFile'],
    filters: [
      { name: 'Cookie 文件', extensions: ['txt'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePaths[0]) return null;
  return { sourcePath: result.filePaths[0], name: path.basename(result.filePaths[0]) };
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
