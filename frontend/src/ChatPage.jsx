import { useCallback, useEffect, useMemo, useState } from 'react';
import AIChatPanel from './AIChatPanel.jsx';

const createId = () => globalThis.crypto?.randomUUID?.() || `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const lastSessionKey = 'personal-agent:last-chat-session';
const greeting = [];
const durationText = (seconds = 0) => {
  if (!seconds) return '0 分钟';
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`;
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor((seconds % 3600) / 60)} 分`;
};

/** 默认对话主页：复用统一 Main Agent API，但使用中间区域的宽屏对话布局。 */
function ChatPage({ apiBase = '', floating = false }) {
  const [collapsed, setCollapsed] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [activeId, setActiveId] = useState(() => window.localStorage.getItem(lastSessionKey) || createId());
  const [activeMessages, setActiveMessages] = useState(greeting);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [watcherStatus, setWatcherStatus] = useState({ watchers: [], running: false, active_count: 0 });
  const [watcherStatistics, setWatcherStatistics] = useState({ watchers: [], active_count: 0 });
  const [statisticsRange, setStatisticsRange] = useState('all');
  const [watcherError, setWatcherError] = useState('');

  const fetchSessions = useCallback(async () => {
    const response = await fetch(`${apiBase}/api/agent/sessions`);
    if (!response.ok) throw new Error(`加载会话失败（${response.status}）`);
    const data = await response.json();
    return (data.sessions || []).filter((session) => Number(session.message_count || 0) > 0);
  }, [apiBase]);

  const openSession = useCallback(async (sessionId) => {
    setLoadingHistory(true);
    try {
      const response = await fetch(`${apiBase}/api/agent/sessions/${encodeURIComponent(sessionId)}/messages`);
      if (!response.ok) throw new Error(`加载消息失败（${response.status}）`);
      const data = await response.json();
      setActiveId(sessionId);
      setActiveMessages(data.messages?.length ? data.messages : greeting);
    } finally {
      setLoadingHistory(false);
    }
  }, [apiBase]);

  useEffect(() => {
    let active = true;
    fetchSessions()
      .then((items) => {
        if (!active) return;
        setSessions(items);
        const remembered = window.localStorage.getItem(lastSessionKey);
        if (remembered && items.some((item) => item.session_id === remembered)) openSession(remembered);
        else setLoadingHistory(false);
      })
      .catch(() => setLoadingHistory(false));
    return () => { active = false; };
  }, [fetchSessions, openSession]);

  useEffect(() => {
    window.localStorage.setItem(lastSessionKey, activeId);
  }, [activeId]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const rangeDays = { day: 1, week: 7, month: 30 }[statisticsRange];
        const query = rangeDays ? `?start_at=${encodeURIComponent(new Date(Date.now() - rangeDays * 86400000).toISOString())}` : '';
        const [statusResponse, statisticsResponse] = await Promise.all([
          fetch(`${apiBase}/api/integrations/codex-watcher`),
          fetch(`${apiBase}/api/integrations/codex-watcher/statistics${query}`),
        ]);
        if (!statusResponse.ok || !statisticsResponse.ok) throw new Error(`统计请求失败（${statisticsResponse.status}）`);
        const [statusData, statisticsData] = await Promise.all([statusResponse.json(), statisticsResponse.json()]);
        if (active) { setWatcherStatus(statusData); setWatcherStatistics(statisticsData); setWatcherError(''); }
      } catch (cause) {
        if (active) setWatcherError(cause.message);
      }
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [apiBase, statisticsRange]);

  const watcherTotals = useMemo(() => (watcherStatistics.watchers || []).reduce((total, watcher) => ({
    turns: total.turns + (watcher.captured_turns || 0),
    conversations: total.conversations + (watcher.conversation_count || 0),
    tokens: total.tokens + (watcher.distillation_tokens || 0),
    memories: total.memories + (watcher.memory_points || 0),
  }), { turns: 0, conversations: 0, tokens: 0, memories: 0 }), [watcherStatistics]);
  const fileSizeText = (bytes = 0) => bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(1)} GB`
    : bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB`
      : bytes >= 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${bytes} B`;
  const activeSession = sessions.find((session) => session.session_id === activeId);

  const newConversation = () => {
    setActiveId(createId());
    setActiveMessages(greeting);
    setLoadingHistory(false);
  };

  const refreshAfterTurn = async ({ sessionId, userMessage }) => {
    try {
      const items = await fetchSessions();
      setSessions(items);
      if (!items.some((item) => item.session_id === sessionId)) {
        setSessions((current) => [{
          session_id: sessionId,
          title: userMessage.slice(0, 48),
          message_count: 2,
          updated_at: new Date().toISOString(),
        }, ...current]);
      }
    } catch {
      // 回答已经成功，目录刷新失败不应覆盖当前对话。
    }
  };

  const deleteConversation = async (event, sessionId) => {
    event.stopPropagation();
    if (!globalThis.confirm('删除这个会话？已经蒸馏的长期记忆不会被删除。')) return;
    const response = await fetch(`${apiBase}/api/agent/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) return;
    localStorage.removeItem(`personal-agent:chat-trace:${sessionId}`);
    const remaining = sessions.filter((item) => item.session_id !== sessionId);
    setSessions(remaining);
    if (activeId === sessionId) {
      if (remaining.length) openSession(remaining[0].session_id);
      else newConversation();
    }
  };

  if (floating) return (
    <section className="chat-page floating-chat-layout" aria-label="个人知识助手对话">
      <aside className="floating-session-sidebar"><button type="button" className="floating-new-chat" onClick={newConversation}>＋ 新对话</button><div className="floating-session-list">{sessions.map((session) => <button type="button" key={session.session_id} className={activeId === session.session_id ? 'active' : ''} onClick={() => openSession(session.session_id)}><strong>{session.title || '新对话'}</strong><small>{session.message_count || 0} 条消息</small></button>)}{!sessions.length && <p>暂无历史会话</p>}</div></aside>
      <main className="floating-conversation-main"><div className="chat-conversation-stage">{loadingHistory ? <div className="chat-history-loading">正在载入会话…</div> : <AIChatPanel key={activeId} apiBase={apiBase} title="个人知识助手" variant="page" sessionId={activeId} initialMessages={activeMessages} onTurnCompleted={refreshAfterTurn}/>}</div></main>
    </section>
  );
  return (
    <section className={`chat-page ${collapsed ? 'sessions-collapsed' : ''} ${floating ? 'floating-chat-layout' : ''}`} aria-label="个人知识助手对话">
      <aside className="chat-session-sidebar">
        <div className="chat-session-topbar">
          <button className="chat-session-toggle" type="button" onClick={() => setCollapsed((value) => !value)} title={collapsed ? '展开会话' : '收起会话'}>☰</button>
          {!collapsed && <span>对话</span>}
        </div>
        {!collapsed && (
          <>
            <button className="chat-new-session" type="button" onClick={newConversation}><span>＋</span>新对话</button>
            <div className="chat-session-section-title">最近</div>
            <div className="chat-session-list">
              {sessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`chat-session-item ${activeId === session.session_id ? 'active' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => openSession(session.session_id)}
                  onKeyDown={(event) => { if (event.key === 'Enter') openSession(session.session_id); }}
                >
                  <span className="chat-session-mark">✦</span>
                  <span className="chat-session-copy">
                    <strong>{session.title || '新对话'}</strong>
                    <small>{session.message_count || 0} 条消息</small>
                  </span>
                  <button className="chat-session-delete" type="button" onClick={(event) => deleteConversation(event, session.session_id)} title="删除会话">×</button>
                </div>
              ))}
              {!sessions.length && <p className="chat-session-empty">还没有已保存的对话</p>}
            </div>
          </>
        )}
      </aside>
      <div className="chat-conversation-stage">
        {loadingHistory ? (
          <div className="chat-history-loading">正在载入会话…</div>
        ) : (
          <AIChatPanel
            key={activeId}
            apiBase={apiBase}
            title="个人知识助手"
            variant="page"
            sessionId={activeId}
            initialMessages={activeMessages}
            onTurnCompleted={refreshAfterTurn}
          />
        )}
      </div>
      <aside className="chat-monitor-panel" aria-label="智能体监听统计">
        <header><div><span>MONITOR HISTORY</span><h2>监听统计</h2></div><div className="chat-monitor-header-tools"><select aria-label="统计时间范围" value={statisticsRange} onChange={(event) => setStatisticsRange(event.target.value)}><option value="all">全部</option><option value="day">近 24 小时</option><option value="week">近 7 天</option><option value="month">近 30 天</option></select><i className={watcherStatus.running ? 'running' : ''} title={watcherStatus.running ? '监听运行中' : '监听已停止'} /></div></header>
        <div className="chat-monitor-summary">
          <div><strong>{watcherStatus.active_count || 0}</strong><span>运行中</span></div>
          <div><strong>{watcherTotals.conversations}</strong><span>会话</span></div>
          <div><strong>{watcherTotals.turns}</strong><span>已捕获轮次</span></div>
          <div><strong>{Number(watcherTotals.tokens).toLocaleString('zh-CN')}</strong><span>蒸馏 Token</span></div>
        </div>
        <div className="chat-monitor-list">
          {(watcherStatistics.watchers || []).map((watcher) => <article className="chat-monitor-agent" key={watcher.id}>
            <div className="chat-monitor-agent-title"><i className={watcher.running ? 'running' : ''} /><div><strong>{watcher.name}</strong><small>{watcher.adapter_id || watcher.parser_type}</small></div><em>{watcher.running ? '监听中' : '已停止'}</em></div>
            <dl><div><dt>累计监听</dt><dd>{durationText(watcher.active_seconds)}</dd></div><div><dt>会话数量</dt><dd>{watcher.conversation_count || 0}</dd></div><div><dt>对话轮次</dt><dd>{watcher.captured_turns || 0}</dd></div><div><dt>蒸馏 Token</dt><dd>{Number(watcher.distillation_tokens || 0).toLocaleString('zh-CN')}</dd></div><div><dt>记忆点</dt><dd>{watcher.memory_points || 0}</dd></div><div><dt>实体 / 关系</dt><dd>{watcher.entities || 0} / {watcher.relations || 0}</dd></div><div><dt>监听文件</dt><dd>{fileSizeText(watcher.source_file_size || 0)}</dd></div><div><dt>最后修改</dt><dd>{watcher.source_last_modified ? new Date(watcher.source_last_modified).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}</dd></div></dl>
            <footer><span>{watcher.last_capture_at ? `最近捕获 ${new Date(watcher.last_capture_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '暂无新对话'}</span></footer>
            {watcher.pending_consolidation_count > 0 && <p title={watcher.last_consolidation_error}>有 {watcher.pending_consolidation_count} 个会话等待重新蒸馏</p>}
            {(watcher.last_error || watcher.error_count > 0) && <p title={watcher.last_error}>{watcher.last_error || `${watcher.error_count} 次扫描异常`}</p>}
          </article>)}
          {!(watcherStatistics.watchers || []).length && <div className="chat-monitor-empty">还没有配置外部智能体监听器。</div>}
        </div>
        {watcherError && <div className="chat-monitor-error">{watcherError}</div>}
        <p className="chat-monitor-note">统计每 5 分钟或监听关闭时写入本地数据库；不保存对话正文。</p>
      </aside>
    </section>
  );
}

export default ChatPage;
