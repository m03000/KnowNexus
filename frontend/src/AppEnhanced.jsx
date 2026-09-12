import { Children, useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import StarfieldApp from './StarfieldApp.jsx';
import LibraryWorkspacePage from './LibraryWorkspacePage.jsx';
import CodeInsightPage from './CodeInsightPage.jsx';
import ChatPage from './ChatPage.jsx';
import { AppearanceControls, CardOpacityControls, useCardOpacity, useWorkspaceAppearance, WorkspaceBackdrop } from './WorkspaceAppearance.jsx';
import './AppShell.css';
import './HarnessTheme.css';
import './DashboardRefinement.css';
import './EnhancedTheme.css';

const API_BASE = import.meta.env.VITE_API_BASE
  || window.desktopAPI?.apiBase
  || (import.meta.env.DEV ? 'http://127.0.0.1:8001' : '');

const normalizeHotspotMarkdown = (content = '') => String(content)
  .split('\n')
  .map((line) => /^(?:[一二三四五六七八九十]+、|\d+[、.]\s*)/.test(line.trim())
    ? `## ${line.trim()}`
    : line)
  .join('\n');

function Icon({ type }) {
  const paths = {
    chat: <><path d="M5 5.5h14v10H9l-4 3z"/><path d="M8 9h8M8 12h5"/></>,
    graph: <><circle cx="6" cy="7" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="m8 7 8-1M7.2 8.6l3.7 7.5M16.8 7.7l-3.7 8.4"/></>,
    memory: <><path d="M9 5a3 3 0 0 0-5 2.2A3.5 3.5 0 0 0 5 14v1a3 3 0 0 0 4 2.8M15 5a3 3 0 0 1 5 2.2 3.5 3.5 0 0 1-1 6.8v1a3 3 0 0 1-4 2.8M9 4v16M15 4v16M9 9h3M12 15h3"/></>,
    noteGraph: <><circle cx="7" cy="7" r="2"/><circle cx="17" cy="7" r="2"/><circle cx="12" cy="17" r="2"/><path d="m8.8 8.2 2.1 6.5M15.2 8.2l-2.1 6.5M9 7h6"/></>,
    projectGraph: <><path d="M4 6h6l2 2h8v10H4z"/><path d="M8 12h8M8 15h5"/></>,
    notes: <><path d="M6 3.8h9.5L19 7.3V20H6z"/><path d="M15 4v4h4M9 11h7M9 14.5h7M9 18h4"/></>,
    code: <><path d="m9 7-5 5 5 5M15 7l5 5-5 5M13 4l-2 16"/></>,
    settings: <><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L14.5 3h-5L9 6.1a8 8 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.7 1l.5 3.1h5l.5-3.1a8 8 0 0 0 1.7-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z"/></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">{paths[type]}</svg>;
}

function DesktopWindowControls() {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    if (!window.desktopAPI?.windowAction) return;
    window.desktopAPI.windowAction('state').then((state) => setMaximized(Boolean(state?.maximized))).catch(() => {});
  }, []);
  if (!window.desktopAPI?.windowAction) return null;
  const run = async (action) => {
    const state = await window.desktopAPI.windowAction(action);
    setMaximized(Boolean(state?.maximized));
  };
  return <div className="desktop-window-controls" aria-label="窗口控制">
    <button type="button" aria-label="最小化" title="最小化" onClick={() => run('minimize')}><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 6.5h9" /></svg></button>
    <button type="button" aria-label={maximized ? '还原' : '最大化'} title={maximized ? '还原' : '最大化'} onClick={() => run('maximize')}><svg viewBox="0 0 12 12" aria-hidden="true">{maximized ? <><rect x="1.5" y="3.25" width="7.25" height="7.25" rx=".25"/><path d="M3.25 3.25V1.5h7.25v7.25H8.75"/></> : <rect x="1.75" y="1.75" width="8.5" height="8.5" rx=".35" />}</svg></button>
    <button type="button" className="close" aria-label="关闭" title="关闭" onClick={() => run('close')}><svg viewBox="0 0 12 12" aria-hidden="true"><path d="m2 2 8 8M10 2 2 10" /></svg></button>
  </div>;
}

const emptyWatcher = { name: '', adapter_id: 'workbuddy', parser_type: 'workbuddy', enabled: true, session_index_path: '', conversation_root: '', memory_path: '' };

function WatcherSettings() {
  const [status, setStatus] = useState({ watchers: [] });
  const [adapters, setAdapters] = useState([]);
  const [mode, setMode] = useState('list');
  const [draft, setDraft] = useState(emptyWatcher);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [preview, setPreview] = useState([]);
  const load = useCallback(async () => {
    const [watchersResponse, adaptersResponse] = await Promise.all([
      fetch(`${API_BASE}/api/integrations/codex-watcher`),
      fetch(`${API_BASE}/api/integrations/codex-watcher/adapters`),
    ]);
    const watchers = await watchersResponse.json(); const adapterData = await adaptersResponse.json();
    setStatus(watchers); setAdapters(adapterData.adapters || []);
  }, []);
  useEffect(() => { load().catch((error) => setMessage(error.message)); }, [load]);
  const action = async (path, method = 'POST', body = null) => {
    const response = await fetch(`${API_BASE}/api/integrations/codex-watcher${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || '操作失败');
    return data;
  };
  const test = async () => {
    setBusy(true); setMessage('正在解析最近对话…'); setPreview([]);
    try {
      const result = await action('/adapters/test', 'POST', { adapter_id: draft.adapter_id, session_index_path: draft.session_index_path, conversation_root: draft.conversation_root, memory_path: draft.memory_path });
      setPreview(result.preview || []); setMessage(result.message);
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const save = async () => {
    const editing = mode === 'edit';
    setBusy(true); setMessage(editing ? '正在保存…' : '正在添加…');
    try {
      const adapterId = draft.adapter_id;
      const adapter = adapters.find((item) => item.id === adapterId);
      const payload = { name: draft.name, adapter_id: adapterId, parser_type: adapter?.parser_type || draft.parser_type || 'generic', enabled: draft.enabled, conversation_root: draft.conversation_root, session_index_path: draft.session_index_path, memory_path: draft.memory_path };
      const data = await action(editing ? `/watchers/${draft.id}` : '/watchers', editing ? 'PUT' : 'POST', payload);
      setStatus(data); setDraft(emptyWatcher); setPreview([]); setMode('list'); setMessage(editing ? '智能体配置已更新。' : '智能体已添加。');
    } catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const watcherAction = async (watcher, operation) => {
    setBusy(true); setMessage('');
    try { setStatus(await action(`/watchers/${watcher.id}${operation ? `/${operation}` : ''}`, operation ? 'POST' : 'DELETE')); }
    catch (error) { setMessage(error.message); } finally { setBusy(false); }
  };
  const selectAdapter = (id) => {
    const adapter = adapters.find((item) => item.id === id);
    setDraft((current) => ({ ...current, adapter_id: id, parser_type: adapter?.parser_type || id,
      session_index_path: adapter?.defaults?.session_index_path || '',
      conversation_root: adapter?.defaults?.conversation_root || '',
      memory_path: adapter?.defaults?.memory_path || '' }));
  };
  const selectedAdapter = adapters.find((item) => item.id === draft.adapter_id);
  const adapterFields = selectedAdapter?.fields || [];
  const allSourcesReady = adapterFields.filter((field) => field.required).every((field) => String(draft[field.key] || '').trim());
  const editWatcher = (watcher) => {
    setDraft({ ...emptyWatcher, ...watcher });
    setPreview([]); setMessage(''); setMode('edit');
  };
  return <div className="watcher-settings-content">
    <div className="watcher-settings-heading"><div><strong>外部智能体监听</strong><p>管理监听状态、文件绑定和对话适配器。</p></div><span>{status.active_count || 0}/{status.max_watchers || 3} 运行中</span></div>
    {mode === 'list' && <><div className="watcher-settings-list">{(status.watchers || []).map((watcher) => <article key={watcher.id}><header><div><i className={watcher.running ? 'running' : ''}/><strong>{watcher.name}</strong><small>{adapters.find((item) => item.id === watcher.adapter_id)?.name || watcher.adapter_id}</small></div><span>{watcher.running ? '监听中' : '已停止'}</span></header><dl><div><dt>会话正文</dt><dd>{watcher.conversation_root}</dd></div><div><dt>会话索引</dt><dd>{watcher.session_index_path || '未配置'}</dd></div><div><dt>记忆/辅助来源</dt><dd>{watcher.memory_path || '未配置'}</dd></div></dl><footer><button disabled={busy} onClick={() => editWatcher(watcher)}>编辑</button><button disabled={busy} onClick={() => watcherAction(watcher, watcher.running ? 'stop' : 'start')}>{watcher.running ? '关闭监听' : '开启监听'}</button><button className="danger" disabled={busy} onClick={() => watcherAction(watcher, '')}>删除</button></footer></article>)}</div><div className="watcher-settings-primary-actions"><button onClick={() => { setDraft(emptyWatcher); setPreview([]); setMode('add'); }}>＋ 添加智能体</button><button onClick={() => setMode('adapters')}>查看已有适配器</button></div></>}
    {mode === 'adapters' && <><div className="adapter-card-list">{adapters.map((adapter) => <article key={adapter.id}><div><strong>{adapter.name}</strong><small>{adapter.builtin ? '内置适配器' : '自定义适配器'}</small></div><p>{adapter.description}</p><code>{adapter.parser_type}</code></article>)}</div><div className="watcher-settings-primary-actions"><button onClick={() => setMode('list')}>返回监听器</button></div></>}
    {(mode === 'add' || mode === 'edit') && <div className="watcher-add-form"><header><button onClick={() => setMode('list')}>← 返回</button><strong>{mode === 'edit' ? '编辑智能体' : '添加智能体'}</strong></header><label><span>智能体名称</span><input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如 Claude Code" /></label><label><span>适配器</span><select value={draft.adapter_id} onChange={(event) => selectAdapter(event.target.value)}>{adapters.map((adapter) => <option value={adapter.id} key={adapter.id}>{adapter.name}</option>)}</select></label>{adapterFields.map((field) => <label key={field.key}><span>{field.label}</span><input value={draft[field.key] || ''} onChange={(event) => setDraft({ ...draft, [field.key]: event.target.value })} placeholder={field.placeholder} /></label>)}<p className="watcher-source-hint">填写当前适配器所需的来源；标记“可选”的路径可留空。</p><label className="watcher-enabled-check"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}/>{mode === 'edit' ? '保存后保持监听' : '添加后立即监听'}</label><div className="watcher-test-row"><button disabled={busy || !allSourcesReady} onClick={test}>测试监听</button><span>{message}</span></div>{preview.length > 0 && <div className="watcher-preview"><strong>最近识别到的对话</strong>{preview.map((turn, index) => <article key={`${turn.session_id}-${index}`}><p><b>用户：</b>{turn.user_message}</p><p><b>助手：</b>{turn.assistant_message}</p></article>)}</div>}<footer><button onClick={() => setMode('list')}>取消</button><button className="primary" disabled={busy || !draft.name || !allSourcesReady || !draft.adapter_id} onClick={save}>{mode === 'edit' ? '保存修改' : '添加智能体'}</button></footer></div>}
    {mode !== 'add' && mode !== 'edit' && message && <p className="watcher-settings-message">{message}</p>}
  </div>;
}

function Settings({ open, close, appearance, cardOpacity, theme, setTheme, initialSection = 'general', setupFocus = '', onWikiReady }) {
  const [section, setSection] = useState('general');
  const emptyProvider = { providerId: '', name: '', provider: 'openai-compatible', apiKey: '', baseUrl: 'https://api.deepseek.com/v1', model: '' };
  const [modelDraft, setModelDraft] = useState(emptyProvider);
  const [modelRuntime, setModelRuntime] = useState({ providers: [], activeProviderId: '' });
  const [editingProvider, setEditingProvider] = useState(false);
  const [modelMessage, setModelMessage] = useState('');
  const [obsidian, setObsidian] = useState({ enabled: false, vault_path: '', wiki_folder: 'AgentWiki', vault_name: '', vault_id: '', vaults: [], active_vault_id: '', connected: false, tool_count: 0, message: '' });
  const [obsidianMessage, setObsidianMessage] = useState('');
  const [vaultDraft, setVaultDraft] = useState(null);
  const [obsidianBusy, setObsidianBusy] = useState(false);
  const [retrievalModels, setRetrievalModels] = useState({ models: [], ready: false });
  const [installingModel, setInstallingModel] = useState('');
  const [retrievalMessage, setRetrievalMessage] = useState('');
  const [platformAuth, setPlatformAuth] = useState({ configured: false, cookie_count: 0, domains: [], message: '尚未导入平台 Cookie' });
  const [platformAuthBusy, setPlatformAuthBusy] = useState(false);
  const [platformAuthMessage, setPlatformAuthMessage] = useState('');
  const updateModel = (key, value) => setModelDraft((current) => ({ ...current, [key]: value }));
  useEffect(() => {
    if (!open || section !== 'models') return;
    fetch(`${API_BASE}/api/settings/models`).then((response) => response.ok ? response.json() : Promise.reject(new Error('读取模型配置失败'))).then((data) => {
      setModelDraft(emptyProvider);
      setModelRuntime({ providers: data.providers || [], activeProviderId: data.active_provider_id || '' });
    }).catch((error) => setModelMessage(error.message));
  }, [open, section]);
  useEffect(() => {
    if (open) setSection(initialSection);
  }, [open, initialSection]);
  const loadBasicConfiguration = useCallback(async () => {
    const [obsidianResponse, modelsResponse, platformAuthResponse] = await Promise.all([
      fetch(`${API_BASE}/api/settings/obsidian-wiki`),
      fetch(`${API_BASE}/api/settings/models/retrieval`),
      fetch(`${API_BASE}/api/settings/platform-auth`),
    ]);
    if (!obsidianResponse.ok || !modelsResponse.ok || !platformAuthResponse.ok) throw new Error('读取基础配置失败');
    const wiki = await obsidianResponse.json();
    const activeVault = (wiki.vaults || []).find((item) => item.id === wiki.active_vault_id);
    setObsidian({ ...wiki, vault_id: wiki.active_vault_id || '', vault_name: activeVault?.name || '' });
    setRetrievalModels(await modelsResponse.json());
    setPlatformAuth(await platformAuthResponse.json());
  }, []);
  useEffect(() => {
    if (!open || section !== 'basic') return;
    loadBasicConfiguration().catch((error) => setRetrievalMessage(error.message));
  }, [open, section]);
  useEffect(() => {
    if (!open || section !== 'basic' || !['embedding', 'reranker'].includes(installingModel)) return undefined;
    const timer = window.setInterval(() => {
      fetch(`${API_BASE}/api/settings/models/retrieval`)
        .then((response) => response.ok ? response.json() : null)
        .then((value) => { if (value) setRetrievalModels(value); })
        .catch(() => {});
    }, 650);
    return () => window.clearInterval(timer);
  }, [open, section, installingModel]);
  const saveVault = async (draft = obsidian) => {
    if (!draft.vault_name?.trim() || !draft.vault_path?.trim()) { setObsidianMessage('请填写 Vault 名称和地址'); return false; }
    setObsidianMessage('正在保存…');
    const response = await fetch(`${API_BASE}/api/settings/obsidian-wiki`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: obsidian.enabled, vault_id: draft.vault_id || '', vault_name: draft.vault_name || '', vault_path: draft.vault_path || '', wiki_folder: draft.wiki_folder || 'AgentWiki' }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { setObsidianMessage(data.detail || '保存失败'); return false; }
    const activeVault = (data.vaults || []).find((item) => item.id === data.active_vault_id);
    setObsidian({ ...data, vault_id: data.active_vault_id || '', vault_name: activeVault?.name || '' }); setVaultDraft(null); setObsidianMessage('Vault 已保存并设为当前使用位置。');
    return data;
  };
  const toggleObsidianMcp = async () => {
    if (obsidianBusy) return;
    setObsidianBusy(true);
    try {
      const activeVault = (obsidian.vaults || []).find((item) => item.id === obsidian.active_vault_id);
      if (!activeVault?.path) throw new Error('请先保存并启用一个 Vault');
      const enabled = !obsidian.connected;
      setObsidianMessage(enabled ? '正在自动下载并启动 Obsidian MCP…' : '正在停用 Obsidian MCP…');
      const savedResponse = await fetch(`${API_BASE}/api/settings/obsidian-wiki`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled, vault_id: activeVault.id, vault_name: activeVault.name, vault_path: activeVault.path, wiki_folder: activeVault.wiki_folder || 'AgentWiki' }) });
      const saved = await savedResponse.json().catch(() => ({}));
      if (!savedResponse.ok) throw new Error(saved.detail || 'MCP 配置保存失败');
      if (!enabled) { setObsidian({ ...saved, vault_id: saved.active_vault_id || '', vault_name: activeVault.name }); setObsidianMessage('Obsidian MCP 已停用'); return; }
      const response = await fetch(`${API_BASE}/api/settings/obsidian-wiki/test`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'MCP 启动失败');
      const current = (data.vaults || []).find((item) => item.id === data.active_vault_id);
      setObsidian({ ...data, vault_id: data.active_vault_id || '', vault_name: current?.name || '' }); setObsidianMessage(`MCP 已连接，发现 ${data.tool_count || 0} 个工具`); onWikiReady?.();
    } catch (error) { setObsidianMessage(error.message); }
    finally { setObsidianBusy(false); }
  };
  const testObsidianRuntime = async () => {
    if (obsidianBusy) return;
    setObsidianBusy(true); setObsidianMessage('正在下载并测试 Obsidian MCP…');
    try {
      const response = await fetch(`${API_BASE}/api/settings/obsidian-wiki/test-runtime`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'MCP 测试失败');
      setObsidianMessage(`MCP 可用，发现 ${data.tool_count || 0} 个工具`);
    } catch (error) { setObsidianMessage(error.message); }
    finally { setObsidianBusy(false); }
  };
  const pickVaultDirectory = async () => {
    if (!window.desktopAPI?.pickDirectory) { setObsidianMessage('当前环境不支持打开本地目录选择器'); return; }
    const selected = await window.desktopAPI.pickDirectory();
    if (selected) setVaultDraft((current) => ({ ...current, vault_path: selected }));
  };
  const activateVault = async (vaultId) => {
    setObsidianBusy(true); setObsidianMessage('正在切换 Vault…');
    try {
      const response = await fetch(`${API_BASE}/api/settings/obsidian-wiki/vaults/${encodeURIComponent(vaultId)}/activate`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '切换 Vault 失败');
      setObsidian({ ...data, vault_id: data.active_vault_id, vault_name: (data.vaults || []).find((item) => item.id === data.active_vault_id)?.name || '' });
      setObsidianMessage(data.connected ? `当前 Vault：${data.vault_path}，MCP 已连接` : `当前 Vault：${data.vault_path}`);
    } catch (error) { setObsidianMessage(error.message); }
    finally { setObsidianBusy(false); }
  };
  const prepareNewVault = () => setVaultDraft({ vault_id: '', vault_name: '', vault_path: '', wiki_folder: 'AgentWiki' });
  const importPlatformCookies = async () => {
    if (!window.desktopAPI?.pickCookieFile) { setPlatformAuthMessage('当前环境不支持 Cookie 文件选择'); return; }
    const selected = await window.desktopAPI.pickCookieFile();
    if (!selected?.sourcePath) return;
    setPlatformAuthBusy(true); setPlatformAuthMessage('正在校验并导入 Cookie…');
    try {
      const response = await fetch(`${API_BASE}/api/settings/platform-auth/import`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_path: selected.sourcePath }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Cookie 导入失败');
      setPlatformAuth(data); setPlatformAuthMessage('导入成功，后续平台视频会优先使用这份登录凭证。');
    } catch (error) { setPlatformAuthMessage(error.message); }
    finally { setPlatformAuthBusy(false); }
  };
  const clearPlatformCookies = async () => {
    setPlatformAuthBusy(true);
    try {
      const response = await fetch(`${API_BASE}/api/settings/platform-auth`, { method: 'DELETE' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '清除失败');
      setPlatformAuth(data); setPlatformAuthMessage('本机保存的平台 Cookie 已清除。');
    } catch (error) { setPlatformAuthMessage(error.message); }
    finally { setPlatformAuthBusy(false); }
  };
  const installRetrievalModel = async (kind) => {
    setInstallingModel(kind); setRetrievalMessage('正在下载模型，请保持网络连接…');
    try {
      const response = await fetch(`${API_BASE}/api/settings/models/retrieval/${kind}/install`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '模型安装失败');
      setRetrievalModels(data); setRetrievalMessage(data.ready ? '两个必要模型均已就绪。' : '模型安装完成，请继续安装另一个模型。');
    } catch (error) { setRetrievalMessage(error.message); }
    finally { setInstallingModel(''); }
  };
  const testRetrievalModel = async (kind) => {
    setInstallingModel(`test-${kind}`); setRetrievalMessage('正在本地加载模型并执行真实推理，首次测试可能需要一些时间…');
    try {
      const response = await fetch(`${API_BASE}/api/settings/models/retrieval/${kind}/test`, { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '模型测试失败');
      setRetrievalModels(data); setRetrievalMessage(data.test.message);
    } catch (error) { setRetrievalMessage(error.message); }
    finally { setInstallingModel(''); }
  };
  const saveModels = async () => {
    setModelMessage('正在保存…');
    const response = await fetch(`${API_BASE}/api/settings/models`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider_id: modelDraft.providerId, name: modelDraft.name, provider: modelDraft.provider, api_key: modelDraft.apiKey, base_url: modelDraft.baseUrl, model: modelDraft.model }) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) { setModelMessage(data.detail || '保存失败'); return; }
    setModelMessage('供应商已保存并设为默认模型，现在即可使用。');
    setModelRuntime({ providers: data.providers || [], activeProviderId: data.active_provider_id || '' });
    window.dispatchEvent(new Event('knownexus:model-providers-changed'));
    setModelDraft(emptyProvider); setEditingProvider(false);
  };
  const testModels = async () => {
    setModelMessage('正在连接模型服务…');
    const response = await fetch(`${API_BASE}/api/settings/models/test`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider_id: modelDraft.providerId, name: modelDraft.name, provider: modelDraft.provider, api_key: modelDraft.apiKey, base_url: modelDraft.baseUrl, model: modelDraft.model }) });
    const data = await response.json().catch(() => ({}));
    setModelMessage(response.ok ? data.message : (data.detail || '连接测试失败'));
  };
  const editProvider = (provider) => { setModelDraft({ providerId: provider.provider_id, name: provider.name, provider: provider.provider, apiKey: '', baseUrl: provider.base_url, model: provider.model }); setEditingProvider(true); setModelMessage(''); };
  if (!open) return null;
  const sections = [['general', '⚙', '通用设置'], ['basic', '◇', '基础配置'], ['models', '◉', '对话模型'], ['watchers', '⌁', '智能体监听']];
  return <div className="harness-modal-backdrop" onMouseDown={close}><section className="harness-settings" onMouseDown={(event) => event.stopPropagation()}>
    <div className="harness-settings-body"><nav><h2>设置</h2>{sections.map(([id, icon, label]) => <button type="button" className={section === id ? 'active' : ''} onClick={() => setSection(id)} key={id}><i>{icon}</i>{label}</button>)}</nav><main>
      <header className="settings-content-header"><span>{sections.find(([id]) => id === section)?.[2]}</span><button type="button" onClick={close}>×</button></header>
      {section === 'general' && <div className="settings-general-content">
        <section className="ui-theme-settings" aria-labelledby="ui-theme-title"><div><strong id="ui-theme-title">界面背景</strong><p>切换无壁纸时的工作区颜色，不影响图谱、壁纸和现有卡片配置。</p></div><div className="ui-theme-options" role="group" aria-label="界面背景"><button type="button" className={theme === 'light' ? 'active' : ''} aria-pressed={theme === 'light'} onClick={() => setTheme('light')}><i className="theme-preview light"/><span>浅色</span></button><button type="button" className={theme === 'dark' ? 'active' : ''} aria-pressed={theme === 'dark'} onClick={() => setTheme('dark')}><i className="theme-preview dark"/><span>深色</span></button></div></section>
        <AppearanceControls appearance={appearance}/>
        <CardOpacityControls cardOpacity={cardOpacity}/>
      </div>}
      {section === 'models' && <div className="model-settings-content">
        <div className="model-settings-intro"><div><strong>模型</strong><p>配置 OpenAI 兼容供应商的 API 密钥、接口地址和模型名称。</p></div></div>
        {!editingProvider && <div className="provider-list">{modelRuntime.providers.map((provider) => <article key={provider.provider_id} className={provider.provider_id === modelRuntime.activeProviderId ? 'active' : ''}><div><strong>{provider.name}</strong><small>{provider.model}</small></div><span>{provider.provider_id === modelRuntime.activeProviderId ? '当前默认' : provider.api_key_configured ? '已配置' : '待配置'}</span><button type="button" onClick={() => editProvider(provider)}>编辑</button></article>)}<button type="button" className="add-provider" onClick={() => { setModelDraft(emptyProvider); setEditingProvider(true); }}>＋ 添加供应商</button></div>}
        {editingProvider && <div className="model-settings-form provider-editor"><div className="model-settings-pair"><label><span>显示名称</span><input value={modelDraft.name} onChange={(event) => updateModel('name', event.target.value)} placeholder="例如 DeepSeek" /></label><label><span>供应商类型</span><select value={modelDraft.provider} onChange={(event) => updateModel('provider', event.target.value)}><option value="openai-compatible">OpenAI 兼容</option><option value="deepseek">DeepSeek</option><option value="openai">OpenAI</option><option value="siliconflow">硅基流动</option><option value="custom">自定义</option></select></label></div><label><span>API Key</span><input type="password" value={modelDraft.apiKey} onChange={(event) => updateModel('apiKey', event.target.value)} placeholder={modelDraft.providerId ? '已配置；留空保持原密钥' : '输入 API Key'} autoComplete="off" /></label><label><span>Base URL</span><input value={modelDraft.baseUrl} onChange={(event) => updateModel('baseUrl', event.target.value)} placeholder="https://api.example.com/v1" /></label><label><span>模型名称</span><input value={modelDraft.model} onChange={(event) => updateModel('model', event.target.value)} placeholder="例如 deepseek-chat" /></label><div className="model-settings-actions"><span>{modelMessage}</span><div><button type="button" className="secondary" onClick={() => { setEditingProvider(false); setModelMessage(''); }}>取消</button><button type="button" className="secondary" onClick={testModels}>测试连接</button><button type="button" onClick={saveModels}>保存并设为默认</button></div></div></div>}
        {!editingProvider && <p className="model-settings-notice">API Key 仅保存在本机配置文件中，不写入浏览器存储。Embedding 与 Reranker 继续使用应用内置模型。</p>}
      </div>}
      {section === 'basic' && <div className="model-settings-content basic-configuration"><div className="model-settings-intro"><div><strong>基础配置</strong><p>{setupFocus === 'models' ? '首次使用需先安装两个必要的本地检索模型。' : setupFocus === 'wiki' ? '加入笔记界面前，请创建 Wiki 并加载 Obsidian MCP。' : '管理本地检索模型与 Obsidian Wiki。'}</p></div><span>{retrievalModels.ready ? '模型已就绪' : '需要安装模型'}</span></div>
<section className={`basic-setup-card ${setupFocus === 'models' ? 'required' : ''}`}><header><div><b>1</b><div><strong>本地检索模型</strong><p>当前版本固定使用以下两个模型，暂不启用降级策略。</p></div></div><span>{retrievalModels.ready ? '已完成' : '首次使用必需'}</span></header><div className="local-model-cards">{(retrievalModels.models || []).map((model) => { const isDownloading = installingModel === model.kind || model.downloading; const progress = Math.max(0, Math.min(100, Number(model.download_progress || 0) * 100)); return <article key={model.kind}><div className="local-model-copy"><strong>{model.kind === 'embedding' ? 'Embedding' : 'Reranker'}</strong><p>{model.model_id}</p><small style={{ display: 'block', overflowWrap: 'anywhere' }}>存储位置：{model.cache_directory}</small><small>{model.installed ? `已安装${model.size_bytes ? ` · ${(model.size_bytes / 1024 / 1024).toFixed(0)} MB` : ''}` : isDownloading ? '正在下载模型文件' : '尚未安装'}</small>{isDownloading && <div className="local-model-progress" role="progressbar" aria-label={`${model.model_id} 下载进度`} aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress)}><span style={{ width: `${progress}%` }}/></div>}</div><div className="local-model-actions"><button type="button" className="secondary" disabled={Boolean(installingModel)} onClick={() => testRetrievalModel(model.kind)}>{installingModel === `test-${model.kind}` ? '测试中…' : '测试模型'}</button><button type="button" disabled={model.installed || Boolean(installingModel)} onClick={() => installRetrievalModel(model.kind)}>{isDownloading ? '下载中…' : model.installed ? '已下载' : '下载并安装'}</button></div></article>; })}</div>{retrievalMessage && <p className="basic-setup-message">{retrievalMessage}</p>}</section>
        <section className="basic-setup-card platform-auth-card"><header><div><b>2</b><div><strong>平台视频凭证</strong><p>导入浏览器导出的 cookies.txt，用于读取需要登录的抖音、B站等平台内容。</p></div></div><span>{platformAuth.configured ? '凭证可用' : '按需配置'}</span></header><div className="platform-auth-row"><div><strong>{platformAuth.configured ? '已保存登录凭证' : '尚未导入 Cookie 文件'}</strong><p>{platformAuth.message}</p>{platformAuth.configured && <small>{(platformAuth.domains || []).length ? `包含域名：${platformAuth.domains.join('、')}` : '已通过 Netscape 格式校验'}</small>}</div><div className="platform-auth-actions">{platformAuth.configured && <button type="button" className="secondary" disabled={platformAuthBusy} onClick={clearPlatformCookies}>清除</button>}<button type="button" disabled={platformAuthBusy} onClick={importPlatformCookies}>{platformAuthBusy ? '处理中…' : platformAuth.configured ? '刷新 Cookie' : '导入 Cookie'}</button></div></div>{platformAuthMessage && <p className="basic-setup-message">{platformAuthMessage}</p>}<p className="platform-auth-warning">凭证仅保存在本机 data/platform_auth，不会进入源码或发布压缩包。Cookie 失效后重新导出并点击“刷新 Cookie”即可。</p></section>
        <section className={`basic-setup-card obsidian-setup-card ${setupFocus === 'wiki' ? 'required' : ''}`}>
          <header><div><b>3</b><div><strong>Obsidian Wiki / MCP</strong><p>可创建并保存多个 Vault，启动前在这里选择当前使用地址。</p></div></div><span>{obsidian.connected ? `已验证 · ${obsidian.tool_count || 0} 工具` : '按需配置'}</span></header>
          <div className="vault-command-bar">
            <strong>Obsidian MCP</strong>
            <span className={obsidian.connected ? 'connected' : ''}><i/>{obsidian.connected ? '已连接' : '未连接'}</span>
            <small>当前：{obsidian.vault_name || '尚未选择'}</small>
            <button type="button" className="secondary vault-test-button" onClick={testObsidianRuntime} disabled={obsidianBusy}>测试</button>
            <button type="button" className="secondary" onClick={toggleObsidianMcp} disabled={obsidianBusy}>{obsidianBusy ? '处理中…' : obsidian.connected ? '停用' : '启用'}</button>
          </div>
          <div className="vault-card-list">
            <article className="vault-info-card builtin"><header><div><strong>{obsidian.builtin_wiki?.name || '内置 Wiki'}</strong><small>应用内置</small></div><span>默认可用</span></header><dl><div><dt>名称</dt><dd>{obsidian.builtin_wiki?.name || '内置 Wiki'}</dd></div><div><dt>目录</dt><dd>{obsidian.builtin_wiki?.directory || 'LLM Wiki'}</dd></div><div><dt>地址</dt><dd>{obsidian.builtin_wiki?.path || '本机运行数据 / wiki'}</dd></div></dl></article>
            {(obsidian.vaults || []).map((vault) => <article className={`vault-info-card ${vault.id === obsidian.active_vault_id ? 'active' : ''}`} key={vault.id}><header><div><strong>{vault.name}</strong><small>{vault.verified ? '已验证' : '尚未验证'}</small></div><button type="button" className="secondary" disabled={vault.id === obsidian.active_vault_id} onClick={() => activateVault(vault.id)}>{vault.id === obsidian.active_vault_id ? '已启用' : '启用'}</button></header><dl><div><dt>名称</dt><dd>{vault.name}</dd></div><div><dt>目录</dt><dd>{vault.wiki_folder || 'AgentWiki'}</dd></div><div><dt>地址</dt><dd>{vault.path}</dd></div></dl></article>)}
            {vaultDraft && <article className="vault-info-card vault-draft-card"><header><div><strong>新 Vault</strong><small>填写后保存</small></div></header><div className="vault-draft-fields"><label><span>名称</span><input value={vaultDraft.vault_name} onChange={(event) => setVaultDraft({ ...vaultDraft, vault_name: event.target.value })} placeholder="例如 工作知识库" /></label><label><span>目录</span><input value={vaultDraft.wiki_folder} onChange={(event) => setVaultDraft({ ...vaultDraft, wiki_folder: event.target.value })} placeholder="AgentWiki" /></label><label className="vault-path-field"><span>地址</span><div><input value={vaultDraft.vault_path} onChange={(event) => setVaultDraft({ ...vaultDraft, vault_path: event.target.value })} placeholder="例如 D:\\Notes\\MyWiki" /><button type="button" className="secondary" onClick={pickVaultDirectory}>选择本地文件夹</button></div></label></div><footer><button type="button" className="vault-cancel-button" onClick={() => setVaultDraft(null)}>取消</button><button type="button" className="vault-save-button" onClick={() => saveVault(vaultDraft)}>保存 Vault</button></footer></article>}
          </div>
          <div className="vault-action-footer"><button type="button" onClick={prepareNewVault} disabled={Boolean(vaultDraft)}>＋ 创建另一个 Vault</button><span>{obsidianMessage || obsidian.message || (obsidian.connected ? 'MCP 已连接' : '点击启用将自动下载并加载 Obsidian MCP')}</span></div>
        </section>
      </div>}
      {section === 'watchers' && <WatcherSettings/>}
    </main></div>
  </section></div>;
}

function Dashboard({ apiBase }) {
  const [open, setOpen] = useState(false);
  const [stats, setStats] = useState({ ai_notes: {}, personal_documents: {}, projects: {} });
  const [loading, setLoading] = useState(false);
  const [panelSize, setPanelSize] = useState(() => { try { return JSON.parse(localStorage.getItem('personal-agent:chat-panel-size-v2')) || { width: 1400, height: 760 }; } catch { return { width: 1400, height: 760 }; } });
  const [position, setPosition] = useState(() => { try { return JSON.parse(localStorage.getItem('personal-agent:dashboard-position')) || { x: 0, y: 0 }; } catch { return { x: 0, y: 0 }; } });
  const drag = useRef(null);
  const panelResize = useRef(null);
  useEffect(() => {
    const resize = (event) => {
      if (!panelResize.current) return;
      const { startX, startY, initial, direction } = panelResize.current;
      const dx = event.clientX - startX; const dy = event.clientY - startY;
      setPanelSize({
        width: Math.max(620, Math.min(window.innerWidth - 50, initial.width + (direction.includes('w') ? -dx : direction.includes('e') ? dx : 0))),
        height: Math.max(440, Math.min(window.innerHeight - 50, initial.height + (direction.includes('n') ? -dy : direction.includes('s') ? dy : 0))),
      });
    };
    const finish = () => { if (!panelResize.current) return; panelResize.current = null; document.body.classList.remove('dashboard-resizing'); };
    window.addEventListener('pointermove', resize); window.addEventListener('pointerup', finish); window.addEventListener('pointercancel', finish);
    return () => { window.removeEventListener('pointermove', resize); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', finish); };
  }, []);
  useEffect(() => { localStorage.setItem('personal-agent:chat-panel-size-v2', JSON.stringify(panelSize)); }, [panelSize]);
  const load = async () => {
    setLoading(true);
    try {
      const [notesResponse, projectsResponse] = await Promise.all([fetch(`${apiBase}/api/library/notes/dashboard`), fetch(`${apiBase}/api/library/code-projects`)]);
      const notes = notesResponse.ok ? await notesResponse.json() : {};
      const projectData = projectsResponse.ok ? await projectsResponse.json() : {};
      const projects = projectData.projects || [];
      setStats({ ...notes, projects: { count: projects.length, files: projects.reduce((sum, item) => sum + Number(item.total_files || 0), 0), blocks: projects.reduce((sum, item) => sum + Number(item.total_blocks || 0), 0) } });
    } finally { setLoading(false); }
  };
  const down = (event) => { event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, position, moved: false }; };
  const move = (event) => {
    if (!drag.current) return;
    const dx = event.clientX - drag.current.x; const dy = event.clientY - drag.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 5) drag.current.moved = true;
    const nextY = Math.min(window.innerHeight - 56, Math.max(0, drag.current.position.y + dy));
    const rightLimit = nextY < 40 ? 0 : 146;
    setPosition({ x: Math.min(rightLimit, Math.max(-window.innerWidth + 110, drag.current.position.x + dx)), y: nextY });
  };
  const up = () => {
    if (!drag.current) return;
    const moved = drag.current.moved; drag.current = null;
    localStorage.setItem('personal-agent:dashboard-position', JSON.stringify(position));
    if (!moved) { const next = !open; setOpen(next); if (next) load(); }
  };
  const startPanelResize = (direction, event) => { event.preventDefault(); event.stopPropagation(); panelResize.current = { direction, startX: event.clientX, startY: event.clientY, initial: panelSize }; document.body.classList.add('dashboard-resizing'); };
  return <div className={`global-dashboard ${open ? 'open' : ''}`} style={{ transform: `translate(${position.x}px, ${position.y}px)` }}>
    <button className="global-dashboard-orb" type="button" onPointerDown={down} onPointerMove={move} onPointerUp={up} title="拖动调整位置，单击打开对话">{open ? '×' : <><span/><i/><b/></>}</button>
    <aside className={`global-dashboard-panel floating-chat-workbench ${open ? '' : 'chat-panel-hidden'}`} style={{ width: `${panelSize.width}px`, height: `${panelSize.height}px` }}><ChatPage apiBase={apiBase} floating />{['n','e','s','w','ne','nw','se','sw'].map((direction) => <span key={direction} className={`chat-panel-resize-edge ${direction}`} onPointerDown={(event) => startPanelResize(direction, event)}/>)}</aside>
  </div>;
}

function FreeDashboardComponent({ id, className = '', children }) {
  const key = `personal-agent:dashboard-component:${id}`;
  const [offset, setOffset] = useState(() => { try { return JSON.parse(localStorage.getItem(key)) || { x: 0, y: 0 }; } catch { return { x: 0, y: 0 }; } });
  const drag = useRef(null);
  useEffect(() => {
    const move = (event) => { if (!drag.current) return; setOffset({ x: drag.current.x + event.clientX - drag.current.startX, y: drag.current.y + event.clientY - drag.current.startY }); };
    const finish = () => { if (!drag.current) return; drag.current = null; document.body.classList.remove('dashboard-dragging'); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', finish); window.addEventListener('pointercancel', finish);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', finish); };
  }, []);
  useEffect(() => { localStorage.setItem(key, JSON.stringify(offset)); }, [key, offset]);
  const start = (event) => { event.preventDefault(); event.stopPropagation(); drag.current = { startX: event.clientX, startY: event.clientY, x: offset.x, y: offset.y }; document.body.classList.add('dashboard-dragging'); };
  return <div className={`free-dashboard-component ${className}`} style={{ transform: `translate(${offset.x}px, ${offset.y}px)` }}><button type="button" className="free-component-handle" onPointerDown={start} aria-label="移动组件">•••</button>{children}</div>;
}

const DASHBOARD_LAYOUTS = {
  memory: [{ x: 0, y: 0, w: 39, h: 100 }, { x: 40.5, y: 0, w: 59.5, h: 100 }],
  notes: [{ x: 0, y: 0, w: 42, h: 100 }, { x: 43.5, y: 0, w: 56.5, h: 100 }],
  code: [{ x: 0, y: 0, w: 42, h: 100 }, { x: 43.5, y: 0, w: 56.5, h: 100 }],
};

function EditableDashboardCanvas({ mode, children }) {
  const storageKey = `personal-agent:dashboard-layout:${mode}`;
  const canvasRef = useRef(null);
  const dragRef = useRef(null);
  const defaults = DASHBOARD_LAYOUTS[mode] || DASHBOARD_LAYOUTS.memory;
  const [layout, setLayout] = useState(() => {
    try { return JSON.parse(localStorage.getItem(storageKey) || 'null') || defaults; }
    catch { return defaults; }
  });
  const [customCards, setCustomCards] = useState(() => {
    try { return JSON.parse(localStorage.getItem(`${storageKey}:custom`) || '[]'); }
    catch { return []; }
  });
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      setLayout(saved || defaults);
      setCustomCards(JSON.parse(localStorage.getItem(`${storageKey}:custom`) || '[]'));
    } catch { setLayout(defaults); setCustomCards([]); }
  }, [storageKey]);
  useEffect(() => {
    const move = (event) => {
      const drag = dragRef.current; if (!drag) return;
      const dx = (event.clientX - drag.startX) / drag.rect.width * 100;
      const dy = (event.clientY - drag.startY) / drag.rect.height * 100;
      setLayout((current) => {
        const next = current.map((item, index) => index === drag.index ? { ...item, x: drag.initial.x + dx, y: drag.initial.y + dy } : item);
        localStorage.setItem(storageKey, JSON.stringify(next)); return next;
      });
    };
    const finish = () => { dragRef.current = null; document.body.classList.remove('dashboard-dragging'); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', finish); window.removeEventListener('pointercancel', finish); };
  }, [storageKey]);
  const persist = (next) => { setLayout(next); localStorage.setItem(storageKey, JSON.stringify(next)); };
  const startDrag = (index, event) => {
    if (!canvasRef.current) return;
    event.preventDefault(); event.stopPropagation();
    dragRef.current = { index, startX: event.clientX, startY: event.clientY, initial: layout[index], rect: canvasRef.current.getBoundingClientRect() };
    document.body.classList.add('dashboard-dragging');
  };
  const saveSize = (index, event) => {
    if (!canvasRef.current) return;
    const canvas = canvasRef.current.getBoundingClientRect(); const card = event.currentTarget.getBoundingClientRect();
    const next = layout.map((item, itemIndex) => itemIndex === index ? { ...item, w: Math.max(8, card.width / canvas.width * 100), h: Math.max(10, card.height / canvas.height * 100) } : item);
    persist(next);
  };
  const addCard = () => {
    const id = `custom-${Date.now()}`; const nextCards = [...customCards, { id, title: '自定义卡片' }];
    const nextLayout = [...layout, { x: 30, y: 24, w: 28, h: 30 }];
    setCustomCards(nextCards); localStorage.setItem(`${storageKey}:custom`, JSON.stringify(nextCards)); persist(nextLayout);
  };
  const removeCard = (customIndex) => {
    const fixedCount = Children.count(children); const layoutIndex = fixedCount + customIndex;
    const nextCards = customCards.filter((_, index) => index !== customIndex);
    setCustomCards(nextCards); localStorage.setItem(`${storageKey}:custom`, JSON.stringify(nextCards)); persist(layout.filter((_, index) => index !== layoutIndex));
  };
  const cards = [...Children.toArray(children), ...customCards.map((card, index) => <section className="dashboard-custom-card" key={card.id}><input value={card.title} onChange={(event) => { const next = customCards.map((item, itemIndex) => itemIndex === index ? { ...item, title: event.target.value } : item); setCustomCards(next); localStorage.setItem(`${storageKey}:custom`, JSON.stringify(next)); }}/><p>拖动顶部把手移动；拖动右下角调整大小。</p><button type="button" onClick={() => removeCard(index)}>删除卡片</button></section>)];
  const displayLayout = cards.map((_, index) => layout[index] || { x: 28, y: 22, w: 30, h: 32 });
  return <div className="editable-dashboard-canvas dashboard-slide" ref={canvasRef}>
    {cards.map((child, index) => <div className="editable-dashboard-widget" key={child.key || index} style={{ left: `${displayLayout[index].x}%`, top: `${displayLayout[index].y}%`, width: `${displayLayout[index].w}%`, height: `${displayLayout[index].h}%` }} onPointerUp={(event) => saveSize(index, event)}>
      <button type="button" className="dashboard-drag-handle" aria-label="拖动卡片" onPointerDown={(event) => startDrag(index, event)}><span/><span/><span/></button>
      <div className="editable-dashboard-widget-content">{child}</div>
    </div>)}
    <button type="button" className="dashboard-add-card" onClick={addCard}>＋ 增加卡片</button>
  </div>;
}

function HomeDashboard({ apiBase }) {
  const [data, setData] = useState({ watchers: [], historyWatchers: [], notes: {}, wiki: {}, wikiStats: {}, maintenance: {}, conflicts: [], workspace: { topics: [], slots: [] } });
  const [dashboardMode, setDashboardMode] = useState('memory');
  const [detailOpen, setDetailOpen] = useState(false);
  const [summaryHeight, setSummaryHeight] = useState(340);
  const [openHotspot, setOpenHotspot] = useState(null);
  const [addingTopic, setAddingTopic] = useState(false);
  const [topicDraft, setTopicDraft] = useState('');
  const [openTopicSlot, setOpenTopicSlot] = useState(null);
  useEffect(() => {
    let live = true;
    const load = async () => {
      const start = new Date(); start.setHours(0, 0, 0, 0);
      const end = new Date(start); end.setDate(end.getDate() + 1);
      const responses = await Promise.all([
        fetch(`${apiBase}/api/integrations/codex-watcher/statistics?start_at=${encodeURIComponent(start.toISOString())}&end_at=${encodeURIComponent(end.toISOString())}`),
        fetch(`${apiBase}/api/library/notes/dashboard`),
        fetch(`${apiBase}/api/settings/obsidian-wiki`),
        fetch(`${apiBase}/api/library/wiki/stats`),
        fetch(`${apiBase}/api/memory-maintenance/dashboard`),
        fetch(`${apiBase}/api/memory-maintenance/conflicts`),
        fetch(`${apiBase}/api/memory-maintenance/wiki-workspace`),
        fetch(`${apiBase}/api/integrations/codex-watcher/statistics`),
        fetch(`${apiBase}/api/integrations/codex-watcher`),
      ]);
      const values = await Promise.all(responses.map((response) => response.ok ? response.json() : {}));
      const enabledWatcherIds = new Set((values[8].watchers || []).filter((watcher) => watcher.enabled).map((watcher) => watcher.id));
      if (live) setData({ watchers: (values[0].watchers || []).filter((watcher) => enabledWatcherIds.has(watcher.id)), historyWatchers: (values[7].watchers || []).filter((watcher) => enabledWatcherIds.has(watcher.id)), notes: values[1], wiki: values[2], wikiStats: values[3], maintenance: values[4], conflicts: values[5].conflicts || [], workspace: values[6] || { topics: [], slots: [] } });
    };
    load().catch(() => {}); const timer = window.setInterval(() => load().catch(() => {}), 5000);
    return () => { live = false; window.clearInterval(timer); };
  }, [apiBase]);
  // Only render sources returned by the backend. A clean portable build must not
  // manufacture placeholder agents or make an empty installation look populated.
  const realAgents = data.historyWatchers.filter((agent) => agent.enabled !== false).slice(0, 3);
  const internalAgent = data.maintenance.internal_agent || { id: 'internal-conversation', name: '内部对话', adapter_id: 'personal_agent', running: true };
  const agents = [
    ...realAgents,
    ...Array.from({ length: Math.max(0, 3 - realAgents.length) }, (_, index) => ({
      id: `reserved-agent-${index}`,
      name: '待接入智能体',
      adapter_id: 'reserved',
      running: false,
    })),
    internalAgent,
  ];
  const listeningTime = (seconds = 0) => {
    const total = Math.max(0, Number(seconds) || 0);
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
  };
  const agentMetrics = (agent) => [
    ['会话', agent.conversation_count || 0],
    ['轮次', agent.captured_turns || 0],
    ['关系', agent.relations || 0],
    ['记忆点', agent.memory_points || 0],
    ['蒸馏 Token', Number(agent.distillation_tokens || 0).toLocaleString('zh-CN')],
    ...(agent.adapter_id === 'personal_agent' ? [] : [['监听时间', listeningTime(agent.active_seconds)]]),
  ];
  const overview = data.wikiStats || {};
  const library = data.notes || {};
  const wikiName = data.wiki?.vault_name || (data.wiki?.connected ? 'Obsidian Wiki' : '内置 Wiki');
  const vaultPath = data.wiki?.vault_path || '';
  const wikiStats = [
    ['主题', overview.topics || 0],
    ['概念', overview.concepts || 0],
    ['Wiki 文档', overview.documents || 0],
    ['个人文档', library.personal_documents?.count || 0],
    ['AI 笔记', library.ai_notes?.count || 0],
    ['导入笔记', library.personal_documents?.imported || 0],
  ];
  const realSourceSlots = data.watchers.filter((agent) => agent.enabled !== false).slice(0, 3);
  const internalToday = data.maintenance.internal_agent_today || { id: 'internal-conversation-today', name: '内部对话', adapter_id: 'personal_agent', running: true };
  const sourceSlots = [
    ...realSourceSlots,
    ...Array.from({ length: Math.max(0, 3 - realSourceSlots.length) }, (_, index) => ({
      id: `memory-source-${index}`,
      name: '待接入智能体',
      running: false,
    })),
    internalToday,
  ];
  const totalMemoryPoints = Number(data.maintenance.memory_points || 0);
  const totalRelations = Number(data.maintenance.relations || 0);
  const totalTokens = data.watchers.reduce((sum, agent) => sum + Number(agent.distillation_tokens || 0), 0) + Number(internalToday.distillation_tokens || 0);
  const totalTurns = data.watchers.reduce((sum, agent) => sum + Number(agent.captured_turns || 0), 0) + Number(internalToday.captured_turns || 0);
  const dailySummaries = data.maintenance.summary?.items || [];
  const summaryColumns = [[], []];
  const summaryColumnWeights = [0, 0];
  dailySummaries.forEach((item, index) => {
    const column = summaryColumnWeights[0] <= summaryColumnWeights[1] ? 0 : 1;
    summaryColumns[column].push({ ...item, displayIndex: index + 1 });
    summaryColumnWeights[column] += Math.max(140, String(item.content || '').length);
  });
  const resolveConflict = async (relationId, side) => {
    const response = await fetch(`${apiBase}/api/memory-maintenance/conflicts/${encodeURIComponent(relationId)}/keep/${side}`, { method: 'POST' });
    if (response.ok) setData((current) => ({ ...current, conflicts: current.conflicts.filter((item) => item.relation_id !== relationId), maintenance: { ...current.maintenance, conflicts: Math.max(0, Number(current.maintenance.conflicts || 0) - 1) } }));
  };
  const startSummaryResize = (event) => {
    event.preventDefault();
    const startY = event.clientY; const startHeight = summaryHeight;
    const containerHeight = event.currentTarget.closest('.memory-detail-overlay')?.clientHeight || 760;
    const move = (moveEvent) => setSummaryHeight(Math.max(260, Math.min(containerHeight - 230, startHeight + startY - moveEvent.clientY)));
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); };
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', stop);
  };
  const updateWorkspace = (workspace) => setData((current) => ({ ...current, workspace }));
  const addTopic = async () => {
    const name = topicDraft.trim();
    if (!name) return;
    const response = await fetch(`${apiBase}/api/memory-maintenance/topics`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.slice(0, 30) }) });
    if (response.ok) { updateWorkspace(await response.json()); setTopicDraft(''); setAddingTopic(false); }
  };
  const selectTopic = async (slotId, value) => {
    const response = await fetch(`${apiBase}/api/memory-maintenance/hotspot-slots/${slotId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic_id: value ? Number(value) : null }) });
    if (response.ok) updateWorkspace(await response.json());
  };
  const readHotspot = async (slot) => {
    if (!slot.hotspot_id) return;
    setOpenHotspot({ ...slot, is_read: 1 });
    if (!slot.is_read) await fetch(`${apiBase}/api/memory-maintenance/hotspots/${slot.hotspot_id}/read`, { method: 'POST' });
    setData((current) => ({ ...current, workspace: { ...current.workspace, slots: current.workspace.slots.map((item) => item.slot_id === slot.slot_id ? { ...item, is_read: 1 } : item) } }));
  };
  const addHotspotToWiki = async (event, hotspotId) => {
    event.stopPropagation();
    if (!hotspotId) return;
    const response = await fetch(`${apiBase}/api/memory-maintenance/hotspots/${hotspotId}/add-to-wiki`, { method: 'POST' });
    if (response.ok) setData((current) => ({ ...current, workspace: { ...current.workspace, slots: current.workspace.slots.map((item) => item.hotspot_id === hotspotId ? { ...item, added_to_wiki: 1 } : item) } }));
  };
  const showMemory = () => { setDashboardMode('memory'); setDetailOpen(false); };
  const showWiki = () => { setDashboardMode('wiki'); setDetailOpen(false); };
  return <section className="home-dashboard home-dashboard-v2">
    <header className="dashboard-switch-header" aria-label="仪表盘内容切换">
      <button type="button" className={dashboardMode === 'memory' ? 'active' : ''} onClick={showMemory}>记忆</button>
      <button type="button" className={dashboardMode === 'wiki' ? 'active' : ''} onClick={showWiki}>WIKI</button>
    </header>
    <div className="home-dashboard-stage"><div className={`fixed-memory-dashboard dashboard-slide dashboard-mode-${dashboardMode}`}>
      {dashboardMode === 'memory' ? <>
        <section className="memory-overview-panel memory-home-panel">
          <header className="memory-panel-heading"><div><h2>今日记录数据</h2></div></header>
          <div className="memory-source-grid">{sourceSlots.map((agent) => <article className="memory-source-card" key={agent.id}><div><i className={agent.running ? 'running' : ''}/><span>{agent.name}</span></div><strong>{Number(agent.captured_turns || 0).toLocaleString('zh-CN')}</strong><small>监听对话</small></article>)}</div>
          <div className="memory-derived-grid">
            {[['捕获轮次', totalTurns], ['记忆点', totalMemoryPoints], ['关系', totalRelations], ['蒸馏 Token', totalTokens]].map(([label, value]) => <div key={label}><span>{label}</span><strong>{Number(value).toLocaleString('zh-CN')}</strong></div>)}
          </div>
          <div className="memory-summary-heading"><span/><strong>今日信息总结</strong><span/></div>
          <div className="memory-bottom-grid">
            <button type="button" onClick={() => setDetailOpen((value) => !value)}><header><strong>今日总结</strong><span>{dailySummaries.length}</span></header><div className="memory-summary-preview">{dailySummaries.map((item) => <p key={item.title}>{item.title}</p>)}</div></button>
            <button type="button" onClick={() => setDetailOpen((value) => !value)}><header><strong>待处理冲突</strong><span>{data.conflicts.length}</span></header><p>{data.conflicts.length ? `${data.conflicts.length} 组冲突记忆等待处理` : '当前没有需要处理的冲突记忆'}</p></button>
          </div>
        </section>
        {detailOpen ? <section className="memory-detail-overlay" style={{ '--summary-height': `${summaryHeight}px` }}>
          <div className="memory-detail-title"><div><h2>记忆整理</h2></div></div>
          <div className="memory-conflict-section"><header><strong>处理冲突记忆</strong><span>{data.conflicts.length} 组</span></header>{data.conflicts.length ? <div className="memory-conflict-list">{data.conflicts.map((item) => <article key={item.relation_id}><div><section><strong>记忆 A</strong><p>{item.source_content}</p><button type="button" onClick={() => resolveConflict(item.relation_id, 'source')}>采纳 A</button></section><section><strong>记忆 B</strong><p>{item.target_content}</p><button type="button" onClick={() => resolveConflict(item.relation_id, 'target')}>采纳 B</button></section></div></article>)}</div> : <div className="memory-empty-conflict"><p>暂无待处理冲突。</p></div>}</div>
          <div className="memory-summary-section"><button type="button" className="summary-resize-handle" aria-label="拖动调整今日总结高度" onPointerDown={startSummaryResize}/><header><strong>今日总结</strong><span>{dailySummaries.length} 条</span></header><div className="memory-summary-columns">{summaryColumns.map((column, columnIndex) => <div className="memory-summary-column" key={columnIndex}>{column.map((item) => <article key={item.title}><span>{String(item.displayIndex).padStart(2, '0')}</span><div><strong>{item.title}</strong><p>{item.content}</p></div></article>)}</div>)}</div></div>
        </section> : <section className="memory-agents-panel"><header><strong>智能体信息</strong><span>{realAgents.length + 1} 个来源</span></header><div className="memory-agent-grid">{agents.map((agent) => <article className="memory-agent-card" key={agent.id}><header><i className={agent.running ? 'running' : ''}/><strong>{agent.name}</strong></header><dl>{agentMetrics(agent).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></article>)}</div></section>}
      </> : <>
        <section className="memory-overview-panel wiki-overview-panel">
          <div className="wiki-head"><div className="wiki-heading-block"><span>当前 Vault · LLM Wiki</span><h3 title={wikiName}>LLM {wikiName}</h3></div>
          <div className="wiki-address-block" title={vaultPath}>{vaultPath || '本地内置 Wiki 存储'}</div></div>
          <div className="wiki-stat-card"><div className="memory-stat-grid wiki-stat-grid">{wikiStats.map(([label, value]) => <article key={label}><strong>{Number(value).toLocaleString('zh-CN')}</strong><span>{label}</span></article>)}</div></div>
          <div className="wiki-token-row"><dl className="memory-config-list wiki-token-list"><div><dt>构建消耗 Token</dt><dd>{Number(overview.build_tokens || 0).toLocaleString('zh-CN')}</dd></div></dl></div>
        </section><section className="memory-agents-panel wiki-workspace-panel">
          <header className="wiki-workspace-heading"><strong>今日工作信息</strong></header>
          <div className="wiki-workspace-grid">
            <article className="wiki-workspace-overview"><header><strong>今日概览</strong></header><dl><div><dt>今日新增笔记</dt><dd>{data.workspace.today_notes || 0}</dd></div><div><dt>今日 Wiki 入库</dt><dd>{data.workspace.today_wiki || 0}</dd></div><div><dt>最新热点</dt><dd>{data.workspace.today_hotspots || 0}</dd></div></dl><div className="wiki-topic-row"><strong>兴趣主题</strong><div>{(data.workspace.topics || []).map((topic) => <span key={topic.topic_id}>{topic.name}</span>)}{addingTopic ? <form onSubmit={(event) => { event.preventDefault(); addTopic(); }}><input autoFocus value={topicDraft} maxLength={30} placeholder="输入主题" onChange={(event) => setTopicDraft(event.target.value)}/><button type="submit" disabled={!topicDraft.trim()}>保存</button><button type="button" onClick={() => { setAddingTopic(false); setTopicDraft(''); }}>取消</button></form> : <button type="button" onClick={() => setAddingTopic(true)} aria-label="增加兴趣主题">＋</button>}</div></div></article>
            {(data.workspace.slots || []).map((slot) => <article className={`wiki-hotspot-card ${slot.is_read ? 'read' : ''}`} key={slot.slot_id} onClick={() => readHotspot(slot)}><header><div className="wiki-hotspot-actions"><button type="button" disabled={!slot.hotspot_id || slot.added_to_wiki} onClick={(event) => addHotspotToWiki(event, slot.hotspot_id)}>{slot.added_to_wiki ? '已进入 LLM Wiki' : '进入 LLM Wiki'}</button><div className={`wiki-topic-select ${openTopicSlot === slot.slot_id ? 'open' : ''}`} onClick={(event) => event.stopPropagation()}><button type="button" className="wiki-topic-select-trigger" aria-expanded={openTopicSlot === slot.slot_id} onClick={() => setOpenTopicSlot((value) => value === slot.slot_id ? null : slot.slot_id)}><span>{slot.topic_name || '选择主题'}</span><i aria-hidden="true" /></button>{openTopicSlot === slot.slot_id ? <div className="wiki-topic-options"><button type="button" className={!slot.topic_id ? 'active' : ''} onClick={() => { selectTopic(slot.slot_id, ''); setOpenTopicSlot(null); }}>选择主题</button>{(data.workspace.topics || []).map((topic) => <button type="button" className={slot.topic_id === topic.topic_id ? 'active' : ''} onClick={() => { selectTopic(slot.slot_id, topic.topic_id); setOpenTopicSlot(null); }} key={topic.topic_id}>{topic.name}</button>)}</div> : null}</div></div></header><div><span>{slot.is_read ? '已读' : slot.hotspot_id ? '未读' : '待生成'}</span><h3>{slot.title || (slot.topic_name ? `${slot.topic_name} · 等待中午更新` : '请选择兴趣主题')}</h3><p>{slot.content || '选择主题后，系统将在中午自动收集并总结最新进展。'}</p></div></article>)}
          </div>
          {openHotspot ? <div className="wiki-hotspot-reader"><button type="button" onClick={() => setOpenHotspot(null)} aria-label="关闭">×</button><span>{openHotspot.topic_name}</span><h2>{openHotspot.title}</h2><article className="wiki-hotspot-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{normalizeHotspotMarkdown(openHotspot.content)}</ReactMarkdown></article></div> : null}
        </section>
      </>}
    </div></div>
  </section>;
}

export default function AppEnhanced() {
  const [view, setView] = useState('chat');
  const [graphOpen, setGraphOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsSection, setSettingsSection] = useState('general');
  const [setupFocus, setSetupFocus] = useState('');
  const [modelSetupPrompt, setModelSetupPrompt] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateNoticeOpen, setUpdateNoticeOpen] = useState(true);
  const [updateDetailOpen, setUpdateDetailOpen] = useState(false);
  const [featureMenuOpen, setFeatureMenuOpen] = useState(false);
  const [enabledFeatures, setEnabledFeatures] = useState(() => {
    try { return [...new Set(['notes', ...JSON.parse(localStorage.getItem('personal-agent:enabled-features') || '[]')])]; }
    catch { return ['notes']; }
  });
  const [libraryOpenRequest, setLibraryOpenRequest] = useState(null);
  const [theme, setTheme] = useState(() => localStorage.getItem('personal-agent:surface-theme-v2') || 'light');
  const appearance = useWorkspaceAppearance();
  const cardOpacity = useCardOpacity();
  const wallpaperView = ['chat', 'learning', 'code'].includes(view);
  useEffect(() => { localStorage.setItem('personal-agent:surface-theme-v2', theme); }, [theme]);
  useEffect(() => { localStorage.setItem('personal-agent:enabled-features', JSON.stringify(enabledFeatures)); }, [enabledFeatures]);
  useEffect(() => {
    fetch(`${API_BASE}/api/settings/models/retrieval`).then((response) => response.ok ? response.json() : null).then((data) => {
      if (data && !data.ready) setModelSetupPrompt(true);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    if (!window.desktopAPI?.checkForUpdates) return undefined;
    let active = true;
    const timer = window.setTimeout(() => {
      window.desktopAPI.checkForUpdates().then((data) => {
        if (active && data?.available) setUpdateInfo(data);
      }).catch(() => {});
    }, 1800);
    return () => { active = false; window.clearTimeout(timer); };
  }, []);
  const addFeature = async (feature) => {
    if (feature === 'notes') {
      try {
        const response = await fetch(`${API_BASE}/api/settings/obsidian-wiki`);
        const config = response.ok ? await response.json() : {};
        if (!config.connected) {
          setSettingsSection('basic'); setSetupFocus('wiki'); setSettingsOpen(true); setFeatureMenuOpen(false);
          return;
        }
      } catch { setSettingsSection('basic'); setSetupFocus('wiki'); setSettingsOpen(true); return; }
    }
    setEnabledFeatures((current) => current.includes(feature) ? current : [...current, feature]);
    setFeatureMenuOpen(false);
  };
  const openSettings = () => { setSettingsSection('general'); setSetupFocus(''); setSettingsOpen(true); };
  const navigate = (next) => { setView(next); if (!next.endsWith('-graph')) setGraphOpen(false); };
  const graph = () => { setGraphOpen((value) => !value); if (!view.endsWith('-graph')) setView('memory-graph'); };
  const openLibraryDocument = (documentId) => {
    setLibraryOpenRequest({ documentId, requestId: Date.now() });
    setView('learning');
    setGraphOpen(false);
  };
  const openLibraryNote = (filename) => {
    setLibraryOpenRequest({ filename, requestId: Date.now() });
    setView('learning');
    setGraphOpen(false);
  };
  const openWikiPage = (pageId) => {
    setLibraryOpenRequest({ pageId, requestId: Date.now() });
    setView('learning');
    setGraphOpen(false);
  };
  return <div data-ui-theme={theme} className={`app-shell enhanced-shell view-${view} ${wallpaperView ? 'wallpaper-view' : 'graph-view'} ${appearance.config.enabled && appearance.asset ? 'wallpaper-enabled' : 'wallpaper-disabled'}`} style={{ '--workspace-glass-blur': `${appearance.config.glass}px`, '--workspace-border-alpha': appearance.config.border / 100, '--dashboard-glass-blur': `${cardOpacity.values.dashboardGlass ?? 22}px`, '--chat-glass-blur': `${cardOpacity.values.chatGlass ?? 18}px`, '--note-glass-blur': `${cardOpacity.values.noteGlass ?? 6}px`, '--code-glass-blur': `${cardOpacity.values.codeGlass ?? 8}px`, '--star-brief-glass-blur': `${cardOpacity.values.starBriefGlass ?? 8}px`, '--star-source-glass-blur': `${cardOpacity.values.starSourceGlass ?? 10}px`, '--card-opacity-chat': (100 - (cardOpacity.values.chat ?? 35)) / 100, '--card-opacity-dashboard': (100 - cardOpacity.values.dashboard) / 100, '--card-opacity-note': (100 - cardOpacity.values.note) / 100, '--card-opacity-code': (100 - cardOpacity.values.code) / 100, '--card-opacity-star-brief': (100 - cardOpacity.values.starBrief) / 100, '--card-opacity-star-source': (100 - cardOpacity.values.starSource) / 100 }}>
    <nav className="app-nav-frame" aria-label="功能导航"><div className="app-nav-primary">
      <button className={`app-nav-cell ${view === 'chat' ? 'active' : ''}`} data-tooltip="仪表盘" onClick={() => navigate('chat')}><Icon type="chat"/></button>
      <button className={`app-nav-cell ${view === 'learning' ? 'active' : ''}`} data-tooltip="笔记与文档" onClick={() => navigate('learning')}><Icon type="notes"/></button>
      {enabledFeatures.includes('projects') && <button className={`app-nav-cell ${view === 'code' ? 'active' : ''}`} data-tooltip="代码项目" onClick={() => navigate('code')}><Icon type="code"/></button>}
      <div className={`app-nav-group app-graph-nav-group ${graphOpen ? 'open' : ''}`}><button className={`app-nav-cell ${view.endsWith('-graph') ? 'active' : ''}`} data-tooltip="知识图谱" onClick={graph}><Icon type="graph"/></button><div className="app-nav-submenu">
        <button className={`app-nav-subcell ${view === 'memory-graph' ? 'active' : ''}`} data-tooltip="记忆图谱" onClick={() => setView('memory-graph')}><Icon type="memory"/></button>
        <button className={`app-nav-subcell ${view === 'note-graph' ? 'active' : ''}`} data-tooltip="笔记图谱" onClick={() => setView('note-graph')}><Icon type="noteGraph"/></button>
        {enabledFeatures.includes('projects') && <button className={`app-nav-subcell ${view === 'project-graph' ? 'active' : ''}`} data-tooltip="项目图谱" onClick={() => setView('project-graph')}><Icon type="projectGraph"/></button>}
      </div></div>
      <div className="app-feature-add"><button className={`app-nav-cell ${featureMenuOpen ? 'active' : ''}`} data-tooltip="添加界面" onClick={() => setFeatureMenuOpen((value) => !value)}>+</button>{featureMenuOpen && <div className="app-feature-menu">
        {[['projects', '代码项目', 'code']].map(([id, label, icon]) => <div key={id}><span><Icon type={icon}/>{label}</span><button disabled={enabledFeatures.includes(id)} onClick={() => addFeature(id)}>{enabledFeatures.includes(id) ? '已加入' : '加入'}</button></div>)}
      </div>}</div>
    </div><div className="app-settings-anchor">{updateInfo && updateNoticeOpen ? <aside className="app-update-notice" role="status"><button type="button" className="app-update-close" aria-label="关闭更新提示" onClick={() => setUpdateNoticeOpen(false)}>×</button><span>有更新</span><strong>{updateInfo.latestVersion}</strong><button type="button" className="app-update-link" onClick={() => setUpdateDetailOpen(true)}>查看更新</button></aside> : null}{updateDetailOpen && updateInfo ? <div className="app-update-detail-backdrop" onMouseDown={() => setUpdateDetailOpen(false)}><section className="app-update-detail" onMouseDown={(event) => event.stopPropagation()}><button type="button" className="app-update-detail-close" aria-label="关闭" onClick={() => setUpdateDetailOpen(false)}>×</button><span>KnowNexus 更新</span><h2>{updateInfo.releaseName || `版本 ${updateInfo.latestVersion}`}</h2><div className="app-update-version"><b>v{updateInfo.currentVersion}</b><i>→</i><strong>v{updateInfo.latestVersion}</strong></div>{updateInfo.releaseNotes ? <p>{updateInfo.releaseNotes}</p> : <p>发现新版本。下载后解压覆盖程序文件即可，个人数据仍保存在独立的数据目录中。</p>}<footer><small>{updateInfo.assetName}{updateInfo.assetSize ? ` · ${(updateInfo.assetSize / 1048576).toFixed(1)} MB` : ''}</small><button type="button" onClick={() => window.desktopAPI?.openUpdatePage?.(updateInfo.assetUrl || updateInfo.releaseUrl)}>下载更新</button></footer></section></div> : null}<button className={`app-nav-cell app-settings-button ${updateInfo ? 'has-update' : ''}`} data-tooltip={updateInfo ? `有更新：${updateInfo.latestVersion}` : '设置'} onClick={openSettings}><Icon type="settings"/><i className="app-update-dot" aria-hidden="true"/></button></div></nav>
    <main className="app-page-frame">
      <div className={`workspace-backdrop-host ${wallpaperView ? 'visible' : 'graph-hidden'}`}>
        <WorkspaceBackdrop asset={appearance.asset} config={appearance.config}/>
      </div>
      <div className="app-page-content">
      <div className={`app-persistent-chat ${view === 'chat' ? 'active' : ''}`}><HomeDashboard apiBase={API_BASE}/></div>
      {view === 'memory-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/memory" graphDomain="memory" title="记忆图谱" directoryTitle="记忆时间线" simpleMode memoryOriginSelector/>}
      {view === 'note-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/notes" graphDomain="note" title="笔记图谱" directoryTitle="笔记目录" simpleMode directoryMode="notes" onOpenLibraryDocument={openLibraryDocument} onOpenLibraryNote={openLibraryNote} onOpenWikiPage={openWikiPage}/>}
      {view === 'project-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/projects" graphDomain="project" title="项目图谱" directoryTitle="项目目录"/>}
      {view === 'learning' && <LibraryWorkspacePage apiBase={API_BASE} openDocumentRequest={libraryOpenRequest} onOpenDocumentRequestHandled={() => setLibraryOpenRequest(null)}/>}
      {view === 'code' && <CodeInsightPage apiBase={`${API_BASE}/api/library/code-projects`} agentApi={`${API_BASE}/api/agent/chat`}/>} 
    </div></main>
    {modelSetupPrompt && <div className="model-setup-prompt-backdrop" onMouseDown={() => setModelSetupPrompt(false)}><section className="model-setup-prompt" onMouseDown={(event) => event.stopPropagation()}><span>必要配置</span><h2>本地检索模型尚未就绪</h2><p>Embedding 与 Reranker 用于本地知识检索和排序。你可以现在安装，也可以关闭提示后稍后在“设置 → 基础配置”中处理。</p><div><button type="button" className="secondary" onClick={() => setModelSetupPrompt(false)}>暂时关闭</button><button type="button" onClick={() => { setModelSetupPrompt(false); setSettingsSection('basic'); setSetupFocus('models'); setSettingsOpen(true); }}>去配置</button></div></section></div>}
    <Dashboard apiBase={API_BASE}/><Settings open={settingsOpen} close={() => setSettingsOpen(false)} appearance={appearance} cardOpacity={cardOpacity} theme={theme} setTheme={setTheme} initialSection={settingsSection} setupFocus={setupFocus} onWikiReady={() => { setEnabledFeatures((current) => current.includes('notes') ? current : [...current, 'notes']); setSetupFocus(''); }}/><DesktopWindowControls/>
  </div>;
}
