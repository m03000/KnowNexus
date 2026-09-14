import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './LearningWorkspacePage.css';

const ROOTS = ['wiki-root', 'personal-root', 'wiki-index', 'wiki-topics', 'wiki-concepts', 'wiki-syntheses', 'wiki-sources', 'ai-note-root', 'personal-document-root'];
const normalizeWikiLinks = (content = '') => content.replace(
  /\[\[([^\]|]+)\|([^\]]+)\]\]/g,
  (_, slug, title) => `[${title}](wiki://slug/${encodeURIComponent(slug)})`,
);
const LibraryIcon = ({ name, className = '' }) => {
  const common = { className: `library-icon ${className}`.trim(), viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: '1.8', strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true };
  if (name === 'chevron') return <svg {...common}><path d="m9 7 5 5-5 5" /></svg>;
  if (name === 'folder') return <svg {...common}><path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h4l2 2h6A2.5 2.5 0 0 1 20.5 9.5v7A2.5 2.5 0 0 1 18 19H6a2.5 2.5 0 0 1-2.5-2.5z" /><path d="M3.5 9h17" /></svg>;
  if (name === 'upload') return <svg {...common}><path d="M12 15V4" /><path d="m8 8 4-4 4 4" /><path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" /></svg>;
  if (name === 'folder-plus') return <svg {...common}><path d="M3.5 8A2.5 2.5 0 0 1 6 5.5h4l2 2h6A2.5 2.5 0 0 1 20.5 10v6A2.5 2.5 0 0 1 18 18.5H6A2.5 2.5 0 0 1 3.5 16z" /><path d="M12 10.5v5M9.5 13h5" /></svg>;
  if (name === 'trash') return <svg {...common}><path d="M4.5 7h15M9 7V4.5h6V7M7 7l.7 12h8.6L17 7M10 10.5v5M14 10.5v5" /></svg>;
  return null;
};
const formatDate = (value) => {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString('zh-CN');
};
const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));
const storedWidth = (key, fallback) => {
  const value = Number(window.localStorage.getItem(key));
  return Number.isFinite(value) && value > 0 ? value : fallback;
};
const renderOutlineTitle = (value = '') => value
  .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
  .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
  .replace(/(?:\*\*|__|~~|`)/g, '')
  .replace(/\\([*_`~])/g, '$1')
  .trim();

function LibraryWorkspacePage({ apiBase = '', openDocumentRequest = null, onOpenDocumentRequestHandled = null }) {
  const [library, setLibrary] = useState({ folders: [], notes: [], documents: [], wikiPages: [] });
  const [expanded, setExpanded] = useState(() => new Set(ROOTS));
  const [selected, setSelected] = useState(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [contentLoading, setContentLoading] = useState(false);
  const [error, setError] = useState('');
  const [draft, setDraft] = useState('');
  const [editorMode, setEditorMode] = useState('split');
  const [saveState, setSaveState] = useState('saved');
  const [notice, setNotice] = useState('');
  const [knowledgePrompt, setKnowledgePrompt] = useState(null);
  const [wikiVersions, setWikiVersions] = useState([]);
  const [showWikiVersions, setShowWikiVersions] = useState(false);
  const [tabs, setTabs] = useState([]);
  const [folderMenu, setFolderMenu] = useState(null);
  const [createDialog, setCreateDialog] = useState(null);
  const [deleteItemDialog, setDeleteItemDialog] = useState(null);
  const [wikiConfig, setWikiConfig] = useState({ vault_path: '', enabled: false });
  const sidebarCollapsed = false;
  const [sidebarWidth, setSidebarWidth] = useState(() => storedWidth('personal-agent:library-sidebar-width', 310));
  const [outlineWidth, setOutlineWidth] = useState(() => storedWidth('personal-agent:note-outline-width', 300));
  const lastSaved = useRef('');
  const editorRef = useRef(null);
  const previewRef = useRef(null);
  const uploadRef = useRef(null);
  const uploadFolderRef = useRef('personal-document-root');
  const handledOpenRequestRef = useRef(null);

  const request = useCallback(async (path, options) => {
    const response = await fetch(`${apiBase}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || `请求失败（${response.status}）`);
    return data;
  }, [apiBase]);
  const refresh = useCallback(async () => {
    const [tree, wiki] = await Promise.all([
      request('/api/library/notes/tree'), request('/api/library/wiki/tree'),
    ]);
    const personalRoot = { folder_id: 'personal-document-root', parent_id: null, name: '个人文档', library_type: 'personal_document', is_system: true, sort_order: 1 };
    const personalFolders = tree.folders.filter((folder) => folder.folder_id !== 'personal-document-root').map((folder) => ({
      ...folder,
      parent_id: folder.folder_id === 'ai-note-root' ? 'personal-document-root' : folder.parent_id,
    }));
    setLibrary({ ...tree, folders: [...wiki.folders, personalRoot, ...personalFolders], wikiPages: wiki.items });
  }, [request]);

  useEffect(() => {
    let cancelled = false;
    refresh().catch((cause) => !cancelled && setError(cause.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [refresh]);
  useEffect(() => { request('/api/settings/obsidian-wiki').then(setWikiConfig).catch(() => {}); }, [request]);
  useEffect(() => {
    const close = () => setFolderMenu(null);
    window.addEventListener('pointerdown', close);
    window.addEventListener('blur', close);
    return () => { window.removeEventListener('pointerdown', close); window.removeEventListener('blur', close); };
  }, []);

  useEffect(() => {
    window.localStorage.setItem('personal-agent:library-sidebar-width', String(sidebarWidth));
  }, [sidebarWidth]);
  useEffect(() => {
    window.localStorage.setItem('personal-agent:note-outline-width', String(outlineWidth));
  }, [outlineWidth]);

  const startResize = (kind, event) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = kind === 'sidebar' ? sidebarWidth : outlineWidth;
    const onMove = (moveEvent) => {
      if (kind === 'sidebar') setSidebarWidth(clamp(startWidth + moveEvent.clientX - startX, 240, 500));
      else setOutlineWidth(clamp(startWidth + startX - moveEvent.clientX, 210, 520));
    };
    const finish = () => {
      document.body.classList.remove('library-column-resizing');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
    };
    document.body.classList.add('library-column-resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', finish, { once: true });
    window.addEventListener('pointercancel', finish, { once: true });
  };

  const foldersByParent = useMemo(() => library.folders.reduce((map, folder) => {
    (map[folder.parent_id || 'root'] ||= []).push(folder); return map;
  }, {}), [library.folders]);
  const itemsByFolder = useMemo(() => [...library.notes, ...library.documents].reduce((map, item) => {
    (map[item.folder_id] ||= []).push(item); return map;
  }, library.wikiPages.reduce((map, item) => { (map[item.folder_id] ||= []).push(item); return map; }, {})), [library]);
  const filteredItems = (folderId) => {
    const keyword = search.trim().toLowerCase();
    return (itemsByFolder[folderId] || []).filter((item) =>
      !keyword || (item.title || item.name || item.filename || '').toLowerCase().includes(keyword));
  };
  const toggleFolder = (folderId) => setExpanded((current) => {
    const next = new Set(current); next.has(folderId) ? next.delete(folderId) : next.add(folderId); return next;
  });

  const openItem = async (item) => {
    setError('');
    if (selected?.editable && selected.item_id !== item.item_id && draft !== lastSaved.current) {
      const saved = await saveDraft(draft, selected);
      if (!saved) return;
    }
    if (item.item_type === 'wiki') {
      setContentLoading(true);
      try {
        const data = await request(`/api/library/wiki/pages/${encodeURIComponent(item.page_id)}`);
        const next = { ...item, ...data, title: data.canonical_title, editable: false };
        setSelected(next); setDraft(data.body_markdown || ''); lastSaved.current = data.body_markdown || '';
        setTabs((current) => current.some((tab) => tab.item_id === item.item_id) ? current : [...current, next]);
        setEditorMode('preview');
        setShowWikiVersions(false); setWikiVersions([]);
      } catch (cause) { setError(cause.message); }
      finally { setContentLoading(false); }
      return;
    }
    if (item.item_type === 'document') {
      if (item.editable) {
        setContentLoading(true);
        try {
          const data = await request(`/api/library/notes/documents/${item.document_id}/content`);
          const next = { ...item, ...data, previewUrl: `${apiBase}/api/library/notes/documents/${item.document_id}` };
          setSelected(next); setDraft(data.content || ''); lastSaved.current = data.content || '';
          setTabs((current) => current.some((tab) => tab.item_id === item.item_id) ? current : [...current, next]);
        } finally { setContentLoading(false); }
      } else {
        const next = { ...item, previewUrl: `${apiBase}/api/library/notes/documents/${item.document_id}` };
        setSelected(next); setTabs((current) => current.some((tab) => tab.item_id === item.item_id) ? current : [...current, next]);
      }
      return;
    }
    setContentLoading(true);
    try {
      const data = await request(`/api/library/notes/${encodeURIComponent(item.filename)}`);
      const next = { ...item, ...data, editable: true };
      setSelected(next); setDraft(data.content || ''); lastSaved.current = data.content || '';
      setTabs((current) => current.some((tab) => tab.item_id === item.item_id) ? current : [...current, next]);
    } catch (cause) { setError(cause.message); }
    finally { setContentLoading(false); }
  };

  useEffect(() => {
    if (loading || (!openDocumentRequest?.documentId && !openDocumentRequest?.pageId && !openDocumentRequest?.filename)) return;
    if (handledOpenRequestRef.current === openDocumentRequest.requestId) return;
    if (openDocumentRequest.pageId) {
      const page = library.wikiPages.find((item) => item.page_id === openDocumentRequest.pageId);
      handledOpenRequestRef.current = openDocumentRequest.requestId;
      if (!page) setError('图谱关联的 Wiki 页面不存在，可能已在增量构建中删除。');
      else {
        setSidebarCollapsed(false);
        setExpanded((current) => new Set([...current, 'wiki-root', page.folder_id]));
        openItem(page).finally(() => onOpenDocumentRequestHandled?.());
        return;
      }
      onOpenDocumentRequestHandled?.();
      return;
    }
    if (openDocumentRequest.filename) {
      const note = library.notes.find((item) => item.filename === openDocumentRequest.filename);
      handledOpenRequestRef.current = openDocumentRequest.requestId;
      if (!note) setError('图谱关联的笔记不存在，可能已经被删除。');
      else {
        setSidebarCollapsed(false);
        setExpanded((current) => new Set([...current, 'ai-note-root', note.folder_id]));
        openItem(note).finally(() => onOpenDocumentRequestHandled?.());
        return;
      }
      onOpenDocumentRequestHandled?.();
      return;
    }
    const document = library.documents.find((item) => item.document_id === openDocumentRequest.documentId);
    if (!document) {
      setError('图谱关联的个人文档不存在，可能已被解除关联。');
      handledOpenRequestRef.current = openDocumentRequest.requestId;
      onOpenDocumentRequestHandled?.();
      return;
    }
    handledOpenRequestRef.current = openDocumentRequest.requestId;
    const folderIds = new Set(['personal-document-root', document.folder_id]);
    let parentId = document.folder_id;
    while (parentId) {
      const folder = library.folders.find((item) => item.folder_id === parentId);
      if (!folder?.parent_id) break;
      folderIds.add(folder.parent_id);
      parentId = folder.parent_id;
    }
    setSidebarCollapsed(false);
    setExpanded((current) => new Set([...current, ...folderIds]));
    openItem(document).finally(() => onOpenDocumentRequestHandled?.());
  }, [loading, library.documents, library.folders, library.notes, library.wikiPages, openDocumentRequest, onOpenDocumentRequestHandled]);
  const createMarkdown = async (folder, title) => {
    try {
      const endpoint = folder.library_type === 'ai_note' ? '/api/library/notes/manual' : '/api/library/notes/documents/markdown';
      const item = await request(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.trim(), folder_id: folder.folder_id }) });
      setExpanded((current) => new Set([...current, folder.folder_id]));
      await refresh();
      await openItem(folder.library_type === 'ai_note'
        ? { ...item, filename: item.filename, library_type: 'ai_note', editable: true }
        : { ...item, library_type: 'personal_document' });
      return true;
    } catch (cause) { setError(cause.message); return false; }
  };

  const saveDraft = useCallback(async (content = draft, item = selected) => {
      if (!item?.editable || content === lastSaved.current) return true;
      setSaveState('saving');
      const path = item.item_type === 'note'
        ? `/api/library/notes/${encodeURIComponent(item.filename)}`
        : `/api/library/notes/documents/${item.document_id}/content`;
      try {
        await request(path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }) });
        lastSaved.current = content; setSaveState('saved');
        localStorage.removeItem(`personal-agent:editor-recovery:${item.item_id}`);
        return true;
      } catch (cause) {
        setSaveState('error'); setError(cause.message);
        localStorage.setItem(`personal-agent:editor-recovery:${item.item_id}`, content);
        return false;
      }
  }, [draft, request, selected]);

  const closeTab = async (event, tab) => {
    event.preventDefault();
    event.stopPropagation();
    if (selected?.item_id === tab.item_id && selected.editable && draft !== lastSaved.current) {
      const saved = await saveDraft(draft, selected);
      if (!saved) return;
    }
    const tabIndex = tabs.findIndex((candidate) => candidate.item_id === tab.item_id);
    const remaining = tabs.filter((candidate) => candidate.item_id !== tab.item_id);
    setTabs(remaining);
    if (selected?.item_id !== tab.item_id) return;
    const next = remaining[Math.min(tabIndex, remaining.length - 1)];
    if (next) await openItem(next);
    else {
      setSelected(null); setDraft(''); lastSaved.current = ''; setSaveState('saved');
    }
  };

  const toggleWikiVersions = async () => {
    if (!selected?.page_id || selected.page_id === 'index') return;
    if (showWikiVersions) { setShowWikiVersions(false); return; }
    try {
      setWikiVersions(await request(`/api/library/wiki/pages/${encodeURIComponent(selected.page_id)}/versions`));
      setShowWikiVersions(true);
    } catch (cause) { setError(cause.message); }
  };
  const rollbackWiki = async (version) => {
    if (!window.confirm(`将“${selected.canonical_title}”恢复到 v${version}？当前版本仍会保留在历史中。`)) return;
    try {
      const restored = await request(`/api/library/wiki/pages/${encodeURIComponent(selected.page_id)}/rollback`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ version }),
      });
      const next = { ...selected, ...restored };
      setSelected(next); setDraft(restored.body_markdown || ''); lastSaved.current = restored.body_markdown || '';
      setTabs((current) => current.map((tab) => tab.item_id === next.item_id ? next : tab));
      setShowWikiVersions(false); setNotice(`已恢复为历史版本 v${version}，当前生成 v${restored.version}。`);
    } catch (cause) { setError(cause.message); }
  };

  useEffect(() => {
    if (!selected?.editable || draft === lastSaved.current) return undefined;
    setSaveState('dirty');
    const timer = window.setTimeout(() => {
      saveDraft(draft, selected);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [draft, saveDraft, selected]);

  useEffect(() => {
    const save = (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); saveDraft(); }
    };
    window.addEventListener('keydown', save); return () => window.removeEventListener('keydown', save);
  }, [saveDraft]);

  const jumpToLine = (item) => {
    const preview = previewRef.current;
    if (preview) {
      const renderedHeadings = [...preview.querySelectorAll('h1,h2,h3,h4,h5,h6')];
      const target = Number.isInteger(item.headingIndex)
        ? renderedHeadings[item.headingIndex]
        : [...preview.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li')]
          .find((element) => element.textContent.trim() === item.renderedTitle);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    const textarea = editorRef.current;
    if (textarea) {
      const start = draft.split('\n').slice(0, item.line).reduce((sum, value) => sum + value.length + 1, 0);
      textarea.focus(); textarea.setSelectionRange(start, start); textarea.scrollTop = Math.max(0, item.line * 26 - 80);
    }
  };

  const outline = useMemo(() => {
    const lines = draft.split('\n');
    let headingIndex = -1;
    const headings = lines.map((line, index) => {
      const match = line.match(/^(#{1,6})\s+(.+)/);
      if (!match) return null;
      headingIndex += 1;
      return { level: match[1].length, title: match[2], renderedTitle: renderOutlineTitle(match[2]), line: index, headingIndex };
    }).filter(Boolean);
    if (headings.length) return headings;
    return lines.map((line, index) => {
      const title = line.trim();
      const isSection = /^[\u4e00-\u9fa5]{1,3}[\u3001．.]\s*/.test(title) || /^\d+[.、)]\s*/.test(title);
      const isQuestion = title.length <= 72 && /[？?]$/.test(title);
      return title && (isSection || isQuestion) ? { level: isSection ? 1 : 2, title, renderedTitle: renderOutlineTitle(title), line: index } : null;
    }).filter(Boolean).slice(0, 80);
  }, [draft]);
  const openSource = (href) => {
    if (href?.startsWith('wiki://page/')) {
      const pageId = decodeURIComponent(href.slice('wiki://page/'.length));
      const page = library.wikiPages.find((item) => item.page_id === pageId);
      if (page) openItem(page);
      return Boolean(page);
    }
    if (href?.startsWith('wiki://slug/')) {
      const slug = decodeURIComponent(href.slice('wiki://slug/'.length));
      const page = library.wikiPages.find((item) => item.slug === slug);
      if (page) openItem(page);
      return Boolean(page);
    }
    if (href?.startsWith('document://')) {
      const documentId = decodeURIComponent(href.slice('document://'.length));
      const document = library.documents.find((item) => item.document_id === documentId);
      if (document) openItem(document);
      return Boolean(document);
    }
    if (href?.startsWith('note://')) {
      const filename = decodeURIComponent(href.slice('note://'.length));
      const note = library.notes.find((item) => item.filename === filename);
      if (note) openItem(note);
      return Boolean(note);
    }
    const match = href?.match(/\/documents\/([^/?#]+)/);
    const document = match && library.documents.find((item) => item.document_id === decodeURIComponent(match[1]));
    if (!document) return false;
    setExpanded((current) => new Set([...current, 'personal-document-root', 'source-files']));
    openItem(document); return true;
  };

  const createFolder = async (parentId, name) => {
    try {
      await request('/api/library/notes/folders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ parent_id: parentId, name: name.trim() }) });
      setExpanded((current) => new Set([...current, parentId])); await refresh();
      return true;
    } catch (cause) { setError(cause.message); return false; }
  };
  const submitCreateDialog = async (event) => {
    event.preventDefault();
    const pending = createDialog;
    const value = pending?.value?.trim();
    if (!pending || !value || pending.submitting) return;
    setCreateDialog((current) => ({ ...current, submitting: true }));
    const created = pending.kind === 'markdown'
      ? await createMarkdown(pending.folder, value)
      : await createFolder(pending.folder.folder_id, value);
    if (created) setCreateDialog(null);
    else setCreateDialog((current) => current ? ({ ...current, submitting: false }) : null);
  };
  const deleteFolder = async (folder) => {
    if (!window.confirm(`删除空目录“${folder.name}”？`)) return;
    try { await request(`/api/library/notes/folders/${folder.folder_id}`, { method: 'DELETE' }); await refresh(); }
    catch (cause) { setError(cause.message); }
  };
  const linkSourceDocument = async ({ sourcePath, name = '', mediaType = '' }, folderId) => {
    const document = await request('/api/library/notes/documents/link', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_path: sourcePath, name, media_type: mediaType, folder_id: folderId }),
    });
    setExpanded((current) => new Set([...current, 'personal-document-root', folderId]));
    setNotice('文件已关联并进入知识库，后续读写都会直接使用源文件。');
    setKnowledgePrompt({
      documentId: document.document_id,
      name: document.name || name || '该文档',
      status: 'pending',
      error: '',
    });
    await refresh();
  };
  const analyzeDocumentKnowledge = async () => {
    if (!knowledgePrompt?.documentId || knowledgePrompt.status === 'loading') return;
    setKnowledgePrompt((current) => ({ ...current, status: 'loading', error: '' }));
    try {
      const result = await request(`/api/library/notes/documents/${knowledgePrompt.documentId}/analyze-knowledge`, {
        method: 'POST',
      });
      const count = result.knowledge_point_count || 0;
      setNotice(count
        ? `已从“${knowledgePrompt.name}”提取 ${count} 个知识点并加入笔记图谱。`
        : `“${knowledgePrompt.name}”没有提取到满足质量要求的知识点。`);
      setKnowledgePrompt(null);
    } catch (cause) {
      setKnowledgePrompt((current) => ({ ...current, status: 'error', error: cause.message }));
    }
  };
  const chooseImport = async (folderId) => {
    uploadFolderRef.current = folderId;
    if (!window.desktopAPI?.pickFile) {
      uploadRef.current?.click();
      return;
    }
    try {
      const selectedFile = await window.desktopAPI.pickFile();
      if (selectedFile) await linkSourceDocument(selectedFile, folderId);
    } catch (cause) { setError(cause.message); }
  };
  const sourcePathForFile = async (file) => {
    const pathResolvers = [
      window.desktopAPI?.getPathForFile,
      window.electronAPI?.getPathForFile,
      window.webUtils?.getPathForFile,
    ].filter((resolver) => typeof resolver === 'function');
    for (const resolver of pathResolvers) {
      const resolved = await Promise.resolve(resolver(file));
      if (resolved) return resolved;
    }
    if (file.path) return file.path;
    return window.prompt(
      '当前浏览器出于安全限制不能读取源文件地址。请粘贴该文件的完整路径；打包为桌面端后会自动取得路径。',
      file.name,
    ) || '';
  };
  const importDocument = async (event) => {
    const file = event.target.files?.[0]; event.target.value = '';
    if (!file) return;
    try {
      const sourcePath = await sourcePathForFile(file);
      if (!sourcePath) throw new Error('浏览器无法取得源文件路径，请在桌面端导入文件。');
      await linkSourceDocument({ sourcePath, name: file.name, mediaType: file.type }, uploadFolderRef.current);
    }
    catch (cause) { setError(cause.message); }
  };
  const removeItem = (event, item) => {
    event.stopPropagation();
    const linked = item.item_type === 'document' && item.source_kind === 'linked';
    const label = item.title || item.name || item.filename;
    setDeleteItemDialog({ item, label, linked });
  };
  const confirmRemoveItem = async () => {
    if (!deleteItemDialog) return;
    const { item } = deleteItemDialog;
    try {
      const path = item.item_type === 'note'
        ? `/api/library/notes/${encodeURIComponent(item.filename)}`
        : `/api/library/notes/documents/${item.document_id}`;
      await request(path, { method: 'DELETE' });
      const remaining = tabs.filter((tab) => tab.item_id !== item.item_id);
      setTabs(remaining);
      if (selected?.item_id === item.item_id) {
        setSelected(null); setDraft(''); lastSaved.current = ''; setSaveState('saved');
      }
      await refresh();
      setDeleteItemDialog(null);
    } catch (cause) { setError(cause.message); }
  };
  const exportNote = async (exportFormat) => {
    if (selected?.item_type !== 'note') return;
    try {
      await saveDraft();
      const result = await request(`/api/library/notes/${encodeURIComponent(selected.filename)}/export`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ export_format: exportFormat }),
      });
      setNotice(`已导出到 ${result.path}`);
    } catch (cause) { setError(cause.message); }
  };
  const moveItem = async (event, folder) => {
    event.preventDefault();
    const raw = event.dataTransfer.getData('application/x-library-item');
    if (!raw) return;
    try {
      const item = JSON.parse(raw);
      if (item.library_type !== folder.library_type) throw new Error('AI 笔记与个人文档之间不能互相移动');
      await request('/api/library/notes/items/move', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ item_type: item.item_type, item_id: item.item_id, folder_id: folder.folder_id }) });
      await refresh();
    } catch (cause) { setError(cause.message); }
  };

  const renderItem = (item, libraryType) => <div key={item.item_id} className="library-item-row">
    <button draggable={item.item_type !== 'wiki'} className={`library-item ${selected?.item_id === item.item_id ? 'active' : ''}`}
      onDragStart={(event) => event.dataTransfer.setData('application/x-library-item', JSON.stringify({ item_type: item.item_type, item_id: item.item_id, library_type: libraryType }))}
      onClick={() => openItem(item)}><span><strong>{item.title || item.name || item.filename}</strong>{item.item_type !== 'wiki' && <small>{formatDate(item.modified || item.modified_at || item.created_at)}</small>}</span></button>
    {item.item_type !== 'wiki' && <button type="button" className="library-item-delete" aria-label={`删除 ${item.title || item.name || item.filename}`} title={item.source_kind === 'linked' ? '解除关联' : '删除'} onClick={(event) => removeItem(event, item)}>×</button>}
  </div>;

  const renderFolder = (folder, depth = 0) => {
    const children = foldersByParent[folder.folder_id] || [];
    const items = filteredItems(folder.folder_id);
    const isOpen = expanded.has(folder.folder_id);
    const canManage = ['ai_note', 'personal_document'].includes(folder.library_type)
      && !['ai-note-root', 'source-files'].includes(folder.folder_id);
    return <section className={`library-folder depth-${depth}`} style={{ '--library-tree-depth': depth }} key={folder.folder_id} onDragOver={(event) => event.preventDefault()} onDrop={(event) => moveItem(event, folder)} onContextMenu={(event) => { if (!canManage) return; event.preventDefault(); setFolderMenu({ x: event.clientX, y: event.clientY, folder }); }}>
      <div className="library-folder-row"><button className={`folder-toggle ${isOpen ? 'open' : ''}`} aria-label={isOpen ? '收起目录' : '展开目录'} onClick={() => toggleFolder(folder.folder_id)}><LibraryIcon name="chevron" /></button>
        <button className="folder-name" onClick={() => toggleFolder(folder.folder_id)}><strong>{folder.name}</strong></button></div>
      {isOpen && <div className="library-folder-content">{children.map((child) => renderFolder(child, depth + 1))}{items.map((item) => renderItem(item, folder.library_type))}</div>}
    </section>;
  };

  return <div className={`learning-workspace library-workspace ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`} style={{ '--library-sidebar-width': `${sidebarCollapsed ? 52 : sidebarWidth}px` }}>
    {folderMenu && <div className="library-context-menu" style={{ left: folderMenu.x, top: folderMenu.y }} onPointerDown={(event) => event.stopPropagation()}>
      <button onClick={() => { setCreateDialog({ kind: 'markdown', folder: folderMenu.folder, value: '', submitting: false }); setFolderMenu(null); }}>＋ 新建 Markdown</button>
      <button onClick={() => { setCreateDialog({ kind: 'folder', folder: folderMenu.folder, value: '', submitting: false }); setFolderMenu(null); }}><LibraryIcon name="folder-plus" /> 新建目录</button>
      {folderMenu.folder.library_type === 'personal_document' && folderMenu.folder.folder_id !== 'source-files' && <button onClick={() => { chooseImport(folderMenu.folder.folder_id); setFolderMenu(null); }}><LibraryIcon name="upload" /> 上传文件</button>}
      {!folderMenu.folder.is_system && <><hr /><button className="danger" onClick={() => { deleteFolder(folderMenu.folder); setFolderMenu(null); }}><LibraryIcon name="trash" /> 删除目录</button></>}
    </div>}
    {createDialog && <div className="library-create-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !createDialog.submitting) setCreateDialog(null); }}>
      <form className="library-create-dialog" role="dialog" aria-modal="true" aria-labelledby="library-create-title" onSubmit={submitCreateDialog}>
        <header><div><strong id="library-create-title">{createDialog.kind === 'markdown' ? '新建 Markdown' : '新建目录'}</strong><small>位置：{createDialog.folder.name}</small></div><button type="button" aria-label="关闭" disabled={createDialog.submitting} onClick={() => setCreateDialog(null)}>×</button></header>
        <label><span>{createDialog.kind === 'markdown' ? '文件名' : '目录名'}</span><input autoFocus maxLength={createDialog.kind === 'markdown' ? 160 : 80} value={createDialog.value} onChange={(event) => setCreateDialog((current) => ({ ...current, value: event.target.value }))} placeholder={createDialog.kind === 'markdown' ? '例如：项目说明（可省略 .md）' : '例如：项目资料'} /></label>
        <footer><button type="button" className="secondary" disabled={createDialog.submitting} onClick={() => setCreateDialog(null)}>取消</button><button type="submit" className="primary" disabled={!createDialog.value.trim() || createDialog.submitting}>{createDialog.submitting ? '正在创建…' : '创建'}</button></footer>
      </form>
    </div>}
    {deleteItemDialog && <div className="library-delete-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteItemDialog(null); }}>
      <section className="library-delete-dialog" role="dialog" aria-modal="true" aria-labelledby="library-delete-title">
        <div className="library-delete-icon">×</div>
        <div><h2 id="library-delete-title">{deleteItemDialog.linked ? '解除文档关联？' : '删除这份文档？'}</h2><p>{deleteItemDialog.linked ? `将解除“${deleteItemDialog.label}”的关联并清理知识库索引，源文件不会被删除。` : `“${deleteItemDialog.label}”及其知识库索引将被删除，此操作无法撤销。`}</p></div>
        <footer><button type="button" onClick={() => setDeleteItemDialog(null)}>取消</button><button type="button" className="danger" onClick={confirmRemoveItem}>{deleteItemDialog.linked ? '解除关联' : '确认删除'}</button></footer>
      </section>
    </div>}
    <aside className="learning-notes-sidebar"><header className="learning-notes-header" aria-hidden="true" />
      {!sidebarCollapsed && <><div className="current-vault-path"><span>当前 Vault</span><strong title={wikiConfig.vault_path}>{wikiConfig.enabled ? wikiConfig.vault_path : '内置 Wiki'}</strong></div><label className="notes-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索笔记或文档" /></label>
      <input ref={uploadRef} type="file" hidden onChange={importDocument} accept=".pdf,.doc,.docx,.md,.txt,.rtf,.html,.htm,.png,.jpg,.jpeg" />
      <div className="notes-directory">{loading ? <div className="notes-empty">正在加载目录…</div> : (foldersByParent.root || []).map((folder) => renderFolder(folder))}</div>
      <div className="library-column-resizer sidebar-resizer" role="separator" aria-label="调整文件目录宽度" aria-orientation="vertical" onPointerDown={(event) => startResize('sidebar', event)} /></>}
    </aside>
    <main className="learning-route-area note-only-main note-editor-workspace">
      {tabs.length > 0 && <div className="note-editor-tabs">{tabs.map((tab) => <div key={tab.item_id} className={`note-editor-tab ${selected?.item_id === tab.item_id ? 'active' : ''}`}><button type="button" className="note-editor-tab-label" onClick={() => openItem(tab)}>{tab.title || tab.name || tab.filename}</button><button type="button" className="note-editor-tab-close" aria-label={`关闭 ${tab.title || tab.name || tab.filename}`} title="关闭" onMouseDown={(event) => event.stopPropagation()} onPointerDown={(event) => event.stopPropagation()} onClick={(event) => closeTab(event, tab)}>×</button></div>)}</div>}
      {selected?.editable ? <div className="note-editor-layout" style={{ '--note-outline-width': `${outlineWidth}px` }}>
        <section className="note-editor-stage"><header><div><strong>{selected.title || selected.name || selected.filename}</strong><small>{saveState === 'saving' ? '正在保存…' : saveState === 'dirty' ? '未保存' : saveState === 'error' ? '保存失败' : '已保存'}</small></div><nav><button type="button" className="note-save-button" disabled={saveState === 'saving' || (saveState === 'saved' && draft === lastSaved.current)} onClick={() => saveDraft()}>保存</button>{selected.item_type === 'note' && <><button type="button" onClick={() => exportNote('md')}>导出 MD</button><button type="button" onClick={() => exportNote('docx')}>导出 DOCX</button></>}{['edit', 'split', 'preview'].map((mode) => <button key={mode} className={editorMode === mode ? 'active' : ''} onClick={() => setEditorMode(mode)}>{mode === 'edit' ? '编辑' : mode === 'split' ? '分栏' : '预览'}</button>)}</nav></header>
          <div className={`note-editor-body mode-${editorMode}`}>{editorMode !== 'preview' && <textarea ref={editorRef} className="note-source-editor" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck="false" />}{editorMode !== 'edit' && <article ref={previewRef} className="note-live-preview"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ href, children, ...props }) => <a href={href} {...props} onClick={(event) => { if (openSource(href)) event.preventDefault(); }}>{children}</a> }}>{draft}</ReactMarkdown></article>}</div>
        </section>
        <aside className="note-outline"><div className="library-column-resizer outline-resizer" role="separator" aria-label="调整文章目录宽度" aria-orientation="vertical" onPointerDown={(event) => startResize('outline', event)} /><header>本文目录</header>{outline.length ? outline.map((item) => <button key={`${item.line}-${item.title}`} style={{ paddingLeft: `${12 + (item.level - 1) * 12}px` }} onClick={() => jumpToLine(item)}>{item.renderedTitle}</button>) : <p>添加标题后，这里会实时生成目录。</p>}</aside></div>
        : selected?.item_type === 'wiki' ? <div className="note-editor-layout wiki-reader-layout" style={{ '--note-outline-width': `${outlineWidth}px` }}>
          <section className="note-editor-stage"><header><div><strong>{selected.canonical_title}</strong><small>{selected.page_type === 'index' ? '索引页' : `Wiki · v${selected.version}`}</small></div>{selected.page_id !== 'index' && <nav><button type="button" onClick={toggleWikiVersions}>版本历史</button></nav>}</header><div className="note-editor-body mode-preview"><article ref={previewRef} className="note-live-preview"><ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(url) => url} components={{ a: ({ href, children, ...props }) => <a href={href} {...props} onClick={(event) => { if (openSource(href)) event.preventDefault(); }}>{children}</a> }}>{normalizeWikiLinks(draft)}</ReactMarkdown></article></div>{showWikiVersions && <aside className="wiki-version-panel"><header><strong>版本历史</strong><button type="button" onClick={() => setShowWikiVersions(false)}>×</button></header>{wikiVersions.length ? wikiVersions.map((version) => <button type="button" key={version.version} onClick={() => rollbackWiki(version.version)}><span>v{version.version}</span><small>{formatDate(version.created_at)}</small><em>恢复</em></button>) : <p>暂无可回滚的历史版本。</p>}</aside>}</section>
          <aside className="note-outline"><div className="library-column-resizer outline-resizer" role="separator" aria-label="调整文章目录宽度" aria-orientation="vertical" onPointerDown={(event) => startResize('outline', event)} /><header>Wiki 目录</header>{outline.map((item) => <button key={`${item.line}-${item.title}`} style={{ paddingLeft: `${12 + (item.level - 1) * 12}px` }} onClick={() => jumpToLine(item)}>{item.renderedTitle}</button>)}</aside>
        </div>
        : selected?.item_type === 'document' ? <section className="document-reader"><header><div><span>只读文档</span><h2>{selected.name}</h2></div><a href={selected.previewUrl} target="_blank" rel="noreferrer">在新窗口打开</a></header><iframe title={selected.name} src={selected.previewUrl} /></section>
          : <section className="learning-empty-state"><span>✦</span><h2>选择或新建一篇笔记</h2><p>文本文件、DOCX 与 AI 笔记可编辑，PDF、旧版 Office 文档和图片保持只读。</p></section>}
      {error && <div className="learning-error">{error}<button onClick={() => setError('')}>×</button></div>}
      {notice && <div className="learning-notice">{notice}<button onClick={() => setNotice('')}>×</button></div>}
      {knowledgePrompt && <section className="document-knowledge-prompt" role="dialog" aria-label="分析文档知识点">
        <div className="document-knowledge-prompt-icon">✦</div>
        <div className="document-knowledge-prompt-copy">
          <strong>是否分析这份文档的知识点？</strong>
          <p>“{knowledgePrompt.name}”已进入个人知识库。确认后会调用当前 LLM 提炼核心知识点，并关联到笔记图谱；原文不会被修改。</p>
          {knowledgePrompt.error && <small>{knowledgePrompt.error}</small>}
        </div>
        <div className="document-knowledge-prompt-actions">
          <button type="button" className="secondary" disabled={knowledgePrompt.status === 'loading'} onClick={() => setKnowledgePrompt(null)}>暂不分析</button>
          <button type="button" className="primary" disabled={knowledgePrompt.status === 'loading'} onClick={analyzeDocumentKnowledge}>{knowledgePrompt.status === 'loading' ? '正在分析…' : '分析知识点'}</button>
        </div>
      </section>}
    </main>
  </div>;
}

export default LibraryWorkspacePage;
