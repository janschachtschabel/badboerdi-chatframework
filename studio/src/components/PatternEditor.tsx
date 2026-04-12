'use client';

import { useState, useEffect, useCallback } from 'react';
import type { Elements, PatternData } from '@/app/page';

// ── YAML helpers ─────────────────────────────────────────────────────
function serializeYamlValue(value: any, indent: number = 0): string {
  const pad = '  '.repeat(indent);
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') {
    if (value === '' || value === '*' || value.includes(':') || value.includes('#') || value.includes('"'))
      return `"${value.replace(/"/g, '\\"')}"`;
    return value;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return '[]';
    // Use inline JSON format for consistency with pattern files
    const items = value.map(v =>
      typeof v === 'string' ? `"${v.replace(/"/g, '\\"')}"` : String(v)
    );
    return `[${items.join(', ')}]`;
  }
  return String(value);
}

function patternToFileContent(p: PatternData, body: string): string {
  const fields: [string, any][] = [
    ['id', p.id],
    ['label', p.label],
    ['priority', p.priority ?? 400],
    ['gate_personas', p.gate_personas ?? ['*']],
    ['gate_states', p.gate_states ?? ['*']],
    ['gate_intents', p.gate_intents ?? ['*']],
    ['signal_high_fit', p.signal_high_fit ?? []],
    ['signal_medium_fit', p.signal_medium_fit ?? []],
    ['signal_low_fit', p.signal_low_fit ?? []],
    ['page_bonus', p.page_bonus ?? []],
    ['precondition_slots', p.precondition_slots ?? []],
    ['default_tone', p.default_tone ?? 'sachlich'],
    ['default_length', p.default_length ?? 'mittel'],
    ['default_detail', p.default_detail ?? 'standard'],
    ['response_type', p.response_type ?? 'answer'],
    ['sources', p.sources ?? ['mcp']],
    ['rag_areas', p.rag_areas ?? []],
    ['format_primary', p.format_primary ?? 'text'],
    ['format_follow_up', p.format_follow_up ?? 'none'],
    ['card_text_mode', p.card_text_mode ?? 'minimal'],
    ['tools', p.tools ?? []],
    ['core_rule', p.core_rule ?? ''],
  ];

  const yamlLines = fields.map(([key, val]) => {
    const sv = serializeYamlValue(val);
    return `${key}: ${sv}`;
  });

  return `---\n${yamlLines.join('\n')}\n---\n\n${body}`;
}

function parseFrontmatterAndBody(raw: string): { meta: Record<string, any>; body: string } {
  const match = raw.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)/);
  if (!match) return { meta: {}, body: raw };

  // Simple YAML parser for our known structures
  const meta: Record<string, any> = {};
  let currentKey = '';
  let currentArray: string[] | null = null;

  for (const line of match[1].split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    if (trimmed.startsWith('- ')) {
      if (currentArray) {
        let val = trimmed.slice(2).trim();
        if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1);
        currentArray.push(val);
      }
      continue;
    }

    // Save previous array
    if (currentArray && currentKey) {
      meta[currentKey] = currentArray;
      currentArray = null;
    }

    const colonIdx = trimmed.indexOf(':');
    if (colonIdx === -1) continue;

    const key = trimmed.slice(0, colonIdx).trim();
    let val = trimmed.slice(colonIdx + 1).trim();

    if (val === '' || val === undefined) {
      // Start of array or object
      currentKey = key;
      currentArray = [];
      continue;
    }

    if (val === '[]') {
      meta[key] = [];
    } else if (val.startsWith('[') && val.endsWith(']')) {
      // Inline JSON array: ["a", "b", "c"] or ["*"]
      try {
        meta[key] = JSON.parse(val);
      } catch {
        // Fallback: parse manually – strip brackets, split by comma, unquote
        meta[key] = val.slice(1, -1).split(',')
          .map(s => s.trim().replace(/^["']|["']$/g, ''))
          .filter(Boolean);
      }
    } else if (val === 'true') {
      meta[key] = true;
    } else if (val === 'false') {
      meta[key] = false;
    } else if (/^\d+$/.test(val)) {
      meta[key] = parseInt(val, 10);
    } else if (/^\d+\.\d+$/.test(val)) {
      meta[key] = parseFloat(val);
    } else {
      if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1);
      meta[key] = val;
    }
    currentKey = key;
  }

  if (currentArray && currentKey) {
    meta[currentKey] = currentArray;
  }

  return { meta, body: match[2].trim() };
}

// ── MCP tools (fallback if backend unavailable) ─────────────────────
const FALLBACK_MCP_TOOLS = [
  'search_wlo_collections', 'search_wlo_content', 'search_wlo_topic_pages',
  'get_collection_contents', 'get_node_details', 'lookup_wlo_vocabulary',
  'get_wirlernenonline_info', 'get_edu_sharing_network_info',
  'get_edu_sharing_product_info', 'get_metaventis_info',
];

const TONE_OPTIONS = ['sachlich', 'empathisch', 'transparent', 'einladend', 'spielerisch', 'empfehlend', 'niedrigschwellig', 'beruhigend', 'orientierend', 'belegend'];
const LENGTH_OPTIONS = ['kurz', 'mittel', 'lang'];
const DETAIL_OPTIONS = ['standard', 'detail', 'overview'];
const RESPONSE_TYPE_OPTIONS = ['answer', 'question', 'suggestion'];
const FORMAT_OPTIONS = ['text', 'cards', 'list'];
const FOLLOW_UP_OPTIONS = ['quick_replies', 'inline', 'none'];
const CARD_TEXT_MODE_OPTIONS = ['minimal', 'reference', 'highlight'];
const SOURCE_OPTIONS = ['mcp', 'rag'];

// ── Props ────────────────────────────────────────────────────────────
interface Props {
  elements: Elements;
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
  createFile: (path: string, content: string) => Promise<boolean>;
}

// ── Chip Multi-Select ────────────────────────────────────────────────
function ChipSelect({ options, selected, onChange, colorClass = 'tag-blue' }: {
  options: { id: string; label?: string }[];
  selected: string[];
  onChange: (val: string[]) => void;
  colorClass?: string;
}) {
  const toggle = (id: string) => {
    if (selected.includes(id)) {
      onChange(selected.filter(s => s !== id));
    } else {
      onChange([...selected, id]);
    }
  };

  const hasWildcard = selected.includes('*');

  return (
    <div className="checkbox-group">
      <label
        className={`checkbox-item ${hasWildcard ? 'checked' : ''}`}
        onClick={() => onChange(hasWildcard ? [] : ['*'])}
      >
        Alle (*)
      </label>
      {options.map(o => (
        <label
          key={o.id}
          className={`checkbox-item ${!hasWildcard && selected.includes(o.id) ? 'checked' : ''}`}
          style={{ opacity: hasWildcard ? 0.5 : 1 }}
          onClick={() => {
            if (hasWildcard) onChange([o.id]);
            else toggle(o.id);
          }}
        >
          {o.label || o.id}
        </label>
      ))}
    </div>
  );
}

// ── RAG Area Input (loads available areas from backend) ─────────────
function RagAreaInput({ selected, onChange }: {
  selected: string[];
  onChange: (val: string[]) => void;
}) {
  const [areas, setAreas] = useState<string[]>([]);
  const [newArea, setNewArea] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const resp = await fetch('/api/rag/areas');
        if (resp.ok) {
          const data = await resp.json();
          setAreas(data.map((a: any) => a.area));
        }
      } catch { /* ignore */ }
    })();
  }, []);

  // Combine backend areas with any areas already selected (in case they don't exist yet)
  const allOptions = Array.from(new Set([...areas, ...selected]));

  const toggle = (area: string) => {
    if (selected.includes(area)) {
      onChange(selected.filter(a => a !== area));
    } else {
      onChange([...selected, area]);
    }
  };

  const addCustom = () => {
    const a = newArea.trim();
    if (a && !selected.includes(a)) {
      onChange([...selected, a]);
      setNewArea('');
    }
  };

  return (
    <div>
      <div className="checkbox-group">
        {allOptions.length === 0 && (
          <span className="text-sm text-muted">Keine Wissensbereiche vorhanden. Erstelle zuerst Bereiche unter Schicht 5.</span>
        )}
        {allOptions.map(a => (
          <label key={a} className={`checkbox-item ${selected.includes(a) ? 'checked' : ''}`}
            onClick={() => toggle(a)}>
            {a}
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
        <input className="form-input form-input-sm" value={newArea} onChange={e => setNewArea(e.target.value)}
          placeholder="Neuer Bereich..." style={{ width: 180 }}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addCustom(); } }} />
        <button className="btn btn-secondary btn-sm" onClick={addCustom} disabled={!newArea.trim()}>+</button>
      </div>
    </div>
  );
}

// ── Main Component ───────────────────────────────────────────────────
export default function PatternEditor({ elements, loadFile, saveFile, onReload, createFile }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editData, setEditData] = useState<PatternData | null>(null);
  const [body, setBody] = useState('');
  const [originalRaw, setOriginalRaw] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newPatternId, setNewPatternId] = useState('');
  const [newPatternLabel, setNewPatternLabel] = useState('');

  // Dynamically load available MCP tools from backend
  const [mcpTools, setMcpTools] = useState<string[]>(FALLBACK_MCP_TOOLS);
  useEffect(() => {
    (async () => {
      try {
        const resp = await fetch('/api/config/mcp-servers');
        if (resp.ok) {
          const data = await resp.json();
          const tools = new Set<string>();
          const servers = Array.isArray(data) ? data : data?.servers ?? [];
          for (const srv of servers) {
            if (srv.enabled !== false && Array.isArray(srv.tools)) {
              for (const t of srv.tools) tools.add(t);
            }
          }
          if (tools.size > 0) setMcpTools(Array.from(tools).sort());
        }
      } catch { /* use fallback */ }
    })();
  }, []);

  const patterns = elements.patterns || [];
  const selected = patterns.find(p => p.id === selectedId);

  // Load pattern file when selection changes
  useEffect(() => {
    if (!selected?.file) { setEditData(null); setBody(''); return; }
    (async () => {
      const raw = await loadFile(selected.file!);
      setOriginalRaw(raw);
      const { meta, body: b } = parseFrontmatterAndBody(raw);
      // Merge loaded meta with element data (element data has parsed arrays)
      setEditData({ ...selected, ...meta });
      setBody(b);
      setStatus('idle');
    })();
  }, [selectedId, selected?.file, loadFile]);

  // Update a field in editData
  const update = (field: string, value: any) => {
    if (!editData) return;
    setEditData({ ...editData, [field]: value });
  };

  // Save
  const handleSave = async () => {
    if (!editData?.file) return;
    setStatus('saving');
    const content = patternToFileContent(editData, body);
    const ok = await saveFile(editData.file, content);
    if (ok) {
      setOriginalRaw(content);
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  const handleCreate = async () => {
    if (!newPatternId.trim()) return;
    const id = newPatternId.trim();
    const label = newPatternLabel.trim() || id;
    const filename = id.toLowerCase().replace(/[^a-z0-9-]/g, '-') + '.md';
    const path = `03-patterns/${filename}`;
    const defaultPattern: PatternData = {
      id,
      label,
      priority: 400,
      gate_personas: ['*'],
      gate_states: ['*'],
      gate_intents: ['*'],
      signal_high_fit: [],
      signal_medium_fit: [],
      signal_low_fit: [],
      page_bonus: [],
      precondition_slots: [],
      default_tone: 'sachlich',
      default_length: 'mittel',
      default_detail: 'standard',
      response_type: 'answer',
      sources: ['mcp'],
      format_primary: 'text',
      format_follow_up: 'none',
      tools: [],
      core_rule: '',
      file: path,
    };
    const content = patternToFileContent(defaultPattern, '# ' + label + '\n\nBeschreibe hier die Anweisungen für dieses Pattern.');
    const ok = await createFile(path, content);
    if (ok) {
      setShowCreateDialog(false);
      setNewPatternId('');
      setNewPatternLabel('');
      await onReload();
      setSelectedId(id);
    }
  };

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div className="page-title">Patterns</div>
          <div className="page-subtitle">Schicht 3: Gesprächsmuster steuern Ton, Format und Tool-Auswahl je nach Situation.</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreateDialog(true)}>+ Neues Pattern</button>
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="dialog-overlay" onClick={() => setShowCreateDialog(false)}>
          <div className="dialog" onClick={e => e.stopPropagation()}>
            <div className="dialog-title">Neues Pattern anlegen</div>
            <div className="form-group">
              <label className="form-label">Pattern ID</label>
              <input className="form-input" value={newPatternId} onChange={e => setNewPatternId(e.target.value)}
                placeholder="z.B. PAT-21-custom" autoFocus />
              <div className="form-hint">Eindeutige ID, z.B. PAT-21-mein-pattern</div>
            </div>
            <div className="form-group">
              <label className="form-label">Label</label>
              <input className="form-input" value={newPatternLabel} onChange={e => setNewPatternLabel(e.target.value)}
                placeholder="z.B. Mein neues Pattern"
                onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }} />
            </div>
            <div className="btn-group" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={() => setShowCreateDialog(false)}>Abbrechen</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={!newPatternId.trim()}>Erstellen</button>
            </div>
          </div>
        </div>
      )}

      <div className="split-layout">
        {/* Pattern list */}
        <div className="split-left">
          {patterns.map(p => (
            <div
              key={p.id}
              className={`pattern-item ${selectedId === p.id ? 'selected' : ''}`}
              onClick={() => setSelectedId(p.id)}
            >
              <span className="pattern-id">{p.id}</span>
              <span className="pattern-label">{p.label}</span>
              <span className="pattern-priority">{p.priority}</span>
            </div>
          ))}
        </div>

        {/* Pattern detail form */}
        <div className="split-right">
          {!editData ? (
            <div className="empty-state">
              <div className="empty-state-icon">&#x1F9E9;</div>
              <div className="empty-state-text">Pattern auswählen</div>
              <div className="empty-state-hint">Wähle links ein Pattern zum Bearbeiten.</div>
            </div>
          ) : (
            <div>
              {/* Header with save */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                  <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>{editData.id}: {editData.label}</h2>
                  <div className="text-xs text-muted font-mono">{editData.file}</div>
                </div>
                <div className="btn-group">
                  {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
                  {status === 'error' && <span className="save-status error">Fehler</span>}
                  <button className="btn btn-primary" onClick={handleSave} disabled={status === 'saving'}>
                    {status === 'saving' ? 'Speichert...' : 'Speichern'}
                  </button>
                </div>
              </div>

              {/* Basic fields */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x2699;&#xFE0F;</span> Grundeinstellungen</div>
                <div className="form-row-3">
                  <div className="form-group">
                    <label className="form-label">Label</label>
                    <input className="form-input" value={editData.label} onChange={e => update('label', e.target.value)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Priorität</label>
                    <input className="form-input form-number" type="number" value={editData.priority ?? 400}
                      onChange={e => update('priority', parseInt(e.target.value) || 400)} />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Response-Typ</label>
                    <select className="form-select" value={editData.response_type ?? 'answer'}
                      onChange={e => update('response_type', e.target.value)}>
                      {RESPONSE_TYPE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              {/* Phase 1: Gates */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F6AA;</span> Phase 1: Gates (Filterung)</div>
                <div className="gate-grid">
                  <div className="gate-box">
                    <div className="gate-box-title">Personas</div>
                    <ChipSelect
                      options={elements.personas.map(p => ({ id: p.id, label: p.label }))}
                      selected={editData.gate_personas ?? ['*']}
                      onChange={v => update('gate_personas', v.length ? v : ['*'])}
                    />
                  </div>
                  <div className="gate-box">
                    <div className="gate-box-title">States</div>
                    <ChipSelect
                      options={elements.states.map(s => ({ id: s.id, label: s.label }))}
                      selected={editData.gate_states ?? ['*']}
                      onChange={v => update('gate_states', v.length ? v : ['*'])}
                      colorClass="tag-green"
                    />
                  </div>
                  <div className="gate-box">
                    <div className="gate-box-title">Intents</div>
                    <ChipSelect
                      options={elements.intents.map(i => ({ id: i.id, label: i.label }))}
                      selected={editData.gate_intents ?? ['*']}
                      onChange={v => update('gate_intents', v.length ? v : ['*'])}
                      colorClass="tag-yellow"
                    />
                  </div>
                </div>
              </div>

              {/* Phase 2: Signals */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F4E1;</span> Phase 2: Signal-Scoring</div>
                <div className="form-group">
                  <label className="form-label">High Fit Signale (Gewicht 1.0)</label>
                  <ChipSelect
                    options={elements.signals.map(s => ({ id: s.id }))}
                    selected={editData.signal_high_fit ?? []}
                    onChange={v => update('signal_high_fit', v.filter(x => x !== '*'))}
                    colorClass="tag-green"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Medium Fit Signale (Gewicht 0.5)</label>
                  <ChipSelect
                    options={elements.signals.map(s => ({ id: s.id }))}
                    selected={editData.signal_medium_fit ?? []}
                    onChange={v => update('signal_medium_fit', v.filter(x => x !== '*'))}
                    colorClass="tag-yellow"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Low Fit Signale (Gewicht 0.2)</label>
                  <ChipSelect
                    options={elements.signals.map(s => ({ id: s.id }))}
                    selected={editData.signal_low_fit ?? []}
                    onChange={v => update('signal_low_fit', v.filter(x => x !== '*'))}
                    colorClass="tag-gray"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">Precondition Slots (benötigte Entities)</label>
                  <ChipSelect
                    options={elements.entities.map(e => ({ id: e.id, label: e.label || e.id }))}
                    selected={editData.precondition_slots ?? []}
                    onChange={v => update('precondition_slots', v.filter(x => x !== '*'))}
                    colorClass="tag-purple"
                  />
                </div>
              </div>

              {/* Phase 3: Output defaults */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F3A8;</span> Phase 3: Ausgabe-Defaults</div>
                <div className="form-row-4">
                  <div className="form-group">
                    <label className="form-label">Ton</label>
                    <select className="form-select" value={editData.default_tone ?? 'sachlich'}
                      onChange={e => update('default_tone', e.target.value)}>
                      {TONE_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Länge</label>
                    <select className="form-select" value={editData.default_length ?? 'mittel'}
                      onChange={e => update('default_length', e.target.value)}>
                      {LENGTH_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Detail</label>
                    <select className="form-select" value={editData.default_detail ?? 'standard'}
                      onChange={e => update('default_detail', e.target.value)}>
                      {DETAIL_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Format</label>
                    <select className="form-select" value={editData.format_primary ?? 'text'}
                      onChange={e => update('format_primary', e.target.value)}>
                      {FORMAT_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Follow-Up</label>
                    <select className="form-select" value={editData.format_follow_up ?? 'none'}
                      onChange={e => update('format_follow_up', e.target.value)}>
                      {FOLLOW_UP_OPTIONS.map(o => <option key={o}>{o}</option>)}
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label">Kachel-Text-Modus</label>
                    <select className="form-select" value={editData.card_text_mode ?? 'minimal'}
                      onChange={e => update('card_text_mode', e.target.value)}>
                      {CARD_TEXT_MODE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Quellen</label>
                    <div className="checkbox-group">
                      {SOURCE_OPTIONS.map(s => (
                        <label key={s} className={`checkbox-item ${(editData.sources ?? []).includes(s) ? 'checked' : ''}`}
                          onClick={() => {
                            const cur = editData.sources ?? [];
                            update('sources', cur.includes(s) ? cur.filter(x => x !== s) : [...cur, s]);
                          }}>
                          {s}
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

              </div>

              {/* RAG Knowledge Areas - own section, only when "rag" source is active */}
              {(editData.sources ?? []).includes('rag') && (
                <div className="section" style={{ background: '#F0F9FF', border: '1px solid #BAE6FD', borderRadius: 8, padding: 16 }}>
                  <div className="section-title">
                    <span className="section-icon">&#x1F4DA;</span> RAG-Wissensbereiche fuer dieses Pattern
                  </div>
                  <div className="form-hint mb-3" style={{ fontSize: '.85rem' }}>
                    Welche Wissensbereiche soll dieses Pattern nutzen?
                    Waehle gezielt einzelne Bereiche aus, oder lasse alle leer = es werden <strong>alle on-demand-Bereiche</strong> genutzt.
                  </div>
                  <RagAreaInput
                    selected={editData.rag_areas ?? []}
                    onChange={v => update('rag_areas', v)}
                  />
                </div>
              )}

              {/* Tools */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F527;</span> MCP Tools</div>
                <div className="checkbox-group">
                  {/* Merge dynamic tools with any already-selected tools (in case they aren't in the server list) */}
                  {Array.from(new Set([...mcpTools, ...(editData.tools ?? [])])).map(t => (
                    <label key={t} className={`checkbox-item ${(editData.tools ?? []).includes(t) ? 'checked' : ''}`}
                      onClick={() => {
                        const cur = editData.tools ?? [];
                        update('tools', cur.includes(t) ? cur.filter(x => x !== t) : [...cur, t]);
                      }}>
                      {t}
                    </label>
                  ))}
                </div>
              </div>

              {/* Core rule */}
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F4DD;</span> Kernregel & Anweisungen</div>
                <div className="form-group">
                  <label className="form-label">Kernregel (core_rule)</label>
                  <input className="form-input" value={editData.core_rule ?? ''}
                    onChange={e => update('core_rule', e.target.value)}
                    placeholder="z.B. Maximal 2 Sätze, keine Einleitung." />
                </div>
                <div className="form-group">
                  <label className="form-label">Zusätzliche Anweisungen (Markdown-Body)</label>
                  <textarea
                    className="form-textarea form-textarea-lg"
                    value={body}
                    onChange={e => setBody(e.target.value)}
                    placeholder="Weitere Pattern-Anweisungen im Markdown-Format..."
                    spellCheck={false}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
