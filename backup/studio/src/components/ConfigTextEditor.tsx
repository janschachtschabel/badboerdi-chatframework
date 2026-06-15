'use client';

import { useState, useEffect, useCallback } from 'react';

interface FileEntry {
  label: string;
  desc: string;
  path: string;
}

interface Props {
  title: string;
  subtitle: string;
  files: FileEntry[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
}

/**
 * ConfigTextEditor: Layer 1 (Identity) and Layer 2 (Domain) editor.
 * Shows labeled file sections with description, text editor, and save.
 */
export default function ConfigTextEditor({ title, subtitle, files, loadFile, saveFile }: Props) {
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [loading, setLoading] = useState(false);

  const isDirty = content !== originalContent;

  const load = useCallback(async (idx: number) => {
    setLoading(true);
    const text = await loadFile(files[idx].path);
    setContent(text);
    setOriginalContent(text);
    setStatus('idle');
    setLoading(false);
  }, [files, loadFile]);

  useEffect(() => {
    load(selectedIdx);
  }, [selectedIdx, load]);

  const handleSave = async () => {
    setStatus('saving');
    const ok = await saveFile(files[selectedIdx].path, content);
    if (ok) {
      setOriginalContent(content);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 's' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (isDirty) handleSave();
    }
    // Tab support
    if (e.key === 'Tab') {
      e.preventDefault();
      const ta = e.target as HTMLTextAreaElement;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const newContent = content.substring(0, start) + '  ' + content.substring(end);
      setContent(newContent);
      setTimeout(() => { ta.selectionStart = ta.selectionEnd = start + 2; }, 0);
    }
  };

  return (
    <div>
      {/* Page header */}
      <div className="page-header">
        <div className="page-title">{title}</div>
        <div className="page-subtitle">{subtitle}</div>
      </div>

      {/* File tabs */}
      <div className="tabs">
        {files.map((f, i) => (
          <button
            key={f.path}
            className={`tab ${selectedIdx === i ? 'active' : ''}`}
            onClick={() => {
              if (isDirty && !confirm('Ungespeicherte Änderungen verwerfen?')) return;
              setSelectedIdx(i);
            }}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* File info */}
      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: '.9rem' }}>{files[selectedIdx].label}</div>
            <div style={{ fontSize: '.78rem', color: 'var(--text-muted)' }}>{files[selectedIdx].desc}</div>
            <div className="text-xs text-muted font-mono mt-2">{files[selectedIdx].path}</div>
          </div>
          <div className="btn-group">
            {isDirty && <span className="save-status dirty">Ungespeichert</span>}
            {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
            {status === 'error' && <span className="save-status error">Fehler</span>}
            <button
              className="btn btn-primary btn-sm"
              onClick={handleSave}
              disabled={!isDirty || status === 'saving'}
            >
              {status === 'saving' ? 'Speichert...' : 'Speichern'}
            </button>
          </div>
        </div>
      </div>

      {/* Editor */}
      {loading ? (
        <div className="empty-state">
          <div className="empty-state-text">Laden...</div>
        </div>
      ) : (
        <textarea
          className="form-textarea"
          style={{ minHeight: 'calc(100vh - 320px)', fontFamily: "'SF Mono', 'Fira Code', monospace", fontSize: '.82rem' }}
          value={content}
          onChange={e => setContent(e.target.value)}
          onKeyDown={handleKeyDown}
          spellCheck={false}
        />
      )}
    </div>
  );
}
