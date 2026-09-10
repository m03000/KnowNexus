import { useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './LearningWorkspacePage.css';

const normalizeNote = (note) => ({
  ...note,
  id: note.filename,
  created_at: note.modified || note.date,
  title: note.title || note.filename?.replace(/\.md$/i, ''),
});

const formatDate = (value) => {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('zh-CN');
};

function LearningWorkspacePage({ apiBase = '' }) {
  const [notes, setNotes] = useState([]);
  const [selectedNote, setSelectedNote] = useState(null);
  const [noteSearch, setNoteSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [noteLoading, setNoteLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiBase}/api/library/notes`)
      .then(async (response) => {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.detail || `笔记请求失败（${response.status}）`);
        return data;
      })
      .then((data) => {
        if (cancelled) return;
        setNotes((data.notes || []).map(normalizeNote));
      })
      .catch((requestError) => !cancelled && setError(requestError.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [apiBase]);

  const visibleNotes = useMemo(() => {
    const keyword = noteSearch.trim().toLowerCase();
    const filtered = keyword
      ? notes.filter((note) => note.title?.toLowerCase().includes(keyword))
      : notes;
    return [...filtered].sort((left, right) => {
      const leftTime = new Date(left.created_at || 0).valueOf() || 0;
      const rightTime = new Date(right.created_at || 0).valueOf() || 0;
      return rightTime - leftTime;
    });
  }, [noteSearch, notes]);

  const noteGroups = useMemo(() => visibleNotes.reduce((groups, note) => {
    const key = String(note.created_at || '').slice(0, 7) || '其他';
    (groups[key] ||= []).push(note);
    return groups;
  }, {}), [visibleNotes]);

  const openNote = async (note) => {
    setSelectedNote(note);
    setNoteLoading(true);
    setError('');
    try {
      const response = await fetch(`${apiBase}/api/library/notes/${encodeURIComponent(note.filename)}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `笔记请求失败（${response.status}）`);
      setSelectedNote({ ...note, ...data });
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setNoteLoading(false);
    }
  };

  return (
    <div className="learning-workspace">
      <aside className="learning-notes-sidebar">
        <header className="learning-notes-header">
          <div><span>KNOWLEDGE NOTES</span><h1>学习笔记</h1></div>
          <div className="notes-header-actions"><span className="notes-count">{notes.length}</span></div>
        </header>
        <label className="notes-search">
          <span>⌕</span>
          <input value={noteSearch} onChange={(event) => setNoteSearch(event.target.value)} placeholder="搜索笔记名称" />
        </label>
        <div className="notes-directory">
          {loading && <div className="notes-empty">正在同步学习笔记…</div>}
          {!loading && !visibleNotes.length && <div className="notes-empty">暂无已生成的学习笔记</div>}
          {Object.entries(noteGroups).map(([month, monthNotes]) => (
            <section className="notes-month" key={month}>
              <h2>{month}</h2>
              {monthNotes.map((note) => (
                <button key={note.id} className={selectedNote?.id === note.id ? 'active' : ''} onClick={() => openNote(note)}>
                  <span className="note-status-dot" />
                  <span><strong>{note.title}</strong><small>{formatDate(note.created_at)}</small></span>
                </button>
              ))}
            </section>
          ))}
        </div>
      </aside>

      <main className="learning-route-area note-only-main">
        {selectedNote ? (
          <article className="note-reader note-library-reader">
            <header className="note-reader-header">
              <div><span>NOTE METADATA</span><h2>{selectedNote.title || selectedNote.filename}</h2></div>
              <div className="note-metadata-grid">
                <span><small>时间</small><b>{formatDate(selectedNote.modified || selectedNote.created_at)}</b></span>
                <span><small>来源</small><b>{selectedNote.source || selectedNote.source_type || '本地生成笔记'}</b></span>
                <span><small>大小</small><b>{selectedNote.size ? `${selectedNote.size} B` : '—'}</b></span>
              </div>
            </header>
            <div className="note-reader-divider"><span /></div>
            <div className="note-reader-content">
              {noteLoading ? <div className="note-reader-loading">正在展开笔记…</div> : <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedNote.content || ''}</ReactMarkdown>}
            </div>
          </article>
        ) : (
          <section className="learning-empty-state"><span>✦</span><h2>选择一篇笔记开始阅读</h2><p>左侧目录保留原有的时间分组与搜索方式。</p></section>
        )}
        {error && <div className="learning-error">{error}</div>}
      </main>
    </div>
  );
}

export default LearningWorkspacePage;
