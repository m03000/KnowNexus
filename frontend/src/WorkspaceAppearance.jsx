import { useEffect, useMemo, useState } from 'react';

const DB_NAME = 'personal-agent-appearance';
const STORE_NAME = 'assets';
const ASSET_KEY = 'workspace-background';
const CONFIG_KEY = 'personal-agent:workspace-appearance';
const CARD_OPACITY_KEY = 'personal-agent:card-transparency-v2';

const defaults = { enabled: false, darkness: 25, wallpaperBlur: 0, border: 35, glass: 16, wallpaperVersion: 3 };
const cardOpacityDefaults = { dashboard: 0, dashboardGlass: 22, chat: 35, chatGlass: 18, note: 0, noteGlass: 6, code: 0, codeGlass: 8, starBrief: 0, starBriefGlass: 8, starSource: 0, starSourceGlass: 10 };

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readAsset() {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = database.transaction(STORE_NAME).objectStore(STORE_NAME).get(ASSET_KEY);
    request.onsuccess = () => resolve(request.result || null);
    request.onerror = () => reject(request.error);
  });
}

async function readAssets() {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = database.transaction(STORE_NAME).objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve([...new Map((request.result || []).filter((item) => item?.id).map((item) => [item.id, item])).values()]);
    request.onerror = () => reject(request.error);
  });
}

async function writeAsset(file) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite');
    const record = { id: `${Date.now()}-${file.name}`, name: file.name, type: file.type, file };
    transaction.objectStore(STORE_NAME).put(record, record.id);
    transaction.objectStore(STORE_NAME).put(record, ASSET_KEY);
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
}

async function removeAsset(id) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, 'readwrite');
    transaction.objectStore(STORE_NAME).delete(ASSET_KEY);
    if (id) transaction.objectStore(STORE_NAME).delete(id);
    transaction.oncomplete = resolve;
    transaction.onerror = () => reject(transaction.error);
  });
}

export function useWorkspaceAppearance() {
  const [config, setConfig] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CONFIG_KEY) || '{}');
      return saved.wallpaperVersion === defaults.wallpaperVersion
        ? { ...defaults, ...saved }
        : { ...defaults, ...saved, enabled: false, wallpaperVersion: defaults.wallpaperVersion };
    }
    catch { return defaults; }
  });
  const [asset, setAsset] = useState(null);
  const [assets, setAssets] = useState([]);

  const refreshAssets = async () => {
    const items = window.desktopAPI?.listWallpapers
      ? await window.desktopAPI.listWallpapers()
      : await readAssets();
    setAssets(items || []);
    return items || [];
  };

  useEffect(() => {
    if (window.desktopAPI?.getWallpaper) {
      Promise.all([window.desktopAPI.getWallpaper(), refreshAssets()]).then(([current]) => setAsset(current)).catch(() => setAsset(null));
    } else {
      Promise.all([readAsset(), refreshAssets()]).then(([current]) => setAsset(current)).catch(() => setAsset(null));
    }
  }, []);
  useEffect(() => { localStorage.setItem(CONFIG_KEY, JSON.stringify(config)); }, [config]);

  const update = (patch) => setConfig((current) => ({ ...current, ...patch }));
  const upload = async (file) => {
    if (!file || (!file.type.startsWith('image/') && !file.type.startsWith('video/'))) {
      throw new Error('请选择图片或视频文件');
    }
    await writeAsset(file);
    const items = await refreshAssets();
    const selected = items.find((item) => item.name === file.name) || items[0];
    setAsset(selected);
    update({ enabled: true });
  };
  const uploadDesktop = async () => {
    const selected = await window.desktopAPI?.pickWallpaper?.();
    if (!selected) return;
    setAsset(selected);
    await refreshAssets();
    update({ enabled: true });
  };

  const selectAsset = async (item) => {
    const selected = window.desktopAPI?.selectWallpaper
      ? await window.desktopAPI.selectWallpaper(item.id)
      : item;
    if (!selected) return;
    setAsset(selected);
    if (!window.desktopAPI?.selectWallpaper) {
      const database = await openDatabase();
      const transaction = database.transaction(STORE_NAME, 'readwrite');
      transaction.objectStore(STORE_NAME).put(selected, ASSET_KEY);
    }
    update({ enabled: true });
  };
  const clear = async () => {
    if (window.desktopAPI?.clearWallpaper) await window.desktopAPI.clearWallpaper();
    else await removeAsset(asset?.id);
    setAsset(null); await refreshAssets(); update({ enabled: false });
  };

  return { config, asset, assets, update, upload, uploadDesktop, selectAsset, clear, reset: () => setConfig(defaults) };
}

export function WorkspaceBackdrop({ asset, config }) {
  const url = useMemo(() => asset?.url || (asset?.file ? URL.createObjectURL(asset.file) : ''), [asset]);
  useEffect(() => () => { if (url?.startsWith('blob:')) URL.revokeObjectURL(url); }, [url]);
  if (!config.enabled || !url) return <div className="workspace-backdrop workspace-backdrop-default" />;
  const mediaStyle = { filter: `blur(${config.wallpaperBlur}px)`, transform: `scale(${1 + config.wallpaperBlur * 0.006})` };
  return <div className="workspace-backdrop" aria-hidden="true">
    {asset.type.startsWith('video/')
      ? <video src={url} style={mediaStyle} autoPlay muted loop playsInline />
      : <img src={url} style={mediaStyle} alt="" />}
    <div className="workspace-backdrop-shade" style={{ background: `rgba(3, 5, 12, ${config.darkness / 100})` }} />
    <div className="workspace-backdrop-aurora" />
  </div>;
}

export function AppearanceControls({ appearance }) {
  const { config, asset, assets, update, upload, uploadDesktop, selectAsset, clear } = appearance;
  const slider = (label, key, max, suffix) => <label className="appearance-slider">
    <span>{label}<b>{config[key]}{suffix}</b></span>
    <input type="range" min="0" max={max} value={config[key]} onChange={(event) => update({ [key]: Number(event.target.value) })} />
  </label>;
  return <section className="appearance-settings-card">
    <div className="appearance-settings-heading">
      <div><strong>工作区壁纸</strong><p>仅应用于对话、笔记和代码区域，不影响右侧导航及知识图谱。</p></div>
      {window.desktopAPI?.pickWallpaper
        ? <button type="button" className="appearance-upload" onClick={() => uploadDesktop().catch((error) => alert(error.message))}>上传图片或视频</button>
        : <label className="appearance-upload"><input type="file" accept="image/*,video/*" onChange={(event) => upload(event.target.files?.[0]).catch((error) => alert(error.message))} />上传图片或视频</label>}
    </div>
    <div className="appearance-preview">
      {asset ? <><span>{asset.type.startsWith('video/') ? '动态视频' : '静态图片'}</span><strong>{asset.name}</strong></> : <p>尚未上传工作区壁纸</p>}
      <div><button type="button" onClick={() => update({ enabled: !config.enabled })} disabled={!asset}>{config.enabled ? '暂停显示' : '启用显示'}</button><button type="button" onClick={clear} disabled={!asset}>清除</button></div>
    </div>
    {!!assets?.length && <div className="appearance-library" aria-label="本地壁纸库">
      {assets.map((item) => <button type="button" className={item.id === asset?.id ? 'active' : ''} key={item.id} onClick={() => selectAsset(item)} title={item.name}>
        <span>{item.type?.startsWith('video/') ? '视频' : '图片'}</span><strong>{item.name}</strong><i>{item.id === asset?.id ? '使用中' : '选择'}</i>
      </button>)}
    </div>}
    <div className="appearance-sliders">
      {slider('壁纸模糊', 'wallpaperBlur', 60, 'px')}
      {slider('暗化', 'darkness', 100, '%')}
      {slider('边框', 'border', 100, '%')}
      {slider('玻璃', 'glass', 40, 'px')}
    </div>
  </section>;
}

export function useCardOpacity() {
  const [values, setValues] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(CARD_OPACITY_KEY) || '{}');
      return { ...cardOpacityDefaults, ...saved };
    }
    catch { return cardOpacityDefaults; }
  });
  useEffect(() => { localStorage.setItem(CARD_OPACITY_KEY, JSON.stringify(values)); }, [values]);
  const update = (key, value) => setValues((current) => ({ ...current, [key]: value }));
  return { values, update, reset: () => setValues(cardOpacityDefaults) };
}

const cardSettingGroups = [
  ['dashboard', 'dashboardGlass', '仪表盘界面'],
  ['chat', 'chatGlass', '对话界面'],
  ['note', 'noteGlass', '笔记界面'],
  ['code', 'codeGlass', '代码界面'],
  ['starBrief', 'starBriefGlass', '星点简介'],
  ['starSource', 'starSourceGlass', '星点原文'],
];

export function CardOpacityControls({ cardOpacity }) {
  const { values, update } = cardOpacity;
  return <section className="appearance-settings-card card-opacity-settings">
    <div className="appearance-settings-heading">
      <div><strong>卡片设置</strong><p>每个界面可分别调整透明度与磨砂玻璃强度，修改后立即生效。</p></div>
    </div>
    <div className="card-setting-grid">
      {cardSettingGroups.map(([opacityKey, glassKey, label]) => <article className="card-setting-item" key={opacityKey}>
        <strong>{label}</strong>
        <label className="appearance-slider"><span>透明度<b>{values[opacityKey]}%</b></span><input type="range" min="0" max="100" value={values[opacityKey]} onChange={(event) => update(opacityKey, Number(event.target.value))} /></label>
        <label className="appearance-slider"><span>磨砂玻璃<b>{values[glassKey]}px</b></span><input type="range" min="0" max="40" value={values[glassKey]} onChange={(event) => update(glassKey, Number(event.target.value))} /></label>
      </article>)}
    </div>
  </section>;
}
