import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './CodeInsightPage.css';

const ROW_HEIGHT = 34;

const languageIcon = (fileName) => {
  const extension = fileName.split('.').pop()?.toLowerCase();
  if (extension === 'py') return 'PY';
  if (['js', 'jsx'].includes(extension)) return 'JS';
  if (['ts', 'tsx'].includes(extension)) return 'TS';
  if (extension === 'json') return '{}';
  if (extension === 'md') return 'MD';
  return '<>';
};

const buildTree = (files) => {
  const root = { name: 'root', type: 'folder', children: new Map() };
  files.forEach((file) => {
    const parts = file.path.replaceAll('\\', '/').split('/').filter(Boolean);
    let cursor = root;
    parts.forEach((part, index) => {
      if (!cursor.children.has(part)) {
        cursor.children.set(part, index === parts.length - 1
          ? { name: part, type: 'file', file }
          : { name: part, type: 'folder', children: new Map() });
      }
      cursor = cursor.children.get(part);
    });
  });
  return [...root.children.values()];
};

const relativePath = (filePath, projectPath) => {
  const normalizedFile = String(filePath || '').replaceAll('\\', '/');
  const normalizedRoot = String(projectPath || '').replaceAll('\\', '/').replace(/\/$/, '');
  if (normalizedRoot && normalizedFile.toLowerCase().startsWith(normalizedRoot.toLowerCase())) {
    return normalizedFile.slice(normalizedRoot.length).replace(/^\//, '');
  }
  const parts = normalizedFile.split('/');
  return parts.slice(Math.max(0, parts.length - 3)).join('/');
};

const filesFromApiTree = (tree, projectPath = '') => (
  (tree || []).flatMap((folder) => (folder.files || []).map((file) => ({
    path: file.relative_path || relativePath(file.file_path, projectPath) || file.file_name,
    apiPath: file.file_path,
    name: file.file_name,
    language: file.file_name?.endsWith('.py') ? 'Python' : 'Text',
    fileRole: file.file_role || '',
    symbols: (file.symbols || []).map((symbol) => ({
      ...symbol,
      type: symbol.type || symbol.symbol_type,
      kind: symbol.type || symbol.symbol_type,
    })),
  })))
);

const EMPTY_PROJECT = {
  id: null,
  root: '',
  name: '未选择项目',
  files: [],
  totalBlocks: 0,
};

function TreeNode({ node, depth, selectedPath, onFile, onSymbol }) {
  const [open, setOpen] = useState(true);
  if (node.type === 'folder') {
    return (
      <div className="ci-tree-group">
        <button className="ci-tree-row folder" style={{ '--depth': depth }} onClick={() => setOpen(!open)}>
          <span className="ci-chevron" aria-hidden="true">{open ? '−' : '+'}</span>
          <span className="ci-folder-icon">◇</span>
          <span>{node.name}</span>
        </button>
        {open && [...node.children.values()].map((child) => (
          <TreeNode
            key={`${child.type}-${child.name}`}
            node={child}
            depth={depth + 1}
            selectedPath={selectedPath}
            onFile={onFile}
            onSymbol={onSymbol}
          />
        ))}
      </div>
    );
  }

  const active = node.file.path === selectedPath;
  return (
    <div>
      <button
        className={`ci-tree-row file ${active ? 'active' : ''}`}
        style={{ '--depth': depth }}
        onClick={() => onFile(node.file)}
      >
        <span className={`ci-file-icon ${node.file.name.split('.').pop()}`}>{languageIcon(node.file.name)}</span>
        <span>{node.name}</span>
        {!!node.file.symbols?.length && <small>{node.file.symbols.length}</small>}
      </button>
      {active && node.file.symbols?.map((symbol) => (
        <button
          key={`${symbol.name}-${symbol.start_line}`}
          className="ci-tree-row symbol"
          style={{ '--depth': depth + 1 }}
          onClick={() => onSymbol(symbol)}
        >
          <span className={symbol.kind === 'class' ? 'ci-symbol-class' : 'ci-symbol-method'}>
            {symbol.kind === 'class' ? 'C' : 'ƒ'}
          </span>
          <span>{symbol.parent_class ? `${symbol.parent_class}.${symbol.name}` : symbol.name}</span>
          <small>L{symbol.start_line}</small>
        </button>
      ))}
    </div>
  );
}

function CodeInsightPage({
  apiBase = '/api/library/code-projects',
  agentApi = '/api/agent/chat',
}) {
  const [projectPath, setProjectPath] = useState('');
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState(EMPTY_PROJECT);
  const [selectedFile, setSelectedFile] = useState(null);
  const [activeBlock, setActiveBlock] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('输入本地项目地址，或选择已有解析项目。');
  const [pendingDelete, setPendingDelete] = useState(null);
  const [isEditing, setIsEditing] = useState(false);
  const [draftCode, setDraftCode] = useState('');
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [sidebarWidth, setSidebarWidth] = useState(() => Number(localStorage.getItem('personal-agent:code-directory-width')) || 286);
  const sidebarResizeRef = useRef(null);
  const codeScrollRef = useRef(null);
  const explainScrollRef = useRef(null);

  useEffect(() => {
    localStorage.setItem('personal-agent:code-directory-width', String(sidebarWidth));
  }, [sidebarWidth]);
  useEffect(() => {
    const resize = (event) => {
      if (!sidebarResizeRef.current) return;
      const next = sidebarResizeRef.current.startWidth + event.clientX - sidebarResizeRef.current.startX;
      setSidebarWidth(Math.max(220, Math.min(520, next)));
    };
    const stop = () => { sidebarResizeRef.current = null; document.body.classList.remove('ci-directory-resizing'); };
    window.addEventListener('pointermove', resize);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
    return () => { window.removeEventListener('pointermove', resize); window.removeEventListener('pointerup', stop); window.removeEventListener('pointercancel', stop); };
  }, []);

  const tree = useMemo(() => buildTree(project.files || []), [project.files]);
  const codeLines = useMemo(() => (selectedFile?.content || '').split('\n'), [selectedFile]);
  const blocks = selectedFile?.blocks || [];

  const readResponse = async (response) => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || data.detail || `请求失败（${response.status}）`);
    return data;
  };

  const refreshProjects = async () => {
    try {
      const response = await fetch(apiBase);
      const data = await readResponse(response);
      setProjects((data.projects || []).map((item) => ({
        ...item,
        id: item.project_id,
      })));
    } catch {
      setProjects([]);
    }
  };

  useEffect(() => {
    refreshProjects();
  // API base is a stable application configuration.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

  const findBlockForLine = (line) => {
    const matches = blocks.filter((block) => line >= block.start_line && line <= block.end_line);
    if (matches.length) {
      return matches.sort((a, b) => (
        (a.end_line - a.start_line) - (b.end_line - b.start_line)
      ))[0];
    }
    return blocks.reduce((nearest, block) => (
      !nearest || Math.abs(block.start_line - line) < Math.abs(nearest.start_line - line)
        ? block
        : nearest
    ), null);
  };

  const focusBlock = (block, behavior = 'smooth') => {
    if (!block) return;
    setActiveBlock(block);
    codeScrollRef.current?.scrollTo({
      top: Math.max(0, (block.start_line - 2) * ROW_HEIGHT),
      behavior,
    });
    explainScrollRef.current?.scrollTo({ top: 0 });
  };

  const focusSymbol = (symbol) => {
    const exact = blocks.find((block) => (
      block.start_line === symbol.start_line
      && block.end_line === symbol.end_line
      && (block.label === symbol.name || block.type === symbol.type)
    ));
    focusBlock(exact || {
      label: symbol.name,
      type: symbol.type || symbol.kind,
      start_line: symbol.start_line,
      end_line: symbol.end_line,
      explanation: '',
    });
  };

  const openFile = async (file, projectOverride = project) => {
    setActiveBlock(null);
    setIsEditing(false);
    setShowSaveConfirm(false);
    if (file.content !== undefined && file.blocks) {
      setSelectedFile(file);
      setActiveBlock(file.blocks[0] || null);
      setDraftCode(file.content || '');
      requestAnimationFrame(() => {
        codeScrollRef.current?.scrollTo({ top: 0 });
        explainScrollRef.current?.scrollTo({ top: 0 });
      });
      return file;
    }

    if (!projectOverride.id) return null;
    setLoading(true);
    try {
      const response = await fetch(
        `${apiBase}/${projectOverride.id}/file?file_path=${encodeURIComponent(file.apiPath)}`,
      );
      const data = await readResponse(response);
      const nextFile = {
        ...file,
        name: data.file_name,
        apiPath: data.file_path,
        fileRole: data.file_role || file.fileRole,
        content: (data.source_lines || []).join('\n'),
        blocks: (data.blocks || []).map((block) => ({
          ...block,
          label: block.label || block.code_name,
          type: block.type || block.code_type,
          start_line: block.start_line || block.line_start,
          end_line: block.end_line || block.line_end,
        })),
      };
      setSelectedFile(nextFile);
      setActiveBlock(nextFile.blocks[0] || null);
      setDraftCode(nextFile.content);
      setProject((current) => ({
        ...current,
        files: current.files.map((item) => item.apiPath === nextFile.apiPath ? nextFile : item),
      }));
      setMessage('');
      requestAnimationFrame(() => {
        codeScrollRef.current?.scrollTo({ top: 0 });
        explainScrollRef.current?.scrollTo({ top: 0 });
      });
      return nextFile;
    } catch (error) {
      setMessage(`文件读取失败：${error.message}`);
      return null;
    } finally {
      setLoading(false);
    }
  };

  const loadProject = async (projectInfo) => {
    setLoading(true);
    setMessage('正在读取解析数据库中的项目结构…');
    try {
      const response = await fetch(`${apiBase}/${projectInfo.id}/tree`);
      const data = await readResponse(response);
      const files = filesFromApiTree(data.folders, projectInfo.project_path);
      const nextProject = {
        id: projectInfo.id,
        root: projectInfo.project_path || '',
        name: projectInfo.project_name,
        files,
        totalBlocks: projectInfo.total_blocks || 0,
      };
      setProject(nextProject);
      setProjectPath(projectInfo.project_path || '');
      setSelectedFile(null);
      if (files[0]) await openFile(files[0], nextProject);
      setMessage(`已载入“${projectInfo.project_name}”：${files.length} 个文件，${projectInfo.total_blocks || 0} 个解析块。`);
    } catch (error) {
      setMessage(`项目载入失败：${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const scanProject = async () => {
    if (!projectPath.trim()) {
      setMessage('请先输入项目绝对地址。');
      return;
    }
    setLoading(true);
    setMessage('代码解析 Agent 正在扫描项目并生成块级解析，这可能需要一些时间…');
    try {
      const normalized = projectPath.trim().replace(/[\\/]+$/, '');
      const projectName = normalized.split(/[\\/]/).pop() || 'code-project';
      const response = await fetch(agentApi, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: `code-page-${Date.now()}`,
          turn_id: globalThis.crypto?.randomUUID?.() || `code-${Date.now()}`,
          message: `请分析本地代码项目：${normalized}。完成项目代码解析并保存结果。`,
        }),
      });
      const result = await readResponse(response);
      await refreshProjects();
      setMessage(result.final_reply || `${projectName} 项目解析任务已完成，请从历史项目中打开结果。`);
    } catch (error) {
      setMessage(`项目解析失败：${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const deleteSelectedProject = async () => {
    if (!pendingDelete) return;
    setLoading(true);
    try {
      const response = await fetch(`${apiBase}/${pendingDelete.id}`, {
        method: 'DELETE',
      });
      await readResponse(response);
      const deletedCurrent = String(project.id) === String(pendingDelete.id);
      setPendingDelete(null);
      await refreshProjects();
      if (deletedCurrent) {
        setProject(EMPTY_PROJECT);
        setSelectedFile(null);
        setActiveBlock(null);
        setProjectPath('');
      }
      setMessage(`已删除“${pendingDelete.project_name}”的解析记录。`);
    } catch (error) {
      setMessage(`删除项目失败：${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const beginEditing = () => {
    if (!project.id || !selectedFile?.apiPath) return;
    setDraftCode(selectedFile.content || '');
    setIsEditing(true);
  };

  const cancelEditing = () => {
    setDraftCode(selectedFile?.content || '');
    setIsEditing(false);
    setShowSaveConfirm(false);
  };

  const saveSourceFile = async () => {
    if (!project.id || !selectedFile?.apiPath) return;
    setSaving(true);
    try {
      const response = await fetch(`${apiBase}/${project.id}/file`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: selectedFile.apiPath,
          content: draftCode,
        }),
      });
      const result = await readResponse(response);
      const nextFile = {
        ...selectedFile,
        content: draftCode,
        blocks: [],
        symbols: [],
      };
      setSelectedFile(nextFile);
      setProject((current) => ({
        ...current,
        files: current.files.map((file) => (
          file.apiPath === nextFile.apiPath ? nextFile : file
        )),
      }));
      setActiveBlock(null);
      setIsEditing(false);
      setShowSaveConfirm(false);
      setMessage(result.message || '源码已保存到本地文件，请重新解析和审查项目。');
    } catch (error) {
      setMessage(`源码保存失败：${error.message}`);
      setShowSaveConfirm(false);
    } finally {
      setSaving(false);
    }
  };

  const isInBlock = (line) => (
    activeBlock && line >= activeBlock.start_line && line <= activeBlock.end_line
  );

  return (
    <div className="code-insight-page">
      <header className="ci-topbar">
        <div className="ci-brand">
          <span className="ci-brand-mark">⌘</span>
          <div><h1>代码学习辅助</h1></div>
        </div>

        <div className="ci-path-control">
          <span className="ci-path-icon">⌁</span>
          <input
            value={projectPath}
            onChange={(event) => setProjectPath(event.target.value)}
            onKeyDown={(event) => { if (event.key === 'Enter') scanProject(); }}
            placeholder="输入本地项目绝对地址"
          />
          <button onClick={scanProject} disabled={loading}>{loading ? '解析中…' : '扫描并解析'}</button>
        </div>

      </header>

      <div className={`ci-workbench ${sidebarCollapsed ? 'project-sidebar-collapsed' : ''}`} style={{ '--ci-directory-width': `${sidebarWidth}px` }}>
        <aside className={`ci-project-panel ${sidebarCollapsed ? 'collapsed' : ''}`}>
          <div className="ci-panel-caption">
            <button className="chat-session-toggle" type="button" onClick={() => setSidebarCollapsed((value) => !value)} title={sidebarCollapsed ? '展开目录' : '收起目录'}>☰</button>
            {!sidebarCollapsed && <><div><strong>{project.name || '未选择项目'}</strong></div>
            <em>{project.files?.length || 0} 个文件 · {project.totalBlocks || 0} 个代码块</em></>}
          </div>

          {!sidebarCollapsed && !!projects.length && (
            <label className="ci-history-projects">
              <span>历史解析项目</span>
              <div className="ci-history-select-row">
                <select
                  value={project.id || ''}
                  onChange={(event) => {
                    const selected = projects.find((item) => String(item.id) === event.target.value);
                    if (selected) loadProject(selected);
                  }}
                >
                  <option value="">选择数据库中的项目</option>
                  {projects.map((item) => (
                    <option value={item.id} key={item.id}>
                      {item.project_name} · {item.total_blocks} 块
                      {item.status === 'stale' ? ' · 待更新' : ''}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="ci-delete-project"
                  title="删除当前历史项目"
                  disabled={!projects.some((item) => String(item.id) === String(project.id))}
                  onClick={() => {
                    const selected = projects.find((item) => String(item.id) === String(project.id));
                    if (selected) setPendingDelete(selected);
                  }}
                >
                  删除
                </button>
              </div>
            </label>
          )}

          {!sidebarCollapsed && <div className="ci-tree">
            {tree.map((node) => (
              <TreeNode
                key={`${node.type}-${node.name}`}
                node={node}
                depth={0}
                selectedPath={selectedFile?.path}
                onFile={openFile}
                onSymbol={focusSymbol}
              />
            ))}
            {!tree.length && <p className="ci-tree-empty">扫描项目后将在这里显示目录、文件、类与方法。</p>}
          </div>}

          {!sidebarCollapsed && <div className="ci-project-footer">
            <span><i className="online" /> 代码服务 :8001</span>
            <span><i className="online" /> 知识库服务 :8001</span>
          </div>}
          {!sidebarCollapsed && <div className="ci-directory-resizer" role="separator" aria-label="调整代码目录宽度" aria-orientation="vertical" onPointerDown={(event) => { event.preventDefault(); sidebarResizeRef.current = { startX: event.clientX, startWidth: sidebarWidth }; document.body.classList.add('ci-directory-resizing'); }} />}
        </aside>

        <main className="ci-editor-area">
          {selectedFile && <>
          <div className="ci-statusbar">
            <div className="ci-breadcrumb">
              <span>◇ {project.name}</span>
              {selectedFile?.path.split('/').map((part) => <span key={part}>› {part}</span>)}
              {selectedFile?.fileRole && <em>{selectedFile.fileRole}</em>}
            </div>
          </div>

          {message && <div className="ci-message"><span>{message}</span><button onClick={() => setMessage('')}>×</button></div>}

          <div className="ci-columns">
            <section className="ci-code-column">
              <header>
                <div><span className="ci-column-icon">&lt;/&gt;</span><strong>原始代码</strong></div>
                <div className="ci-editor-actions">
                  <small>{selectedFile?.language || '—'} · {codeLines[0] ? `${codeLines.length} 行` : '未选择文件'}</small>
                  {isEditing ? (
                    <>
                      <button type="button" onClick={cancelEditing}>取消</button>
                      <button type="button" className="primary" onClick={() => setShowSaveConfirm(true)}>保存</button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={beginEditing}
                      disabled={!project.id || !selectedFile?.apiPath}
                    >
                      编辑源码
                    </button>
                  )}
                </div>
              </header>
              {isEditing ? (
                <textarea
                  className="ci-source-editor"
                  value={draftCode}
                  onChange={(event) => setDraftCode(event.target.value)}
                  spellCheck="false"
                  aria-label="编辑当前 Python 源码"
                />
              ) : (
                <div className="ci-line-scroll code" ref={codeScrollRef}>
                  {selectedFile ? codeLines.map((code, index) => {
                  const line = index + 1;
                  const lineBlock = findBlockForLine(line);
                  return (
                    <div
                      key={line}
                      onClick={() => {
                        if (lineBlock) {
                          setActiveBlock(lineBlock);
                          explainScrollRef.current?.scrollTo({ top: 0 });
                        }
                      }}
                      className={[
                        'ci-code-line',
                        lineBlock ? 'selectable' : '',
                        isInBlock(line) ? 'in-block' : '',
                        activeBlock?.start_line === line ? 'block-start' : '',
                        activeBlock?.end_line === line ? 'block-end' : '',
                      ].join(' ')}
                    >
                      <span className="ci-line-number">{line}</span>
                      <code>{code || ' '}</code>
                    </div>
                  );
                }) : <div className="ci-editor-empty">请先扫描项目并选择一个文件</div>}
                </div>
              )}
            </section>

            <section className="ci-explain-column">
              <header>
                <div><span className="ci-column-icon explain">✦</span><strong>当前代码块解析</strong></div>
                <small>
                  {activeBlock
                    ? `${Math.max(1, blocks.indexOf(activeBlock) + 1)} / ${blocks.length}`
                    : (blocks.length ? '请选择代码块' : '等待解析 Agent')}
                </small>
              </header>
              <div
                className="ci-line-scroll explain ci-block-scroll"
                ref={explainScrollRef}
              >
                {activeBlock ? (
                  <article className="ci-block-card active ci-single-block-card">
                    <header>
                      <div>
                        <span className={`ci-block-type ${activeBlock.type}`}>{activeBlock.type}</span>
                        <strong>
                          {activeBlock.parent_class
                            ? `${activeBlock.parent_class}.${activeBlock.label}`
                            : activeBlock.label}
                        </strong>
                      </div>
                      <em>L{activeBlock.start_line}–L{activeBlock.end_line}</em>
                    </header>
                    {activeBlock.docstring && <p className="ci-block-docstring">{activeBlock.docstring}</p>}
                    <div className="ci-block-explanation">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {activeBlock.explanation || '该代码块尚未生成解析内容。'}
                      </ReactMarkdown>
                    </div>
                  </article>
                ) : (
                  <div className="ci-editor-empty">
                    {blocks.length
                      ? '点击左侧方法、类或原始代码行查看对应代码块解析'
                      : '解析数据库中的代码块将在这里显示'}
                  </div>
                )}
              </div>
            </section>
          </div>

          <footer className="ci-footerbar">
            <span>
              {activeBlock
                ? `当前代码块：${activeBlock.label} · L${activeBlock.start_line}–L${activeBlock.end_line}`
                : '点击目录节点或解析卡片可定位对应代码块'}
            </span>
            <span>UTF-8　LF　{selectedFile?.language || 'Plain Text'}</span>
          </footer>
          </>}

          {pendingDelete && (
            <div className="ci-confirm-backdrop" onMouseDown={() => setPendingDelete(null)}>
              <article className="ci-confirm-dialog" onMouseDown={(event) => event.stopPropagation()}>
                <span>删除解析记录</span>
                <h2>删除历史解析项目？</h2>
                <p>
                  将删除“{pendingDelete.project_name}”的代码解析和源码快照。
                  本地项目文件不会被删除。
                </p>
                <div>
                  <button type="button" onClick={() => setPendingDelete(null)}>取消</button>
                  <button type="button" className="danger" onClick={deleteSelectedProject}>确认删除</button>
                </div>
              </article>
            </div>
          )}

          {showSaveConfirm && (
            <div className="ci-confirm-backdrop" onMouseDown={() => setShowSaveConfirm(false)}>
              <article className="ci-confirm-dialog" onMouseDown={(event) => event.stopPropagation()}>
                <span>LOCAL FILE PERMISSION</span>
                <h2>保存到本地文件？</h2>
                <p>
                  这会授予本次操作修改当前本地文件的权限，并直接覆盖
                  “{selectedFile?.apiPath}”。保存后现有解析缓存将失效。
                </p>
                <div>
                  <button type="button" onClick={() => setShowSaveConfirm(false)} disabled={saving}>取消</button>
                  <button type="button" className="primary" onClick={saveSourceFile} disabled={saving}>
                    {saving ? '保存中…' : '确认并保存'}
                  </button>
                </div>
              </article>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

export default CodeInsightPage;
