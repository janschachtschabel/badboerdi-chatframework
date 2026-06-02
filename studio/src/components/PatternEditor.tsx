'use client';

import { useState, useEffect, useCallback } from 'react';
import type { Elements, PatternData } from '@/app/page';

// ── YAML helpers ─────────────────────────────────────────────────────
function serializeYamlValue(value: any, indent: number = 0): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') {
    // Multi-line string → YAML block scalar with `|` so newlines survive round-trip
    if (value.includes('\n')) {
      const indented = value.replace(/\n$/, '').split('\n').map(l => `  ${l}`).join('\n');
      return `|\n${indented}`;
    }
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
  // Welle E v4 (2026-05-25): deprecated Felder (gate_personas, gate_states,
  // gate_intents, signal_*, page_bonus) werden nicht mehr serialisiert.
  // Der LLM-Hint wählt das Pattern; Phase 1+2 sind aus der Engine raus.
  // Existierende MD-Dateien mit alten Feldern werden vom config_loader
  // still ignoriert.
  const fields: [string, any][] = [
    ['id', p.id],
    ['label', p.label],
    ['priority', p.priority ?? 400],
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

  const lines = match[1].split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
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

    // Block scalar (`|`, `|-`, `>`) — consume subsequent indented lines as string
    if (val === '|' || val === '|-' || val === '>') {
      const mode = val;
      const collected: string[] = [];
      let j = i + 1;
      // Determine baseline indent from first non-empty indented line
      let baseIndent = -1;
      while (j < lines.length) {
        const next = lines[j];
        if (next.trim() === '') { collected.push(''); j++; continue; }
        const leading = next.match(/^(\s+)/)?.[1].length ?? 0;
        if (leading === 0) break;
        if (baseIndent < 0) baseIndent = leading;
        if (leading < baseIndent) break;
        collected.push(next.slice(baseIndent));
        j++;
      }
      i = j - 1;
      let joined: string;
      if (mode === '>') {
        // Folded: replace single newlines with spaces, keep blank lines as \n
        joined = collected.join('\n').replace(/([^\n])\n(?!\n)/g, '$1 ');
      } else {
        joined = collected.join('\n');
      }
      if (mode === '|-') joined = joined.replace(/\n+$/, '');
      else joined = joined.replace(/\n*$/, '\n').replace(/\n+$/, '\n');
      meta[key] = joined.replace(/\n$/, '');
      currentKey = key;
      continue;
    }

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

// ── Pattern-Discriminators — vs/rule/example-Tripel-Editor (Welle E v4+7) ──
function PatternDiscriminators({ values, onChange }: {
  values: Array<{ vs: string; rule: string; example?: string }>;
  onChange: (v: Array<{ vs: string; rule: string; example?: string }>) => void;
}) {
  const items = values || [];
  const update = (idx: number, key: 'vs' | 'rule' | 'example', val: string) => {
    const next = [...items];
    next[idx] = { ...next[idx], [key]: val };
    onChange(next);
  };
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, { vs: '', rule: '', example: '' }]);
  return (
    <div className="form-group">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label className="form-label" style={{ margin: 0 }}>
          Tie-Breaks zu anderen Patterns (discriminators){' '}
          <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({items.length})</span>
        </label>
        <button type="button" className="btn btn-sm" onClick={add}
          style={{ fontSize: '.7rem', padding: '2px 8px' }}>+ hinzufügen</button>
      </div>
      <div className="form-hint" style={{ fontSize: '.8rem', marginBottom: 6 }}>
        Pro Konflikt-Pattern eine Regel + ein Beispiel. Z.B. <code>vs M04 — Create-Verb + Material-Typ → M10. Erstell mir ein Quiz zu Photosynthese → M10.</code>
      </div>
      {items.length === 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF', fontStyle: 'italic', padding: '4px 0' }}>
          (keine Tie-Breaks definiert)
        </div>
      )}
      {items.map((d, idx) => (
        <div key={idx} style={{
          border: '1px solid #e5e7eb', borderRadius: 4, padding: 8, marginBottom: 6,
          background: '#fafafa',
        }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#6B7280' }}>vs Pattern:</span>
            <input
              className="form-input form-input-sm"
              value={d.vs || ''}
              placeholder="M04"
              onChange={e => update(idx, 'vs', e.target.value)}
              style={{ width: 80, fontSize: 12, fontFamily: 'ui-monospace, Menlo, monospace' }}
            />
            <button type="button" className="btn btn-danger btn-sm btn-icon"
              onClick={() => remove(idx)} title="Entfernen"
              style={{ padding: '2px 6px', fontSize: '.7rem', marginLeft: 'auto' }}>✕</button>
          </div>
          <input
            className="form-input form-input-sm"
            value={d.rule || ''}
            placeholder="Regel: Create-Verb + Material-Typ → M10. Was-Frage ohne Material-Typ → M04."
            onChange={e => update(idx, 'rule', e.target.value)}
            style={{ width: '100%', fontSize: 12, marginBottom: 4 }}
          />
          <input
            className="form-input form-input-sm"
            value={d.example || ''}
            placeholder="Beispiel: Erstell mir ein Quiz zu Photosynthese → M10. Was ist Photosynthese? → M04."
            onChange={e => update(idx, 'example', e.target.value)}
            style={{ width: '100%', fontSize: 12 }}
          />
        </div>
      ))}
    </div>
  );
}


// ── String-Liste (Add/Remove) — für forbidden_phrases / anti_patterns ──
function PatternStringList({ label, hint, values, onChange, placeholder }: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const items = values || [];
  const update = (idx: number, v: string) => {
    const next = [...items];
    next[idx] = v;
    onChange(next);
  };
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, '']);
  return (
    <div className="form-group">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label className="form-label" style={{ margin: 0 }}>
          {label} <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({items.length})</span>
        </label>
        <button type="button" className="btn btn-sm" onClick={add}
          style={{ fontSize: '.7rem', padding: '2px 8px' }}>+ hinzufügen</button>
      </div>
      {hint && <div className="form-hint" style={{ fontSize: '.8rem', marginBottom: 6 }}>{hint}</div>}
      {items.length === 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF', fontStyle: 'italic', padding: '4px 0' }}>
          (keine Einträge)
        </div>
      )}
      {items.map((v, idx) => (
        <div key={idx} style={{ display: 'flex', gap: 4, marginBottom: 3 }}>
          <input
            className="form-input form-input-sm"
            value={v}
            placeholder={placeholder}
            onChange={e => update(idx, e.target.value)}
            style={{ flex: 1, fontSize: 12 }}
          />
          <button type="button" className="btn btn-danger btn-sm btn-icon"
            onClick={() => remove(idx)} title="Entfernen"
            style={{ padding: '2px 6px', fontSize: '.7rem' }}>✕</button>
        </div>
      ))}
    </div>
  );
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
          <span className="text-sm text-muted">Keine Wissensbereiche vorhanden. Erstelle zuerst Bereiche unter Schicht 6 (Wissen).</span>
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

// ── Tab definition ───────────────────────────────────────────────────
// 5 tabs grouped by the 3-Phasen-Engine + Output/Tools + Anweisungen.
// Keeping the form modal-free: a tab is just a render-filter, the
// underlying editData state is shared. Save button is global (top
// right) so a click commits everything regardless of active tab.
// Welle E v4 (2026-05-25): Tabs "Phase 1 Gates" + "Phase 2 Scoring" raus.
// Patterns werden vom LLM-Hint ausgewählt, nicht mehr deterministisch
// gefiltert/bewertet. precondition_slots wandern nach "Slots" (eigener
// schlanker Tab, weil sie noch in phase3_modulate als Degradation-Flag
// aktiv sind und für M09/M10 inhaltlich wichtig bleiben).
type TabId = 'identity' | 'output' | 'tools' | 'slots' | 'instructions';

const TAB_DEFINITIONS: { id: TabId; label: string; icon: string }[] = [
  { id: 'identity',     label: 'Identität',           icon: '\u{1F9E9}' }, // 🧩
  { id: 'output',       label: 'Antwort-Form',        icon: '\u{1F3A8}' }, // 🎨
  { id: 'tools',        label: 'Tools & Wissen',      icon: '\u{1F527}' }, // 🔧
  { id: 'slots',        label: 'Slots & Degradation', icon: '\u{1F511}' }, // 🔑
  { id: 'instructions', label: 'Anweisungen',         icon: '\u{1F4DD}' }, // 📝
];

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
  const [activeTab, setActiveTab] = useState<TabId>('identity');

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

  // Save — Welle E v3 (2026-05-25): bevorzugt den strukturierten Backend-
  // PUT-Endpoint (/api/config/patterns), der via ruamel-Roundtrip
  // Kommentare erhält + Pydantic-validiert. Fallback auf den älteren
  // /api/config/file-Pfad nur wenn das neue Endpoint fehlt (404).
  const handleSave = async () => {
    if (!editData) return;
    setStatus('saving');

    // Build full payload — keep ALL patterns intact, only patch the edited one.
    const payload = patterns.map(p =>
      p.id === editData.id
        ? { ...editData, body_md: body }
        : p
    );

    try {
      const r = await fetch('/api/config/patterns', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patterns: payload }),
      });
      if (r.ok) {
        setStatus('saved');
        await onReload();
        setTimeout(() => setStatus('idle'), 2000);
        return;
      }
      // 404 → fall back to legacy file-based save (preserves backwards-compat
      // when the user is running an older backend without the new endpoint).
      if (r.status === 404 && editData.file) {
        const content = patternToFileContent(editData, body);
        const ok = await saveFile(editData.file, content);
        if (ok) {
          setOriginalRaw(content);
          setStatus('saved');
          setTimeout(() => setStatus('idle'), 2000);
          return;
        }
      }
      setStatus('error');
    } catch {
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
      // Welle E v4: gate_* + signal_* + page_bonus aus dem Default
      // entfernt — der LLM-Hint wählt das Pattern, deterministische
      // Filterung/Gewichtung ist deprecated.
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
                placeholder="z.B. M10-custom" autoFocus />
              <div className="form-hint">Eindeutige ID, z.B. M10-mein-pattern</div>
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

              {/* Tab bar — Block 2 Studio-UI Refactor (Sprint 6).
                  Splits the long pattern form into 6 logical tabs matching
                  the 3-Phasen-Engine. Underlying state stays a single
                  editData object so Save commits everything. */}
              <div
                className="pattern-tab-bar"
                style={{
                  display: 'flex',
                  gap: 4,
                  borderBottom: '2px solid #E5E7EB',
                  marginBottom: 20,
                  flexWrap: 'wrap',
                }}
                role="tablist"
              >
                {TAB_DEFINITIONS.map(t => {
                  const active = activeTab === t.id;
                  return (
                    <button
                      key={t.id}
                      role="tab"
                      aria-selected={active}
                      onClick={() => setActiveTab(t.id)}
                      style={{
                        background: 'none',
                        border: 'none',
                        padding: '10px 14px',
                        cursor: 'pointer',
                        borderBottom: active ? '3px solid #3B82F6' : '3px solid transparent',
                        marginBottom: -2,
                        fontWeight: active ? 600 : 500,
                        color: active ? '#1E3A8A' : '#4B5563',
                        fontSize: '.92rem',
                        transition: 'all .15s ease',
                      }}
                    >
                      <span style={{ marginRight: 6 }}>{t.icon}</span>
                      {t.label}
                    </button>
                  );
                })}
              </div>

              {/* Identity tab */}
              {activeTab === 'identity' && (
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
                <div className="form-hint" style={{ marginTop: 12, fontSize: '.85rem' }}>
                  Die Identität entscheidet, wie das Pattern in der Klassifikator-Pattern-Liste
                  auftaucht (Reihenfolge via <code>priority</code>) und ob es als Antwort, Frage
                  oder Vorschlag rendert. Slots & Degradation, Tools, Anweisungen stehen in den
                  weiteren Tabs.
                </div>
              </div>
              )}

              {/* Slots & Degradation (Welle E v4) */}
              {activeTab === 'slots' && (
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F511;</span> Slots & Degradation</div>
                <div className="form-group">
                  <label className="form-label">Precondition Slots (benötigte Entities)</label>
                  <ChipSelect
                    options={elements.entities.map(e => ({ id: e.id, label: e.label || e.id }))}
                    selected={editData.precondition_slots ?? []}
                    onChange={v => update('precondition_slots', v.filter(x => x !== '*'))}
                    colorClass="tag-purple"
                  />
                  <div className="form-hint" style={{ marginTop: 6, fontSize: '.85rem' }}>
                    Wenn nicht alle Slots gefüllt sind, setzt phase3_modulate ein{' '}
                    <code>degradation=true</code> Flag und meldet die fehlenden Slots
                    — der Antwort-Builder kann darauf reagieren (z. B. mit einer
                    Klärungs-Rückfrage). Anders als früher wird das Pattern NICHT mehr
                    eliminiert, der LLM-Hint bleibt der Selektor. Leer lassen, wenn
                    keine Slots erforderlich sind.
                  </div>
                </div>
                <div className="card" style={{
                  marginTop: 12, padding: 10, background: '#EFF6FF',
                  border: '1px solid #BFDBFE', fontSize: 12,
                }}>
                  <strong>Welle E v4+12 (Sprint K, 2026-05-27):</strong> Phase-1-Gates,
                  Phase-2-Scoring und die komplette Routing-Rule-Engine wurden entfernt.
                  Das Pattern wird vom LLM-Klassifikator-Hint gewählt; deterministische
                  Hard-Overrides liegen in <code>01-base/classify-overrides.yaml</code>
                  (Persona-Self-ID, Verb-Anker). Pattern-Definitionen brauchen daher
                  keine Gate-/Signal-Felder mehr — pflege hier nur Inhalt, Tools und
                  Antwort-Form.
                </div>
              </div>
              )}

              {/* Antwort-Form (vormals Phase 3 Output defaults) */}
              {activeTab === 'output' && (
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
              </div>
              )}

              {/* Tools & Wissen tab: sources + RAG areas + MCP tools */}
              {activeTab === 'tools' && (
              <>
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F4E6;</span> Quellen</div>
                <div className="form-row">
                  <div className="form-group">
                    <label className="form-label">Erlaubte Wissensquellen</label>
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
                    <div className="form-hint" style={{ marginTop: 6, fontSize: '.85rem' }}>
                      <code>mcp</code> = Tool-Aufrufe (Live-Daten), <code>rag</code> = Wissensbereiche
                      (statisches Wissen), <code>llm</code> = nur Sprachmodell ohne Tools. Mehrfach-Auswahl
                      möglich.
                    </div>
                  </div>
                </div>
              </div>

              {/* RAG Knowledge Areas — only when "rag" source is active */}
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

              {/* MCP Tools */}
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
                <div className="form-hint" style={{ marginTop: 6, fontSize: '.85rem' }}>
                  Nur ausgewählte Tools darf das Pattern aufrufen. Leere Liste = keine Tools.
                </div>
              </div>
              </>
              )}

              {/* Anweisungen tab: Welle E v3 — strukturiert + freier Body */}
              {activeTab === 'instructions' && (
              <div className="section">
                <div className="section-title"><span className="section-icon">&#x1F4DD;</span> Kernregel & Anweisungen</div>

                <div className="form-group">
                  <label className="form-label">Kernregel (core_rule)</label>
                  <textarea
                    className="form-textarea"
                    value={editData.core_rule ?? ''}
                    onChange={e => update('core_rule', e.target.value)}
                    placeholder="HART formulierte Hauptregel — 1–3 Sätze. Wird im Response-Prompt als Top-Block gerendert."
                    rows={3}
                    style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: '.9rem' }}
                  />
                  <div className="form-hint" style={{ marginTop: 6, fontSize: '.85rem' }}>
                    Die zentrale „HART"-Regel des Patterns. 1–3 Sätze. Wird im Antwort-Prompt als
                    eigene Sektion gerendert.
                  </div>
                </div>

                <PatternStringList
                  label="Verbotene Formulierungen (forbidden_phrases)"
                  hint='Konkrete Wortlaute die der Bot NICHT verwenden darf. Wird im Antwort-Prompt + Eval-Judge als Anti-Liste eingesetzt.'
                  values={editData.forbidden_phrases ?? []}
                  onChange={v => update('forbidden_phrases', v)}
                  placeholder='z.B. „Hier sind passende Sammlungen"'
                />

                <PatternStringList
                  label="Anti-Patterns (anti_patterns)"
                  hint="Falsche Handlungs-Strategien dieses Patterns — eine pro Bullet."
                  values={editData.anti_patterns ?? []}
                  onChange={v => update('anti_patterns', v)}
                  placeholder='z.B. „Suche statt Routing"'
                />

                {/* ── Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl ── */}
                <div className="card" style={{
                  marginTop: 16, marginBottom: 8, padding: 14,
                  background: '#f0f9ff', border: '1px solid #bae6fd',
                }}>
                  <div style={{ fontSize: '.82rem', color: '#0369a1', fontWeight: 600, marginBottom: 4 }}>
                    Pattern-Auswahl-Regeln (verbindet sich automatisch mit dem classify-Prompt + Eval-Judge)
                  </div>
                  <div style={{ fontSize: '.74rem', color: '#0369a1' }}>
                    Diese 4 Felder ersetzen die zentrale <code>classify-overrides.yaml</code>-Sektion
                    <code>pattern_disambiguators</code>. Sie wandern beim nächsten Turn automatisch in
                    den classify-Prompt, den response-Pattern-Brief und den Eval-Judge.
                  </div>
                </div>

                <PatternStringList
                  label="Einsetzen wenn (when_to_use)"
                  hint="Positive Auslöser-Bedingungen — Klassifizier wählt dieses Pattern wenn eine zutrifft."
                  values={editData.when_to_use ?? []}
                  onChange={v => update('when_to_use', v)}
                  placeholder='z.B. „Intent I05 + Topic + Material-Typ vorhanden"'
                />

                <PatternStringList
                  label="NICHT einsetzen wenn (when_not_to_use)"
                  hint="Negative Bedingungen — Klassifizier wählt ein anderes Pattern wenn eine zutrifft."
                  values={editData.when_not_to_use ?? []}
                  onChange={v => update('when_not_to_use', v)}
                  placeholder='z.B. „Topic fehlt → M03 (Slot-Klärung)"'
                />

                <PatternStringList
                  label="Typische User-Phrasen (trigger_phrases)"
                  hint="Konkrete Nutzer-Eingaben die dieses Pattern triggern. Werden als Few-Shot-Anker in den classify-Prompt geschoben."
                  values={editData.trigger_phrases ?? []}
                  onChange={v => update('trigger_phrases', v)}
                  placeholder='z.B. „Erstell mir ein Quiz zu X"'
                />

                <PatternDiscriminators
                  values={editData.discriminators ?? []}
                  onChange={v => update('discriminators', v)}
                />

                <div className="form-group">
                  <label className="form-label">Pattern-Brief (Markdown-Body)</label>
                  <textarea
                    className="form-textarea form-textarea-lg"
                    value={body}
                    onChange={e => setBody(e.target.value)}
                    placeholder="Pflicht-Antwort-Schema, Tabellen, Beispiele — pattern-spezifische Inhalte als freier Markdown."
                    spellCheck={false}
                    style={{ minHeight: 320, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: '.9rem' }}
                  />
                  <div className="form-hint" style={{ marginTop: 6, fontSize: '.85rem' }}>
                    Freier Markdown-Text für das Pflicht-Antwort-Schema, Tabellen, Persona-Quick-Reply-
                    Templates und sonstige pattern-spezifische Anweisungen. <strong>Kernregel,
                    forbidden_phrases und anti_patterns gehören NICHT hier rein</strong> — die haben
                    eigene strukturierte Felder oben.
                  </div>
                </div>
              </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
