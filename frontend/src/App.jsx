import { useEffect, useState } from 'react';
import StarfieldApp from './StarfieldApp.jsx';
import LibraryWorkspacePage from './LibraryWorkspacePage.jsx';
import CodeInsightPage from './CodeInsightPage.jsx';
import ChatPage from './ChatPage.jsx';
import './AppShell.css';
import './HarnessTheme.css';

const API_BASE = import.meta.env.VITE_API_BASE
  || window.desktopAPI?.apiBase
  || (import.meta.env.DEV ? 'http://127.0.0.1:8001' : '');

function NavIcon({ type }) {
  const paths = {
    chat: <><path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6a2.5 2.5 0 0 1-2.5 2.5H11l-4.2 3v-3.2A2.5 2.5 0 0 1 5 12.5z" /></>,
    graph: <><circle cx="6" cy="7" r="2" /><circle cx="18" cy="6" r="2" /><circle cx="12" cy="18" r="2" /><path d="m8 7 8-1M7.2 8.6l3.7 7.5M16.8 7.7l-3.7 8.4" /></>,
    notes: <><path d="M6 3.8h9.5L19 7.3V20H6z" /><path d="M15 4v4h4M9 11h7M9 14.5h7M9 18h4" /></>,
    code: <><path d="m9 7-5 5 5 5M15 7l5 5-5 5M13 4l-2 16" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a8 8 0 0 0-1.7-1L14.5 3h-5L9 6.1a8 8 0 0 0-1.7 1l-2.4-1-2 3.4 2 1.5a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a8 8 0 0 0 1.7 1l.5 3.1h5l.5-3.1a8 8 0 0 0 1.7-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1z" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[type]}</svg>;
}

function SettingsDialog({ open, onClose, theme, onThemeChange }) {
  const [section, setSection] = useState('general');
  if (!open) return null;
  const sections = [['general', '通用'], ['models', '模型'], ['agents', 'Agent'], ['plugins', '插件'], ['about', '关于']];
  return (
    <div className="harness-modal-backdrop" onMouseDown={onClose}>
      <section className="harness-settings" onMouseDown={(event) => event.stopPropagation()}>
        <header><strong>设置</strong><button type="button" onClick={onClose}>×</button></header>
        <div className="harness-settings-body">
          <nav>{sections.map(([id, label]) => <button type="button" className={section === id ? 'active' : ''} onClick={() => setSection(id)} key={id}>{label}</button>)}</nav>
          <main>
            <h2>{sections.find(([id]) => id === section)?.[1]}</h2>
            {section === 'general' ? <>
              <div className="settings-row"><div><strong>外观</strong><p>选择工作台的显示主题。</p></div><div className="theme-switch">{['dark', 'light', 'system'].map((item) => <button type="button" className={theme === item ? 'active' : ''} onClick={() => onThemeChange(item)} key={item}>{item === 'dark' ? '深色' : item === 'light' ? '浅色' : '跟随系统'}</button>)}</div></div>
              <div className="settings-row"><div><strong>语言</strong><p>界面显示语言。</p></div><button className="settings-select" type="button">简体中文⌄</button></div>
              <div className="settings-row"><div><strong>通知</strong><p>任务完成后显示桌面提醒。</p></div><span className="settings-toggle active"><i /></span></div>
            </> : <div className="settings-placeholder"><span>◇</span><h3>{sections.find(([id]) => id === section)?.[1]}设置</h3><p>界面已预留，暂不连接后端配置。</p></div>}
          </main>
        </div>
      </section>
    </div>
  );
}

function FloatingDashboard({ apiBase }) {
  const [open, setOpen] = useState(false);
  const [stats, setStats] = useState({ ai_notes: {}, personal_documents: {}, projects: {} });
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [libraryResponse, projectsResponse] = await Promise.all([
        fetch(`${apiBase}/api/library/notes/dashboard`),
        fetch(`${apiBase}/api/library/code-projects`),
      ]);
      const library = libraryResponse.ok ? await libraryResponse.json() : {};
      const projectData = projectsResponse.ok ? await projectsResponse.json() : {};
      const projects = projectData.projects || [];
      setStats({
        ...library,
        projects: {
          count: projects.length,
          files: projects.reduce((sum, item) => sum + Number(item.total_files || 0), 0),
          blocks: projects.reduce((sum, item) => sum + Number(item.total_blocks || 0), 0),
        },
      });
    } finally { setLoading(false); }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) load();
  };

  return <div className={`global-dashboard ${open ? 'open' : ''}`}>
    <button className="global-dashboard-orb" type="button" onClick={toggle} aria-label={open ? '收起知识库仪表盘' : '打开知识库仪表盘'} title="知识库概览">
      {open ? '×' : <><span /><i /><b /></>}
    </button>
    {open && <aside className="global-dashboard-panel">
      <header><div><span>KNOWLEDGE OVERVIEW</span><h2>知识库概览</h2></div><small>{loading ? '同步中…' : '本地实时统计'}</small></header>
      <div className="global-dashboard-grid">
        <article className="metric-notes"><span>AI NOTES</span><strong>{stats.ai_notes?.count || 0}</strong><p>AI 生成笔记</p><small>{stats.ai_notes?.folders || 0} 个自定义目录</small></article>
        <article className="metric-documents"><span>DOCUMENTS</span><strong>{stats.personal_documents?.count || 0}</strong><p>个人文档</p><small>{stats.personal_documents?.imported || 0} 个导入 · {stats.personal_documents?.source_files || 0} 个源文件</small></article>
        <article className="metric-projects"><span>CODE PROJECTS</span><strong>{stats.projects?.count || 0}</strong><p>已解析项目</p><small>{stats.projects?.files || 0} 个文件 · {stats.projects?.blocks || 0} 个代码块</small></article>
      </div>
    </aside>}
  </div>;
}

function App() {
  const [view, setView] = useState('chat');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState(() => localStorage.getItem('personal-agent:theme') || 'dark');

  useEffect(() => {
    localStorage.setItem('personal-agent:theme', theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const navigate = (next) => setView(next);
  return (
    <div className="app-shell">
      <main className="app-page-frame">
        <div className={`app-persistent-chat ${view === 'chat' ? 'active' : ''}`}><ChatPage apiBase={API_BASE} /></div>
        {view === 'memory-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/memory" graphDomain="memory" title="KnowNexus 记忆图谱" directoryTitle="记忆时间线" simpleMode memoryOriginSelector />}
        {view === 'note-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/notes" graphDomain="note" title="KnowNexus 笔记图谱" directoryTitle="笔记目录" simpleMode directoryMode="notes" />}
        {view === 'project-graph' && <StarfieldApp apiBase={API_BASE} graphEndpoint="/api/graphs/projects" graphDomain="project" title="KnowNexus 项目图谱" directoryTitle="项目目录" />}
        {view === 'learning' && <LibraryWorkspacePage apiBase={API_BASE} />}
        {view === 'code' && <CodeInsightPage apiBase={`${API_BASE}/api/library/code-projects`} agentApi={`${API_BASE}/api/agent/chat`} />}
      </main>

      <nav className="app-nav-frame" aria-label="功能导航">
        <div className="app-brand" title="Personal Agent"><span>D</span></div>
        <div className="app-nav-primary">
          <button className={`app-nav-cell ${view === 'chat' ? 'active' : ''}`} data-tooltip="对话" onClick={() => navigate('chat')}><NavIcon type="chat" /></button>
          <button className={`app-nav-cell ${view === 'learning' ? 'active' : ''}`} data-tooltip="笔记" onClick={() => navigate('learning')}><NavIcon type="notes" /></button>
          <button className={`app-nav-cell ${view === 'code' ? 'active' : ''}`} data-tooltip="代码" onClick={() => navigate('code')}><NavIcon type="code" /></button>
          <div className="app-nav-group app-graph-nav-group">
            <button className={`app-nav-cell ${view.endsWith('-graph') ? 'active' : ''}`} data-tooltip="知识图谱" onClick={() => navigate('memory-graph')}><NavIcon type="graph" /></button>
            <div className="app-nav-submenu app-nav-submenu-fixed" aria-label="知识图谱子页面">
              <button className={view === 'memory-graph' ? 'active' : ''} data-tooltip="记忆图谱" aria-label="记忆图谱" onClick={() => navigate('memory-graph')}>M</button>
              <button className={view === 'note-graph' ? 'active' : ''} data-tooltip="笔记图谱" aria-label="笔记图谱" onClick={() => navigate('note-graph')}>N</button>
              <button className={view === 'project-graph' ? 'active' : ''} data-tooltip="项目图谱" aria-label="项目图谱" onClick={() => navigate('project-graph')}>P</button>
            </div>
          </div>
        </div>
        <button className="app-nav-cell app-settings-button" data-tooltip="设置" onClick={() => setSettingsOpen(true)}><NavIcon type="settings" /></button>
        <div className="app-profile" title="本地个人知识库">P</div>
      </nav>
      <FloatingDashboard apiBase={API_BASE} />
      <SettingsDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} theme={theme} onThemeChange={setTheme} />
    </div>
  );
}

export default App;
