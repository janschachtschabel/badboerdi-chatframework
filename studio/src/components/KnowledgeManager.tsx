'use client';

import { useState, useEffect, useRef, useCallback } from 'react';

interface RagArea {
  area: string;
  chunks: number;
  documents: number;
}

interface RagDoc {
  title: string;
  source: string;
  chunks: number;
  preview: string;
}

interface AreaConfig {
  mode: 'always' | 'on-demand';
  description: string;
}

interface McpServer {
  id: string;
  name: string;
  url: string;
  description: string;
  enabled: boolean;
  tools: string[];
}

/**
 * KnowledgeManager: Layer 5 - RAG knowledge areas + MCP server registry.
 */
export default function KnowledgeManager() {
  const [areas, setAreas] = useState<RagArea[]>([]);
  const [areaConfigs, setAreaConfigs] = useState<Record<string, AreaConfig>>({});
  const areaConfigsRef = useRef(areaConfigs);
  // Keep ref in sync so onBlur always has latest value
  useEffect(() => { areaConfigsRef.current = areaConfigs; }, [areaConfigs]);
  const [selectedArea, setSelectedArea] = useState<string | null>(null);
  const [docs, setDocs] = useState<RagDoc[]>([]);
  const [tab, setTab] = useState<'areas' | 'upload' | 'mcp'>('areas');

  // Upload state
  /** ID of the currently selected EXISTING area from the dropdown.
   *  Starts empty — the first-area-auto-select effect below syncs it
   *  once the areas list is loaded, so the dropdown value never drifts
   *  from what the user sees (critical: HTML <select> displays the
   *  first option when value doesn't match any option, but React state
   *  stays on the invalid value — classic silent-bug source). */
  const [uploadArea, setUploadArea] = useState('');
  /** True when "+ Neuer Wissensbereich" is chosen in the dropdown — the
   *  name is then taken from `newAreaName` below. */
  const [creatingNewArea, setCreatingNewArea] = useState(false);
  /** Free-text name for the new area, used when creatingNewArea is true. */
  const [newAreaName, setNewAreaName] = useState('');
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadUrl, setUploadUrl] = useState('');
  const [uploadText, setUploadText] = useState('');
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // MCP server state
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [mcpEditing, setMcpEditing] = useState<McpServer | null>(null);
  const [mcpDiscovering, setMcpDiscovering] = useState(false);
  const [mcpDiscoverUrl, setMcpDiscoverUrl] = useState('');
  const [mcpDiscoveredTools, setMcpDiscoveredTools] = useState<{ name: string; description: string }[]>([]);
  const [mcpStatus, setMcpStatus] = useState<string | null>(null);

  /** Speicherstatus der Bereichs-Konfig (Beschreibungstext + mode).
   *   - 'idle'    → nichts zu tun / letzter Save liegt lange zurueck
   *   - 'pending' → Aenderung vorliegend, Debounce laeuft
   *   - 'saving'  → PUT laeuft gerade
   *   - 'saved'   → letzter Save erfolgreich (wird nach ~1.8s wieder 'idle')
   *   - 'error'   → PUT fehlgeschlagen */
  const [saveStatus, setSaveStatus] = useState<'idle'|'pending'|'saving'|'saved'|'error'>('idle');

  // Viewer-Modal state (full chunks of a single document)
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerData, setViewerData] = useState<{
    title: string;
    source: string;
    area: string;
    chunk_count: number;
    total_chars: number;
    chunks: { index: number; content: string; created_at: string }[];
  } | null>(null);

  useEffect(() => { loadAreas(); loadAreaConfigs(); loadMcpServers(); }, []);

  /** Keep `uploadArea` in sync with the existing-areas list.
   *  Runs whenever `areas` changes:
   *    - Empty uploadArea + areas available → select the first one.
   *    - uploadArea no longer in the list → fall back to the first.
   *  Without this, <select value=...> can show an option that doesn't
   *  match React state (browser renders the first available option,
   *  but onChange never fires if the user just visually "confirms"
   *  the pre-filled choice). */
  useEffect(() => {
    if (areas.length === 0) return;
    const known = areas.some(a => a.area === uploadArea);
    if (!known) {
      setUploadArea(areas[0].area);
    }
  }, [areas, uploadArea]);

  // ── RAG Areas ──────────────────────────────────────────────

  const loadAreas = async () => {
    try {
      const resp = await fetch('/api/rag/areas');
      if (resp.ok) setAreas(await resp.json());
    } catch { /* ignore */ }
  };

  const loadAreaConfigs = async () => {
    try {
      const resp = await fetch('/api/config/file?path=05-knowledge/rag-config.yaml');
      if (resp.ok) {
        const data = await resp.json();
        const content = data.content || '';
        const configs: Record<string, AreaConfig> = {};
        let currentArea = '';
        let collectingDesc = false;
        let descLines: string[] = [];

        const flushDesc = () => {
          if (currentArea && descLines.length > 0) {
            configs[currentArea] = {
              ...configs[currentArea],
              description: descLines.join(' ').trim(),
            };
          }
          descLines = [];
          collectingDesc = false;
        };

        for (const line of content.split('\n')) {
          const trimmed = line.trim();
          if (trimmed.startsWith('# ') || trimmed === '') {
            // Blank line ends a block scalar continuation
            if (collectingDesc && descLines.length > 0) flushDesc();
            continue;
          }

          // Top-level key (area name) — no leading whitespace, ends with ':'
          if (!line.startsWith(' ') && !line.startsWith('\t') && trimmed.endsWith(':')) {
            flushDesc();
            const key = trimmed.slice(0, -1);
            if (key === 'areas') continue;
            currentArea = key;
            configs[currentArea] = { mode: 'on-demand', description: '' };
          } else if (currentArea && trimmed.startsWith('mode:')) {
            flushDesc();
            const val = trimmed.split(':')[1]?.trim().replace(/['"]/g, '');
            configs[currentArea] = { ...configs[currentArea], mode: val === 'always' ? 'always' : 'on-demand' };
          } else if (currentArea && trimmed.startsWith('description:')) {
            flushDesc();
            const afterColon = trimmed.split(':').slice(1).join(':').trim().replace(/['"]/g, '');
            if (afterColon === '>' || afterColon === '|') {
              // YAML block scalar — collect following indented lines
              collectingDesc = true;
            } else if (afterColon) {
              configs[currentArea] = { ...configs[currentArea], description: afterColon };
            } else {
              collectingDesc = true;
            }
          } else if (collectingDesc && (line.startsWith('  ') || line.startsWith('\t'))) {
            // Continuation line of block scalar description
            descLines.push(trimmed);
          } else if (collectingDesc) {
            flushDesc();
          }
        }
        flushDesc(); // flush last area's description

        setAreaConfigs(configs);
      }
    } catch { /* no config yet */ }
  };

  const saveAreaConfigs = async (configs: Record<string, AreaConfig>) => {
    const lines = ['# RAG-Bereichskonfiguration', '# mode: always = immer im Kontext, on-demand = nur bei Bedarf', ''];
    for (const [area, cfg] of Object.entries(configs)) {
      lines.push(`${area}:`);
      lines.push(`  mode: ${cfg.mode}`);
      if (cfg.description) {
        // Use YAML block scalar (>) for longer descriptions to preserve readability
        if (cfg.description.length > 80) {
          lines.push('  description: >');
          // Word-wrap at ~90 chars per line, indented by 4 spaces
          const words = cfg.description.split(/\s+/);
          let currentLine = '    ';
          for (const word of words) {
            if (currentLine.length + word.length + 1 > 95 && currentLine.trim()) {
              lines.push(currentLine.trimEnd());
              currentLine = '    ' + word;
            } else {
              currentLine += (currentLine.trim() ? ' ' : '') + word;
            }
          }
          if (currentLine.trim()) lines.push(currentLine.trimEnd());
        } else {
          lines.push(`  description: "${cfg.description}"`);
        }
      }
      lines.push('');
    }
    setSaveStatus('saving');
    try {
      const resp = await fetch('/api/config/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: '05-knowledge/rag-config.yaml', content: lines.join('\n'), file_type: 'yaml' }),
      });
      setSaveStatus(resp.ok ? 'saved' : 'error');
    } catch {
      setSaveStatus('error');
    }
    // Zeige "gespeichert" nur kurz, dann ausblenden
    setTimeout(() => setSaveStatus(prev => (prev === 'saved' ? 'idle' : prev)), 1800);
  };

  /** Debounced Auto-Save: speichert ~600ms nach der letzten Tipp-Pause.
   *  Damit gehen Eingaben nicht verloren, wenn der User das Feld NICHT
   *  explizit verlaesst (Tab schliessen, Browser-Crash). */
  const debouncedSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleAutoSave = useCallback((configs: Record<string, AreaConfig>) => {
    if (debouncedSaveRef.current) clearTimeout(debouncedSaveRef.current);
    setSaveStatus('pending');
    debouncedSaveRef.current = setTimeout(() => {
      void saveAreaConfigs(configs);
    }, 600);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Cleanup beim Unmount: Pending-Save sofort ausfuehren, damit nichts verloren geht
  useEffect(() => {
    return () => {
      if (debouncedSaveRef.current) {
        clearTimeout(debouncedSaveRef.current);
        // Direkter flush mit aktuellem ref
        void saveAreaConfigs(areaConfigsRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleAreaMode = async (area: string) => {
    const current = areaConfigs[area]?.mode || 'on-demand';
    const newMode = current === 'always' ? 'on-demand' : 'always';
    const updated = { ...areaConfigs, [area]: { ...areaConfigs[area] || { description: '' }, mode: newMode as 'always' | 'on-demand' } };
    setAreaConfigs(updated);
    await saveAreaConfigs(updated);
  };

  const loadDocs = async (area: string) => {
    setSelectedArea(area);
    try {
      const resp = await fetch(`/api/rag/area/${encodeURIComponent(area)}`);
      if (resp.ok) setDocs(await resp.json());
    } catch { /* ignore */ }
  };

  const removeOrphanArea = async (area: string) => {
    if (!confirm(`Konfig-Eintrag "${area}" entfernen? (enthaelt keine Dokumente)`)) return;
    const updated = { ...areaConfigs };
    delete updated[area];
    setAreaConfigs(updated);
    await saveAreaConfigs(updated);
  };

  const deleteArea = async (area: string) => {
    if (!confirm(`Wirklich alle Dokumente in "${area}" loeschen?`)) return;
    await fetch(`/api/rag/area/${encodeURIComponent(area)}`, { method: 'DELETE' });
    const updated = { ...areaConfigs };
    delete updated[area];
    setAreaConfigs(updated);
    await saveAreaConfigs(updated);
    await loadAreas();
    if (selectedArea === area) { setSelectedArea(null); setDocs([]); }
  };

  /** Open the viewer modal with ALL chunks of a single document. */
  const viewDoc = async (doc: RagDoc) => {
    if (!selectedArea) return;
    setViewerOpen(true);
    setViewerLoading(true);
    setViewerData(null);
    try {
      const params = new URLSearchParams({
        title: doc.title || '',
        source: doc.source || '',
      });
      const resp = await fetch(
        `/api/rag/area/${encodeURIComponent(selectedArea)}/doc?${params}`,
      );
      if (!resp.ok) {
        setViewerData({
          title: doc.title || '',
          source: doc.source || '',
          area: selectedArea,
          chunk_count: 0,
          total_chars: 0,
          chunks: [],
        });
        return;
      }
      setViewerData(await resp.json());
    } finally {
      setViewerLoading(false);
    }
  };

  const closeViewer = () => {
    setViewerOpen(false);
    setViewerData(null);
  };

  /** Delete a single document (all its chunks) from the currently selected
   *  area. Identified by its compound key (title + source). */
  const deleteDoc = async (doc: RagDoc) => {
    if (!selectedArea) return;
    const label = doc.title || '(ohne Titel)';
    if (!confirm(
      `Dokument "${label}" wirklich löschen?\n\n` +
      `Quelle: ${doc.source || '—'}\n` +
      `Chunks: ${doc.chunks}\n\n` +
      `Der Bereich "${selectedArea}" bleibt erhalten.`,
    )) return;
    const params = new URLSearchParams({
      title: doc.title || '',
      source: doc.source || '',
    });
    const resp = await fetch(
      `/api/rag/area/${encodeURIComponent(selectedArea)}/doc?${params}`,
      { method: 'DELETE' },
    );
    if (!resp.ok) {
      alert(`Löschen fehlgeschlagen: HTTP ${resp.status}`);
      return;
    }
    // Refresh docs + area counts (chunk total shrinks)
    await loadDocs(selectedArea);
    await loadAreas();
  };

  /** Resolve the effective area name for the current upload.
   *  Priority:
   *    1. A freshly-typed new name in `newAreaName` (wins if non-empty)
   *    2. The selected existing area in `uploadArea`
   *  This fail-safe rule means the user can always pick one of the two
   *  even if the dropdown state drifts (e.g. initial uploadArea 'general'
   *  that doesn't exist yet). */
  const effectiveAreaName = (): string => {
    const typed = newAreaName.trim();
    if (typed) return typed;
    return uploadArea.trim();
  };

  // Upload handlers
  const doUpload = async (method: 'file' | 'url' | 'text') => {
    const areaName = effectiveAreaName();
    // eslint-disable-next-line no-console
    console.log('[rag-upload] method=%s area=%s (selected=%s, newName=%s)',
      method, areaName, uploadArea, newAreaName);
    if (!areaName) {
      setUploadResult('Bitte einen Wissensbereich wählen oder einen neuen Namen eingeben.');
      return;
    }
    setUploading(true);
    setUploadResult(null);
    const form = new FormData();
    form.append('area', areaName);
    form.append('title', uploadTitle || 'Dokument');

    try {
      let endpoint = '';
      if (method === 'file') {
        const file = fileRef.current?.files?.[0];
        if (!file) { setUploading(false); return; }
        form.append('file', file);
        form.set('title', uploadTitle || file.name);
        endpoint = '/api/rag/ingest/file';
      } else if (method === 'url') {
        form.append('url', uploadUrl);
        form.set('title', uploadTitle || uploadUrl);
        endpoint = '/api/rag/ingest/url';
      } else {
        form.append('content', uploadText);
        form.set('title', uploadTitle || 'Manueller Eintrag');
        endpoint = '/api/rag/ingest/text';
      }

      // Large PDFs can take 60-120s to chunk + embed — use generous timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 180_000); // 3 min
      const resp = await fetch(endpoint, { method: 'POST', body: form, signal: controller.signal });
      clearTimeout(timeoutId);
      if (!resp.ok) throw new Error('Failed');
      const data = await resp.json();
      setUploadResult(`${data.chunks} Chunks erstellt`);

      if (!areaConfigs[areaName]) {
        const updated = { ...areaConfigs, [areaName]: { mode: 'on-demand' as const, description: '' } };
        setAreaConfigs(updated);
        await saveAreaConfigs(updated);
      }
      // Nach erfolgreichem Upload: den frisch erstellten Bereich im
      // Dropdown auswählen und das Neu-Name-Feld leeren, damit weitere
      // Uploads ohne erneutes Eintippen in denselben Bereich gehen.
      if (newAreaName.trim()) {
        setUploadArea(areaName);
        setNewAreaName('');
      }
      await loadAreas();
      setUploadTitle('');
      setUploadUrl('');
      setUploadText('');
    } catch {
      setUploadResult('Fehler beim Import');
    }
    setUploading(false);
  };

  // ── MCP Servers ─────────────────────────────────────────────

  const loadMcpServers = async () => {
    try {
      const resp = await fetch('/api/config/mcp-servers');
      if (resp.ok) setMcpServers(await resp.json());
    } catch { /* ignore */ }
  };

  const saveMcpServers = async (servers: McpServer[]) => {
    try {
      await fetch('/api/config/mcp-servers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ servers }),
      });
      setMcpServers(servers);
    } catch { /* ignore */ }
  };

  const toggleMcpServer = async (id: string) => {
    const updated = mcpServers.map(s =>
      s.id === id ? { ...s, enabled: !s.enabled } : s
    );
    await saveMcpServers(updated);
  };

  const deleteMcpServer = async (id: string) => {
    if (!confirm('MCP-Server wirklich entfernen?')) return;
    const updated = mcpServers.filter(s => s.id !== id);
    await saveMcpServers(updated);
  };

  const discoverTools = async () => {
    if (!mcpDiscoverUrl) return;
    setMcpDiscovering(true);
    setMcpStatus(null);
    setMcpDiscoveredTools([]);
    try {
      const resp = await fetch(`/api/config/mcp-servers/discover?url=${encodeURIComponent(mcpDiscoverUrl)}`, {
        method: 'POST',
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Verbindung fehlgeschlagen' }));
        setMcpStatus(err.detail || 'Fehler');
        setMcpDiscovering(false);
        return;
      }
      const data = await resp.json();
      setMcpDiscoveredTools(data.tools || []);
      setMcpStatus(`${data.tools?.length || 0} Tools gefunden`);
    } catch {
      setMcpStatus('Verbindungsfehler');
    }
    setMcpDiscovering(false);
  };

  const registerDiscoveredServer = async () => {
    if (!mcpEditing) return;
    const server: McpServer = {
      ...mcpEditing,
      tools: mcpDiscoveredTools.map(t => t.name),
    };
    const exists = mcpServers.find(s => s.id === server.id);
    const updated = exists
      ? mcpServers.map(s => s.id === server.id ? server : s)
      : [...mcpServers, server];
    await saveMcpServers(updated);
    setMcpEditing(null);
    setMcpDiscoveredTools([]);
    setMcpDiscoverUrl('');
    setMcpStatus('Server registriert!');
  };

  const startNewServer = () => {
    setMcpEditing({
      id: '',
      name: '',
      url: '',
      description: '',
      enabled: true,
      tools: [],
    });
    setMcpDiscoveredTools([]);
    setMcpDiscoverUrl('');
    setMcpStatus(null);
  };

  const orphanAreas = Object.keys(areaConfigs).filter(k => !areas.some(a => a.area === k));
  const alwaysOnCount = Object.values(areaConfigs).filter(c => c.mode === 'always').length;
  const enabledServers = mcpServers.filter(s => s.enabled).length;

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Wissen</div>
        <div className="page-subtitle">
          Schicht 6: MCP-Tools und RAG-Wissensbereiche.
          {alwaysOnCount > 0 && (
            <span className="tag tag-green" style={{ marginLeft: 8 }}>
              {alwaysOnCount} RAG-Bereich{alwaysOnCount > 1 ? 'e' : ''} immer aktiv
            </span>
          )}
          {enabledServers > 0 && (
            <span className="tag tag-blue" style={{ marginLeft: 8 }}>
              {enabledServers} MCP-Server aktiv
            </span>
          )}
        </div>
      </div>

      <div className="tabs">
        <button className={`tab ${tab === 'areas' ? 'active' : ''}`} onClick={() => setTab('areas')}>
          Wissensbereiche<span className="tab-count">{areas.length}</span>
        </button>
        <button className={`tab ${tab === 'upload' ? 'active' : ''}`} onClick={() => setTab('upload')}>
          Dokument hinzufuegen
        </button>
        <button className={`tab ${tab === 'mcp' ? 'active' : ''}`} onClick={() => setTab('mcp')}>
          MCP-Server<span className="tab-count">{mcpServers.length}</span>
        </button>
      </div>

      {/* ── Areas view ───────────────────────────────────── */}
      {tab === 'areas' && (
        <div>
          {orphanAreas.length > 0 && (
            <div className="card" style={{ marginBottom: 16, borderLeft: '4px solid #f59e0b', background: '#fffbeb' }}>
              <div style={{ fontWeight: 600, color: '#92400e', marginBottom: 4 }}>
                Verwaiste Konfig-Eintraege
              </div>
              <div style={{ fontSize: 13, color: '#78350f', marginBottom: 12 }}>
                Diese Bereiche sind in <code>rag-config.yaml</code> definiert, enthalten aber
                keine indexierten Dokumente. Du kannst sie entfernen oder Dokumente hinzufuegen.
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {orphanAreas.map(a => (
                  <div key={a} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', background: '#fff', border: '1px solid #fde68a', borderRadius: 6 }}>
                    <span style={{ fontWeight: 500 }}>{a}</span>
                    <span className={`area-mode ${areaConfigs[a]?.mode || 'on-demand'}`} style={{ fontSize: 11 }}>
                      {areaConfigs[a]?.mode === 'always' ? 'immer' : 'on-demand'}
                    </span>
                    <button className="btn-ghost" style={{ fontSize: 12, padding: '2px 8px' }} onClick={() => removeOrphanArea(a)}>
                      Entfernen
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
          {areas.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">&#x1F4DA;</div>
              <div className="empty-state-text">Noch keine Wissensbereiche</div>
              <div className="empty-state-hint">Fuege Dokumente hinzu, um Wissensbereiche zu erstellen.</div>
            </div>
          ) : (
            <div className="grid-2">
              {/* Area cards */}
              <div>
                {areas.map(a => {
                  const cfg = areaConfigs[a.area];
                  const mode = cfg?.mode || 'on-demand';
                  return (
                    <div
                      key={a.area}
                      className={`area-card ${selectedArea === a.area ? 'selected' : ''}`}
                      onClick={() => loadDocs(a.area)}
                      style={{ marginBottom: 10 }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ flex: 1 }}>
                          <div className="area-name">{a.area}</div>
                          <div className="area-meta">
                            <span>{a.documents} Dok.</span>
                            <span>{a.chunks} Chunks</span>
                          </div>
                        </div>
                        <button
                          className="btn btn-danger btn-sm btn-icon"
                          onClick={(e) => { e.stopPropagation(); deleteArea(a.area); }}
                          title="Bereich loeschen"
                        >
                          &#x1F5D1;
                        </button>
                      </div>

                      {/* Editable description — debounced auto-save */}
                      <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
                        <textarea
                          className="form-input form-input-sm"
                          value={cfg?.description || ''}
                          onChange={e => {
                            const updated = {
                              ...areaConfigs,
                              [a.area]: { ...areaConfigs[a.area] || { mode: 'on-demand' }, description: e.target.value },
                            };
                            setAreaConfigs(updated);
                            // Debounced: speichert nach 600ms Tipp-Pause
                            scheduleAutoSave(updated);
                          }}
                          onBlur={() => {
                            // Sicherheits-Flush beim Verlassen: falls noch
                            // ein Debounce ansteht, sofort speichern.
                            if (debouncedSaveRef.current) {
                              clearTimeout(debouncedSaveRef.current);
                              debouncedSaveRef.current = null;
                            }
                            void saveAreaConfigs(areaConfigsRef.current);
                          }}
                          placeholder="Beschreibung: Was findet man hier? (z.B. WLO als Bildungsplattform mit Suchmaschine, Fachportalen...)"
                          rows={3}
                          style={{
                            width: '100%',
                            fontSize: '.8rem',
                            color: cfg?.description ? '#1F2937' : '#9CA3AF',
                            background: 'transparent',
                            border: '1px dashed var(--border)',
                            borderRadius: 4,
                            padding: '6px 8px',
                            resize: 'vertical',
                            lineHeight: 1.5,
                            fontFamily: 'inherit',
                          }}
                        />
                        <div
                          className="text-xs text-muted"
                          style={{
                            marginTop: 2, display: 'flex',
                            justifyContent: 'space-between', alignItems: 'center',
                            gap: 8,
                          }}
                        >
                          <span>
                            Diese Beschreibung hilft dem LLM zu entscheiden, wann dieser Bereich relevant ist.
                          </span>
                          {saveStatus !== 'idle' && (
                            <span style={{
                              fontSize: '.68rem',
                              fontWeight: 600,
                              whiteSpace: 'nowrap',
                              color:
                                saveStatus === 'error' ? '#B91C1C' :
                                saveStatus === 'saved' ? '#059669' :
                                '#B45309',
                            }}>
                              {saveStatus === 'pending' && '● ungespeichert'}
                              {saveStatus === 'saving'  && '… speichere'}
                              {saveStatus === 'saved'   && '✓ gespeichert'}
                              {saveStatus === 'error'   && '✕ Fehler beim Speichern'}
                            </span>
                          )}
                        </div>
                      </div>

                      <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <button
                          className={`toggle ${mode === 'always' ? 'active' : ''}`}
                          onClick={(e) => { e.stopPropagation(); toggleAreaMode(a.area); }}
                        />
                        <span className={`area-mode ${mode}`}>
                          {mode === 'always' ? 'Immer verfuegbar' : 'Bei Bedarf (on-demand)'}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Documents in selected area */}
              <div>
                {selectedArea ? (
                  <>
                    <h3 style={{ fontSize: '.92rem', fontWeight: 600, marginBottom: 12 }}>
                      Dokumente in &bdquo;{selectedArea}&ldquo;
                    </h3>
                    {docs.length === 0 ? (
                      <div className="text-sm text-muted">Keine Dokumente gefunden.</div>
                    ) : docs.map((d, i) => (
                      <div key={i} className="card" style={{ marginBottom: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'start' }}>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ fontWeight: 600, fontSize: '.88rem', marginBottom: 4 }}>
                              {d.title || <em style={{ color: 'var(--text-muted)' }}>(ohne Titel)</em>}
                            </div>
                            <div className="text-xs text-muted mb-2">
                              Quelle: {d.source || '—'} &middot; {d.chunks} Chunk{d.chunks === 1 ? '' : 's'}
                            </div>
                          </div>
                          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                            <button
                              type="button"
                              onClick={() => viewDoc(d)}
                              title="Vollständigen Inhalt dieses Dokuments anzeigen"
                              style={{
                                background: '#2B6CB0',
                                color: '#fff',
                                border: 'none',
                                borderRadius: 4,
                                padding: '4px 10px',
                                fontSize: '.72rem',
                                cursor: 'pointer',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              👁 Ansehen
                            </button>
                            <button
                              type="button"
                              onClick={() => deleteDoc(d)}
                              title="Dieses Dokument aus dem Bereich löschen"
                              style={{
                                background: '#DC2626',
                                color: '#fff',
                                border: 'none',
                                borderRadius: 4,
                                padding: '4px 10px',
                                fontSize: '.72rem',
                                cursor: 'pointer',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              🗑 Löschen
                            </button>
                          </div>
                        </div>
                        <div className="text-sm text-muted" style={{ maxHeight: 60, overflow: 'hidden' }}>
                          {d.preview}
                        </div>
                      </div>
                    ))}
                  </>
                ) : (
                  <div className="empty-state">
                    <div className="empty-state-text">Bereich auswaehlen</div>
                    <div className="empty-state-hint">Klicke links auf einen Bereich, um die Dokumente zu sehen.</div>
                  </div>
                )}
              </div>
            </div>
          )}

          <div className="card mt-4" style={{ background: 'var(--primary-lt)', border: 'none' }}>
            <div style={{ fontSize: '.85rem', fontWeight: 600, marginBottom: 6 }}>Wie funktionieren die Modi?</div>
            <div className="text-sm">
              <strong>Immer verfuegbar:</strong> Der Bereich wird bei jeder Nachricht automatisch als RAG-Kontext einbezogen.<br />
              <strong>Bei Bedarf:</strong> Der Bereich wird nur genutzt, wenn das aktive Pattern &bdquo;rag&ldquo; als Quelle definiert hat.
              Patterns koennen gezielt einzelne Bereiche aktivieren.
            </div>
          </div>
        </div>
      )}

      {/* ── Upload view ──────────────────────────────────── */}
      {tab === 'upload' && (
        <div style={{ maxWidth: 640 }}>
          <div className="form-row mb-4">
            <div className="form-group">
              <label className="form-label">Wissensbereich</label>
              {/* Zwei Felder, beide sichtbar. Wenn das untere Textfeld
                  einen Namen hat, gewinnt es; sonst zählt die Auswahl
                  oben. Damit gibt es keinen Mode-Toggle-Bug. */}
              <select
                className="form-input"
                value={uploadArea}
                onChange={e => setUploadArea(e.target.value)}
                disabled={!!newAreaName.trim()}
                style={newAreaName.trim() ? { opacity: 0.55 } : undefined}
              >
                {areas.length === 0 && (
                  <option value="" disabled>
                    — noch keine Bereiche vorhanden —
                  </option>
                )}
                {areas.map(a => (
                  <option key={a.area} value={a.area}>
                    {a.area} ({a.documents} Dok. · {a.chunks} Chunks)
                  </option>
                ))}
              </select>
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  fontSize: '.72rem', color: 'var(--text-muted)',
                  margin: '6px 0 4px',
                }}
              >
                <span style={{ flex: 1, borderTop: '1px dashed #d1d5db' }} />
                <span>oder neuer Bereich</span>
                <span style={{ flex: 1, borderTop: '1px dashed #d1d5db' }} />
              </div>
              <input
                className="form-input"
                value={newAreaName}
                onChange={e => setNewAreaName(e.target.value)}
                placeholder="Name des neuen Wissensbereichs (z.B. wlo-hilfe, didaktik, faq)"
              />
              <div className="form-hint">
                {newAreaName.trim()
                  ? <>→ Upload geht in den neuen Bereich <code>{newAreaName.trim()}</code> (wird automatisch angelegt).</>
                  : 'Leer lassen, um in den oben gewählten Bereich hochzuladen.'}
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Titel (optional)</label>
              <input className="form-input" value={uploadTitle} onChange={e => setUploadTitle(e.target.value)}
                placeholder="Dokumenttitel" />
            </div>
          </div>

          {/* Live-Anzeige: wohin der Upload gehen wird.
              Damit der User VOR dem Klick eindeutig sieht, welches
              Ziel aktiv ist — kein versteckter Default mehr. */}
          <div
            style={{
              background: '#EFF6FF',
              border: '1px solid #BFDBFE',
              borderRadius: 8,
              padding: '10px 14px',
              marginBottom: 16,
              fontSize: '.84rem',
              color: '#1E3A8A',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <span style={{ fontSize: '1.1rem' }}>→</span>
            <div>
              <div>
                Upload-Ziel: <strong>
                  <code style={{
                    background: '#DBEAFE',
                    padding: '2px 8px',
                    borderRadius: 4,
                    color: '#1E3A8A',
                  }}>{effectiveAreaName() || '(kein Bereich gewählt)'}</code>
                </strong>
              </div>
              <div style={{ fontSize: '.72rem', marginTop: 2, color: '#3B4E7A' }}>
                {newAreaName.trim()
                  ? <>Der Bereich wird neu angelegt (aus Textfeld „neuer Bereich").</>
                  : areas.some(a => a.area === uploadArea)
                    ? <>Existierender Bereich aus dem Dropdown.</>
                    : <>Hinweis: Der Bereich <code>{uploadArea}</code> existiert noch nicht — er wird beim Upload neu angelegt.</>}
              </div>
            </div>
          </div>

          <div className="card mb-4">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: '.88rem' }}>Datei hochladen</div>
                <div className="text-xs text-muted">PDF, DOCX, PPTX, HTML, TXT, MD, CSV, XLSX</div>
              </div>
              <button className="btn btn-primary btn-sm" onClick={() => doUpload('file')} disabled={uploading}>
                {uploading ? 'Verarbeite...' : 'Hochladen'}
              </button>
            </div>
            <input type="file" ref={fileRef} accept=".pdf,.docx,.pptx,.html,.htm,.txt,.md,.csv,.xlsx" />
          </div>

          <div className="card mb-4">
            <div style={{ fontWeight: 600, fontSize: '.88rem', marginBottom: 8 }}>Webseite importieren</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <input className="form-input" value={uploadUrl} onChange={e => setUploadUrl(e.target.value)}
                placeholder="https://example.com/page" style={{ flex: 1 }} />
              <button className="btn btn-primary btn-sm" onClick={() => doUpload('url')} disabled={uploading || !uploadUrl}>
                Importieren
              </button>
            </div>
          </div>

          <div className="card mb-4">
            <div style={{ fontWeight: 600, fontSize: '.88rem', marginBottom: 8 }}>Text / Markdown direkt eingeben</div>
            <textarea className="form-textarea" value={uploadText} onChange={e => setUploadText(e.target.value)}
              placeholder="Markdown oder Text hier einfuegen..." style={{ minHeight: 120, marginBottom: 8 }} />
            <button className="btn btn-primary btn-sm" onClick={() => doUpload('text')} disabled={uploading || !uploadText}>
              Text importieren
            </button>
          </div>

          {uploadResult && (
            <div className="card" style={{ background: uploadResult.includes('Fehler') ? '#FEF2F2' : '#F0FDF4' }}>
              {uploadResult}
            </div>
          )}
        </div>
      )}

      {/* ── MCP Server view ──────────────────────────────── */}
      {tab === 'mcp' && (
        <div>
          {/* Registered servers list */}
          {mcpServers.length === 0 && !mcpEditing ? (
            <div className="empty-state">
              <div className="empty-state-icon">&#x1F50C;</div>
              <div className="empty-state-text">Keine MCP-Server registriert</div>
              <div className="empty-state-hint">
                MCP-Server stellen Tools bereit, die der Chatbot in Patterns nutzen kann.
              </div>
              <button className="btn btn-primary mt-4" onClick={startNewServer}>
                + MCP-Server hinzufuegen
              </button>
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
                <button className="btn btn-primary btn-sm" onClick={startNewServer}>
                  + MCP-Server hinzufuegen
                </button>
              </div>

              {mcpServers.map(server => (
                <div key={server.id} className="card mb-3" style={{
                  opacity: server.enabled ? 1 : 0.6,
                  borderLeft: `3px solid ${server.enabled ? 'var(--green)' : 'var(--border)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <span style={{ fontWeight: 700, fontSize: '.95rem' }}>{server.name || server.id}</span>
                        <span className={`tag ${server.enabled ? 'tag-green' : 'tag-muted'}`}>
                          {server.enabled ? 'Aktiv' : 'Deaktiviert'}
                        </span>
                      </div>
                      <div className="text-sm text-muted" style={{ marginBottom: 4 }}>{server.description}</div>
                      <div className="text-xs text-muted" style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                        {server.url}
                      </div>
                      {server.tools.length > 0 && (
                        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                          {server.tools.map(t => (
                            <span key={t} className="tag tag-sm">{t}</span>
                          ))}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button
                        className="btn btn-sm"
                        onClick={() => toggleMcpServer(server.id)}
                        title={server.enabled ? 'Deaktivieren' : 'Aktivieren'}
                      >
                        {server.enabled ? 'Deaktivieren' : 'Aktivieren'}
                      </button>
                      <button
                        className="btn btn-sm"
                        onClick={() => {
                          setMcpEditing({ ...server });
                          setMcpDiscoverUrl(server.url);
                          setMcpDiscoveredTools(server.tools.map(t => ({ name: t, description: '' })));
                        }}
                      >
                        Bearbeiten
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => deleteMcpServer(server.id)}
                      >
                        &#x1F5D1;
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </>
          )}

          {/* Add/Edit server dialog */}
          {mcpEditing && (
            <div className="dialog-overlay" onClick={() => setMcpEditing(null)}>
              <div className="dialog" onClick={e => e.stopPropagation()} style={{ maxWidth: 640 }}>
                <div className="dialog-title">
                  {mcpEditing.id && mcpServers.find(s => s.id === mcpEditing.id)
                    ? 'MCP-Server bearbeiten'
                    : 'Neuen MCP-Server registrieren'}
                </div>

                <div className="form-group mb-3">
                  <label className="form-label">Server-URL</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input
                      className="form-input"
                      value={mcpDiscoverUrl}
                      onChange={e => setMcpDiscoverUrl(e.target.value)}
                      placeholder="https://example.com/mcp"
                      style={{ flex: 1 }}
                    />
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={discoverTools}
                      disabled={mcpDiscovering || !mcpDiscoverUrl}
                    >
                      {mcpDiscovering ? 'Verbinde...' : 'Tools erkennen'}
                    </button>
                  </div>
                  <div className="form-hint">
                    MCP-Server-Endpunkt (JSON-RPC 2.0 / SSE). Klicke &quot;Tools erkennen&quot; um verfuegbare Tools abzufragen.
                  </div>
                </div>

                {mcpStatus && (
                  <div className="card mb-3" style={{
                    background: mcpStatus.includes('Fehler') || mcpStatus.includes('fehlgeschlagen')
                      ? '#FEF2F2' : '#F0FDF4',
                    fontSize: '.85rem',
                  }}>
                    {mcpStatus}
                  </div>
                )}

                {mcpDiscoveredTools.length > 0 && (
                  <div className="mb-3">
                    <div className="form-label">Erkannte Tools ({mcpDiscoveredTools.length})</div>
                    <div style={{ maxHeight: 200, overflow: 'auto', border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}>
                      {mcpDiscoveredTools.map(t => (
                        <div key={t.name} style={{ padding: '4px 0', borderBottom: '1px solid var(--border-lt)' }}>
                          <span style={{ fontFamily: 'monospace', fontSize: '.82rem', fontWeight: 600 }}>{t.name}</span>
                          {t.description && (
                            <div className="text-xs text-muted" style={{ marginTop: 2 }}>{t.description}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="form-row mb-3">
                  <div className="form-group">
                    <label className="form-label">Server-ID</label>
                    <input
                      className="form-input"
                      value={mcpEditing.id}
                      onChange={e => setMcpEditing({ ...mcpEditing, id: e.target.value })}
                      placeholder="z.B. my-server"
                    />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Name</label>
                    <input
                      className="form-input"
                      value={mcpEditing.name}
                      onChange={e => setMcpEditing({ ...mcpEditing, name: e.target.value })}
                      placeholder="Anzeigename"
                    />
                  </div>
                </div>

                <div className="form-group mb-3">
                  <label className="form-label">Beschreibung</label>
                  <input
                    className="form-input"
                    value={mcpEditing.description}
                    onChange={e => setMcpEditing({ ...mcpEditing, description: e.target.value })}
                    placeholder="Was stellt dieser Server bereit?"
                  />
                </div>

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button className="btn" onClick={() => setMcpEditing(null)}>Abbrechen</button>
                  <button
                    className="btn btn-primary"
                    onClick={() => {
                      const server: McpServer = {
                        ...mcpEditing,
                        url: mcpDiscoverUrl || mcpEditing.url,
                        tools: mcpDiscoveredTools.length > 0
                          ? mcpDiscoveredTools.map(t => t.name)
                          : mcpEditing.tools,
                      };
                      registerDiscoveredServer();
                    }}
                    disabled={!mcpEditing.id || !mcpDiscoverUrl}
                  >
                    Speichern
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Explanation */}
          <div className="card mt-4" style={{ background: 'var(--primary-lt)', border: 'none' }}>
            <div style={{ fontSize: '.85rem', fontWeight: 600, marginBottom: 6 }}>Was sind MCP-Server?</div>
            <div className="text-sm">
              <strong>MCP (Model Context Protocol)</strong> ist ein Standard, ueber den LLMs auf externe Tools zugreifen.<br />
              Registrierte Server stellen Tools bereit (z.B. Suche, Metadaten-Abfragen), die in <strong>Patterns</strong> referenziert werden.<br />
              Beim Hinzufuegen eines Servers werden die verfuegbaren Tools automatisch erkannt.<br /><br />
              <strong>Beispiele:</strong> OER-Repositorien, Curriculum-Datenbanken, Schulbuch-Verlage, interne Wikis
            </div>
          </div>
        </div>
      )}

      {/* ── Viewer-Modal: Volltext eines Dokuments (alle Chunks) ── */}
      {viewerOpen && (
        <div
          onClick={closeViewer}
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
            zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            onClick={e => e.stopPropagation()}
            style={{
              background: '#fff', borderRadius: 12, padding: 20,
              width: 'min(900px, 94vw)', maxHeight: '88vh',
              display: 'flex', flexDirection: 'column', gap: 12,
              boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <h2 style={{ margin: 0, fontSize: '1.05rem' }}>
                  {viewerData?.title || <em style={{ color: 'var(--text-muted)' }}>(ohne Titel)</em>}
                </h2>
                <div style={{ fontSize: '.74rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  Bereich: <code>{viewerData?.area || selectedArea}</code>
                  &nbsp;·&nbsp;Quelle: {viewerData?.source || '—'}
                  {viewerData && (
                    <>
                      &nbsp;·&nbsp;{viewerData.chunk_count} Chunks
                      &nbsp;·&nbsp;{viewerData.total_chars.toLocaleString('de-DE')} Zeichen
                    </>
                  )}
                </div>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={closeViewer}>Schließen</button>
            </div>

            <div
              style={{
                overflow: 'auto', flex: 1, minHeight: 200,
                border: '1px solid var(--border, #e5e7eb)',
                borderRadius: 8, padding: 4, background: '#fafafa',
              }}
            >
              {viewerLoading && (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                  Lade Inhalt…
                </div>
              )}
              {!viewerLoading && viewerData && viewerData.chunks.length === 0 && (
                <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>
                  Keine Chunks gefunden.
                </div>
              )}
              {!viewerLoading && viewerData && viewerData.chunks.map((c) => (
                <div
                  key={c.index}
                  style={{
                    padding: '10px 14px',
                    borderBottom: '1px solid #eee',
                    fontSize: '.84rem',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    lineHeight: 1.55,
                  }}
                >
                  <div style={{
                    fontSize: '.68rem',
                    color: '#6b7280',
                    fontWeight: 600,
                    marginBottom: 6,
                    textTransform: 'uppercase',
                    letterSpacing: '.04em',
                  }}>
                    Chunk {c.index + 1} / {viewerData.chunk_count}
                    <span style={{ opacity: 0.7, marginLeft: 10, fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                      {c.content.length.toLocaleString('de-DE')} Zeichen
                    </span>
                  </div>
                  {c.content}
                </div>
              ))}
            </div>

            {/* Footer-Aktionen */}
            {viewerData && viewerData.chunks.length > 0 && (
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: '.78rem' }}>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={async () => {
                    const text = (viewerData.chunks || []).map(c => c.content).join('\n\n---\n\n');
                    try {
                      await navigator.clipboard.writeText(text);
                      alert('Volltext in Zwischenablage kopiert.');
                    } catch {
                      alert('Clipboard nicht verfügbar.');
                    }
                  }}
                >
                  📋 Kopieren
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    const text = (viewerData.chunks || []).map(c => c.content).join('\n\n---\n\n');
                    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    const safe = (viewerData.title || 'dokument').replace(/[^\w.\-äöüÄÖÜß]+/g, '_');
                    a.href = url; a.download = `${safe}.md`; a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  ↓ Download .md
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
