import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { consumeSse } from './api/sseClient.js';

const createId = () => globalThis.crypto?.randomUUID?.() || `agent-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const traceStorageKey = (sessionId) => `knownexus:chat-trace:${sessionId}`;
const thinkingPhrases = ['正在把线索排成队', '正在翻阅记忆抽屉', '正在和答案碰头', '快好了，再理一遍'];

function initialConversationMessages(sessionId, initialMessages) {
  if (sessionId) {
    try {
      const cached = JSON.parse(localStorage.getItem(traceStorageKey(sessionId)) || 'null');
      if (Array.isArray(cached) && cached.length) return cached;
    } catch {
      // 缓存损坏时使用后端会话正文，不影响正常对话。
    }
  }
  return Array.isArray(initialMessages)
    ? initialMessages
    : [{ role: 'assistant', content: '你好，我是你的个人知识助手。可以让我查询知识、生成笔记或分析代码项目。' }];
}

// 保留原右侧对话框结构与样式，仅把请求适配到新的 Main Agent Loop API。
function AIChatPanel({
  apiBase = '',
  title = 'AI 助手',
  variant = 'sidebar',
  sessionId = '',
  initialMessages = null,
  onTurnCompleted = null,
}) {
  const [messages, setMessages] = useState(() => initialConversationMessages(sessionId, initialMessages));
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [activeRunId, setActiveRunId] = useState('');
  const [cancelling, setCancelling] = useState(false);
  const [connection, setConnection] = useState('checking');
  const [modelOptions, setModelOptions] = useState([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [thinkingPhrase, setThinkingPhrase] = useState(0);
  const listRef = useRef(null);
  const sessionIdRef = useRef(sessionId || createId());
  const messagesRef = useRef(messages);
  const ownedRunIdsRef = useRef(new Set());

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 5000);
    fetch(`${apiBase}/api/agent/profiles`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setConnection('online');
      })
      .catch(() => setConnection('offline'))
      .finally(() => window.clearTimeout(timer));
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [apiBase]);

  useEffect(() => {
    const loadModels = () => fetch(`${apiBase}/api/settings/models`).then((response) => response.ok ? response.json() : null).then((data) => {
      if (!data) return;
      setModelOptions(data.providers || []);
      setSelectedModel(data.active_provider_id || data.providers?.[0]?.provider_id || '');
    }).catch(() => {});
    loadModels();
    window.addEventListener('knownexus:model-providers-changed', loadModels);
    return () => window.removeEventListener('knownexus:model-providers-changed', loadModels);
  }, [apiBase]);

  const selectModel = async (providerId) => {
    if (providerId === selectedModel) return;
    const previous = selectedModel;
    setSelectedModel(providerId);
    try {
      const response = await fetch(`${apiBase}/api/settings/models/${encodeURIComponent(providerId)}/activate`, { method: 'POST' });
      if (!response.ok) throw new Error('切换失败');
      window.dispatchEvent(new Event('knownexus:model-providers-changed'));
    } catch {
      setSelectedModel(previous);
    }
  };

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    if (!sending) { setThinkingPhrase(0); return undefined; }
    const timer = window.setInterval(() => setThinkingPhrase((value) => (value + 1) % thinkingPhrases.length), 2200);
    return () => window.clearInterval(timer);
  }, [sending]);

  useEffect(() => {
    if (variant !== 'page' || !sessionId) return;
    localStorage.setItem(traceStorageKey(sessionId), JSON.stringify(messages));
  }, [messages, sessionId, variant]);

  useEffect(() => {
    let disposed = false;
    const terminalStatuses = new Set(['completed', 'failed', 'cancelled', 'blocked', 'budget_exhausted']);
    const messageRunId = (message) => message.runId
      || [...(message.processEvents || [])].reverse().find((event) => event.runId)?.runId
      || '';

    const reconcilePersistedRuns = async () => {
      const streamingMessages = messagesRef.current.filter((message) => message.streaming);
      const orphaned = streamingMessages.filter((message) => !messageRunId(message));
      if (orphaned.length) {
        setMessages((current) => current.map((message) => (
          message.streaming && !messageRunId(message)
            ? {
                ...message,
                streaming: false,
                processEvents: [...(message.processEvents || []), {
                  id: `orphaned:${Date.now()}`,
                  type: 'run_reconciled',
                  agent: 'main',
                  message: '未找到可查询的运行编号，已清除过期运行状态',
                }],
              }
            : message
        )));
      }
      const pending = streamingMessages
        .filter((message) => message.streaming)
        .map((message) => ({ message, runId: messageRunId(message) }))
        .filter(({ runId }) => runId && !ownedRunIdsRef.current.has(runId));
      if (!pending.length || disposed) return;

      const results = await Promise.all(pending.map(async ({ runId }) => {
        try {
          const response = await fetch(`${apiBase}/api/agent/runs/${encodeURIComponent(runId)}`);
          if (response.status === 404) return { runId, missing: true };
          if (!response.ok) return null;
          return { runId, run: await response.json() };
        } catch {
          return null;
        }
      }));
      if (disposed) return;

      const active = results.find((item) => item?.run && !terminalStatuses.has(item.run.status));
      if (active) {
        setSending(true);
        setActiveRunId(active.runId);
      }
      const settled = new Map(
        results.filter((item) => item && (item.missing || terminalStatuses.has(item.run?.status)))
          .map((item) => [item.runId, item]),
      );
      if (!settled.size) return;
      setMessages((current) => current.map((message) => {
        const runId = messageRunId(message);
        const result = settled.get(runId);
        if (!message.streaming || !result) return message;
        const status = result.missing ? 'unknown' : result.run.status;
        return {
          ...message,
          streaming: false,
          meta: { ...(message.meta || {}), status },
          processEvents: [...(message.processEvents || []), {
            id: `${runId}:reconciled`,
            type: 'run_reconciled',
            agent: 'main',
            runId,
            message: result.missing
              ? '运行记录已失效，可能是后端服务已经重启'
              : `已从后端同步最终状态：${status}`,
          }],
        };
      }));
      if (!active) {
        setSending(false);
        setActiveRunId('');
        setCancelling(false);
      }
    };

    reconcilePersistedRuns();
    const timer = window.setInterval(reconcilePersistedRuns, 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [apiBase, sessionId]);
  const suggestions = [
    { icon: '⌘', title: '解析本地代码', prompt: '帮我分析一个本地 Python 项目，重点说明整体架构和核心调用链。' },
    { icon: '✦', title: '生成学习笔记', prompt: '我想把一份本地文档整理成结构清晰的学习笔记。' },
    { icon: '◷', title: '检索个人知识', prompt: '请从我的个人知识库中检索相关内容并给出有依据的回答。' },
  ];

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setMessages((current) => [...current, { role: 'user', content: text }]);
    setInput('');
    setSending(true);
    const assistantId = createId();
    const turnId = createId();
    ownedRunIdsRef.current.add(turnId);
    setActiveRunId(turnId);
    setCancelling(false);
    setMessages((current) => [...current, {
      id: assistantId,
      role: 'assistant',
      content: '',
      streaming: true,
      processEvents: [],
      runId: turnId,
    }]);
    let completedResponse = null;
    try {
      const response = await fetch(`${apiBase}/api/agent/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionIdRef.current, turn_id: turnId, message: text }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.message || `请求失败（${response.status}）`);
      }
      await consumeSse(response, (eventName, envelope) => {
        const data = envelope.data || {};
        if (eventName === 'run_created') {
          const runId = data.run_id || envelope.run_id || turnId;
          setActiveRunId(runId);
          ownedRunIdsRef.current.add(runId);
          setMessages((current) => current.map((item) => (
            item.id === assistantId ? { ...item, runId } : item
          )));
        }
        if (eventName === 'answer_delta') {
          setMessages((current) => current.map((item) => (
            item.id === assistantId ? { ...item, content: `${item.content}${data.text || ''}` } : item
          )));
          return;
        }
        if (eventName === 'done') {
          completedResponse = data.response || {};
          setMessages((current) => current.map((item) => (
            item.id === assistantId ? { ...item, streaming: false, meta: completedResponse } : item
          )));
          return;
        }
        if (eventName === 'error') throw new Error(data.message || 'Agent 执行失败');
        setMessages((current) => current.map((item) => item.id === assistantId
          ? {
              ...item,
              processEvents: [...(item.processEvents || []), {
                id: `${envelope.run_id || turnId}:${item.processEvents?.length || 0}`,
                type: eventName,
                agent: envelope.agent || data.agent || 'main',
                runId: envelope.run_id,
                ...data,
              }],
            }
          : item));
      });
      onTurnCompleted?.({ sessionId: sessionIdRef.current, userMessage: text, response: completedResponse || {} });
    } catch (error) {
      setMessages((current) => current.map((item) => item.id === assistantId
        ? { ...item, streaming: false, content: `暂时无法连接 AI 服务：${error.message}` }
        : item));
    } finally {
      ownedRunIdsRef.current.delete(turnId);
      setSending(false);
      setActiveRunId('');
      setCancelling(false);
    }
  };

  const cancelCurrentRun = async () => {
    if (!sending || !activeRunId || cancelling) return;
    setCancelling(true);
    try {
      const response = await fetch(
        `${apiBase}/api/agent/runs/${encodeURIComponent(activeRunId)}/cancel`,
        { method: 'POST' },
      );
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `取消失败（${response.status}）`);
      }
      setMessages((current) => current.map((item) => (
        item.streaming
          ? {
              ...item,
              processEvents: [...(item.processEvents || []), {
                id: `${activeRunId}:cancel-requested`,
                type: 'cancel_requested',
                agent: 'main',
                runId: activeRunId,
                message: '已请求停止，正在等待当前模型调用安全返回',
              }],
            }
          : item
      )));
    } catch (error) {
      setCancelling(false);
      setMessages((current) => current.map((item) => (
        item.streaming
          ? {
              ...item,
              processEvents: [...(item.processEvents || []), {
                id: `${activeRunId}:cancel-error`,
                type: 'cancel_error',
                agent: 'main',
                runId: activeRunId,
                message: error.message,
              }],
            }
          : item
      )));
    }
  };

  const pageGreetingOnly = variant === 'page' && messages.length === 1 && messages[0]?.role === 'assistant';

  return (
    <div className={`ai-panel ai-panel-${variant}`}>
      {variant !== 'page' && (
        <div className="ai-header">
          <span className="ai-title">{title}</span>
          <span className={`ai-connection ${connection}`}>
            <i />{connection === 'online' ? '已连接' : connection === 'offline' ? '未连接' : '连接中'}
          </span>
        </div>
      )}
      <div className="ai-messages" ref={listRef}>
        {pageGreetingOnly && !sending && (
          <div className="chat-welcome">
            <div className="chat-orbit" aria-hidden="true">
              <span className="chat-orbit-core">✦</span>
              <span className="chat-orbit-dot dot-one" />
              <span className="chat-orbit-dot dot-two" />
            </div>
            <h1>从一个问题开始</h1>
            <p>我会识别你的意图，并按需调用代码解析、学习笔记或个人知识检索 Agent。</p>
            <div className="chat-suggestions">
              {suggestions.map((item) => (
                <button key={item.title} type="button" onClick={() => setInput(item.prompt)}>
                  <span>{item.icon}</span>
                  <strong>{item.title}</strong>
                  <small>点击填入示例请求</small>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((message, index) => pageGreetingOnly && index === 0 ? null : (
          <div key={index} className={`ai-msg ${message.role}`}>
            {message.role === 'assistant' ? (
              <div className="ai-bubble markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content.replace(/\n{3,}/g, '\n\n')}</ReactMarkdown>
                {message.meta && <small className="ai-run-meta">{message.meta.status} · {message.meta.iterations} iterations · {message.meta.tool_calls} tools</small>}
              </div>
            ) : <div className="ai-bubble">{message.content}</div>}
          </div>
        ))}
      </div>
      <div className="ai-input-area">
        {sending && <div className="ai-thinking-status" role="status" aria-live="polite"><span className="thinking-spark">✦</span><span>{thinkingPhrases[thinkingPhrase]}</span><span className="thinking-dots" aria-hidden="true"><i/><i/><i/></span></div>}
        <textarea
          className="ai-input"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } }}
          placeholder={sending ? '当前任务执行中，请先停止后再发送新消息' : '输入消息，Enter 发送…'}
          disabled={sending}
          rows={2}
        />
        <div className="ai-composer-footer"><div className={`ai-model-picker ${modelMenuOpen ? 'open' : ''}`} title="选择已配置模型">{modelMenuOpen && <div className="ai-model-menu"><header>选择模型</header>{modelOptions.map((provider) => <button type="button" key={provider.provider_id} className={selectedModel === provider.provider_id ? 'active' : ''} onClick={() => { selectModel(provider.provider_id); setModelMenuOpen(false); }}><span><strong>{provider.name}</strong><small>{provider.model}</small></span><b>{selectedModel === provider.provider_id ? '✓' : ''}</b></button>)}</div>}<button type="button" className="ai-model-trigger" onClick={() => !sending && setModelMenuOpen((value) => !value)} disabled={sending}><span>{modelOptions.find((provider) => provider.provider_id === selectedModel)?.name || '选择模型'}</span><small>{modelOptions.find((provider) => provider.provider_id === selectedModel)?.model || ''}</small></button></div><button
            className={`ai-send ${sending ? 'is-stop' : ''}`}
            onClick={sending ? cancelCurrentRun : send}
            disabled={sending && cancelling}
            aria-label={sending ? (cancelling ? '正在停止' : '停止生成') : '发送消息'}
            title={sending ? (cancelling ? '正在停止' : '停止生成') : '发送消息'}
          >
            {sending ? <span className={`ai-stop-icon ${cancelling ? 'pending' : ''}`} aria-hidden="true"/> : <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 15V5M6.5 8.5 10 5l3.5 3.5" /></svg>}
          </button></div>
      </div>
    </div>
  );
}

export default AIChatPanel;
