'use client';

import { useState, useEffect, useCallback } from 'react';
import type { Elements, PersonaData, IntentData, StateData, EntityData, SignalData } from '@/app/page';

type DimTab = 'personas' | 'intents' | 'states' | 'entities' | 'signals';

interface Props {
  elements: Elements;
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
  createFile: (path: string, content: string) => Promise<boolean>;
  appendToYaml: (path: string, yamlSnippet: string) => Promise<boolean>;
}

// ── Tone-Modifier schema (Welle B.3 / C.5 — 2026-05) ────────────────
//
// Mirror der ToneModifier-Pydantic-Klasse im Backend. Wird vom
// Persona-Detail-View als Form-UI gerendert und über die
// /api/config/tone-modifiers REST-Endpoints persistiert.
interface ToneModifier {
  tone: string;
  length_bias: number;
  formality: string;  // 'duzen' | 'siezen' | 'wie_user'
  card_text_mode: string;  // 'minimal' | 'kurz' | 'explanation' | 'ausfuehrlich'
  override: boolean;
}

interface ToneModifiersPayload {
  modifiers: Record<string, ToneModifier>;
  default_modifier: ToneModifier;
}

const _DEFAULT_TONE_MOD: ToneModifier = {
  tone: 'locker',
  length_bias: 0.0,
  formality: 'wie_user',
  card_text_mode: 'minimal',
  override: false,
};

const _TONE_OPTIONS = [
  'locker', 'kollegial', 'ermutigend', 'warm', 'sachlich',
  'professionell', 'formell', 'spielerisch', 'einladend',
];
const _FORMALITY_OPTIONS = [
  { v: 'duzen', l: 'duzen' },
  { v: 'siezen', l: 'siezen' },
  { v: 'wie_user', l: 'wie der User schreibt' },
];
const _CARD_MODE_OPTIONS = [
  { v: 'minimal', l: 'minimal — nur Titel' },
  { v: 'kurz', l: 'kurz — Titel + 1 Satz' },
  { v: 'explanation', l: 'explanation — mehr Kontext' },
  { v: 'ausfuehrlich', l: 'ausfuehrlich — volle Karten' },
];

// ── Persona detail editor ────────────────────────────────────────────
function PersonaDetail({ persona, loadFile, saveFile }: {
  persona: PersonaData;
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
}) {
  const [content, setContent] = useState('');
  const [original, setOriginal] = useState('');
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  // Welle C.5: Modifier-State — separat von Markdown-Content, eigener Save-Flow.
  const [modifiers, setModifiers] = useState<ToneModifiersPayload | null>(null);
  const [modOrig, setModOrig] = useState<string>('');  // JSON-Stringified compare
  const [modStatus, setModStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  useEffect(() => {
    if (!persona.file) return;
    (async () => {
      const text = await loadFile(persona.file!);
      setContent(text);
      setOriginal(text);
      setStatus('idle');
    })();
  }, [persona.file, loadFile]);

  // Lade alle Modifier einmal (kleine Map mit 9 Einträgen). Wird beim
  // Speichern komplett zurückgeschrieben — der State bleibt konsistent
  // zwischen Persona-Wechseln.
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('/api/config/tone-modifiers');
        if (!r.ok) return;
        const data = await r.json() as ToneModifiersPayload;
        setModifiers(data);
        setModOrig(JSON.stringify(data));
      } catch { /* nicht-blockierend */ }
    })();
  }, []);

  const personaMod: ToneModifier = (modifiers?.modifiers?.[persona.id]) ?? _DEFAULT_TONE_MOD;

  const updateModField = <K extends keyof ToneModifier>(field: K, value: ToneModifier[K]) => {
    if (!modifiers) return;
    const current = modifiers.modifiers[persona.id] ?? _DEFAULT_TONE_MOD;
    const updated: ToneModifiersPayload = {
      ...modifiers,
      modifiers: { ...modifiers.modifiers, [persona.id]: { ...current, [field]: value } },
    };
    setModifiers(updated);
  };

  const modDirty = modifiers !== null && JSON.stringify(modifiers) !== modOrig;

  const handleSaveModifier = async () => {
    if (!modifiers) return;
    setModStatus('saving');
    try {
      const r = await fetch('/api/config/tone-modifiers', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(modifiers),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json() as ToneModifiersPayload;
      setModifiers(data);
      setModOrig(JSON.stringify(data));
      setModStatus('saved');
      setTimeout(() => setModStatus('idle'), 2000);
    } catch {
      setModStatus('error');
    }
  };

  const isDirty = content !== original;

  const handleSave = async () => {
    if (!persona.file) return;
    setStatus('saving');
    const ok = await saveFile(persona.file, content);
    if (ok) { setOriginal(content); setStatus('saved'); setTimeout(() => setStatus('idle'), 2000); }
    else setStatus('error');
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>{persona.id}: {persona.label}</h3>
          {persona.description && <div className="text-sm text-muted">{persona.description}</div>}
          <div className="text-xs text-muted font-mono mt-2">{persona.file}</div>
        </div>
        <div className="btn-group">
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error">Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!isDirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Markdown speichern'}
          </button>
        </div>
      </div>
      {persona.hints && persona.hints.length > 0 && (
        <div className="form-group">
          <label className="form-label">Erkennungshinweise</label>
          <div className="tags">
            {persona.hints.map((h, i) => <span key={i} className="tag tag-blue">{h}</span>)}
          </div>
        </div>
      )}

      {/* ── Welle C.5: Tonalitäts-Modifier (aus 01-base/tone-modifiers.yaml) ── */}
      <div style={{
        background: '#F9FAFB', border: '1px solid #E5E7EB', borderRadius: 8,
        padding: 14, marginBottom: 16,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div>
            <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: '#1F2937' }}>
              Tonalitäts-Modifier
            </h4>
            <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>
              Wie soll BOERDi mit dieser Persona klingen? Diese Werte überschreiben Pattern-Defaults für tone/length/formality/card_text_mode.
              {' '}
              Quelle:{' '}
              <code style={{ background: '#F3F4F6', padding: '0 4px', borderRadius: 2 }}>
                01-base/tone-modifiers.yaml
              </code>
            </div>
          </div>
          <div className="btn-group">
            {modStatus === 'saved' && <span className="save-status saved">Gespeichert</span>}
            {modStatus === 'error' && <span className="save-status error">Fehler</span>}
            <button
              className="btn btn-primary btn-sm"
              onClick={handleSaveModifier}
              disabled={!modDirty || modStatus === 'saving' || !modifiers}
              style={{ minWidth: 140 }}
            >
              {modStatus === 'saving' ? 'Speichert...' : 'Modifier speichern'}
            </button>
          </div>
        </div>

        {!modifiers && (
          <div style={{ fontSize: 12, color: '#9CA3AF', fontStyle: 'italic' }}>
            Lade Tonalitäts-Daten …
          </div>
        )}

        {modifiers && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
            <div>
              <label className="form-label" style={{ fontSize: 12 }}>Tone</label>
              <select
                className="form-input"
                value={personaMod.tone}
                onChange={e => updateModField('tone', e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
              >
                {_TONE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                {/* Auch einen aktuellen freien Wert weiter anbieten, falls
                    die YAML einen Custom-Eintrag enthält. */}
                {!_TONE_OPTIONS.includes(personaMod.tone) && (
                  <option value={personaMod.tone}>{personaMod.tone} (custom)</option>
                )}
              </select>
            </div>

            <div>
              <label className="form-label" style={{ fontSize: 12 }}>
                Length-Bias: {personaMod.length_bias > 0 ? '+' : ''}{personaMod.length_bias.toFixed(2)}
                {' '}
                <span style={{ color: '#6B7280', fontWeight: 400 }}>
                  ({personaMod.length_bias > 0.15 ? 'eine Stufe länger' :
                    personaMod.length_bias < -0.15 ? 'eine Stufe kürzer' : 'unverändert'})
                </span>
              </label>
              <input
                type="range"
                min={-0.3} max={0.3} step={0.05}
                value={personaMod.length_bias}
                onChange={e => updateModField('length_bias', parseFloat(e.target.value))}
                style={{ width: '100%' }}
              />
            </div>

            <div>
              <label className="form-label" style={{ fontSize: 12 }}>Anrede (Formality)</label>
              <select
                className="form-input"
                value={personaMod.formality}
                onChange={e => updateModField('formality', e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
              >
                {_FORMALITY_OPTIONS.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
              </select>
            </div>

            <div>
              <label className="form-label" style={{ fontSize: 12 }}>Card-Text-Mode</label>
              <select
                className="form-input"
                value={personaMod.card_text_mode}
                onChange={e => updateModField('card_text_mode', e.target.value)}
                style={{ width: '100%', fontSize: 13 }}
              >
                {_CARD_MODE_OPTIONS.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
              </select>
            </div>

            <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                type="checkbox"
                id={`override-${persona.id}`}
                checked={personaMod.override}
                onChange={e => updateModField('override', e.target.checked)}
              />
              <label htmlFor={`override-${persona.id}`} style={{ fontSize: 12, cursor: 'pointer' }}>
                <strong>Override aktiv</strong> — Modifier überschreibt Pattern-Defaults.
                <span style={{ color: '#6B7280', marginLeft: 4 }}>
                  (z.B. P-W-SL Duzen-Regel siegt über Pattern-Tonalität.)
                </span>
              </label>
            </div>
          </div>
        )}
      </div>

      <label className="form-label" style={{ marginTop: 4 }}>
        Persona-Markdown ({persona.file})
      </label>
      <textarea
        className="form-textarea form-textarea-lg"
        style={{ minHeight: 'calc(100vh - 560px)' }}
        value={content}
        onChange={e => setContent(e.target.value)}
        onKeyDown={e => {
          if (e.key === 's' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (isDirty) handleSave(); }
        }}
        spellCheck={false}
      />
    </div>
  );
}

// ── Editable Intent Table ───────────────────────────────────────────
function IntentEditor({ intents, loadFile, saveFile, onReload }: {
  intents: IntentData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<IntentData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRows(intents.map(i => ({ ...i })));
    setDirty(false);
  }, [intents]);

  const updateRow = (idx: number, field: string, value: string) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], [field]: value };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    // Rebuild YAML from rows
    const lines = [
      '# Intent-Definitionen',
      '# Jeder Intent hat eine ID, ein Label und eine Beschreibung.',
      '# Diese werden für die LLM-Klassifikation und im Studio verwendet.',
      '',
      'intents:',
    ];
    for (const r of rows) {
      lines.push(`  - id: ${r.id}`);
      lines.push(`    label: "${r.label}"`);
      if (r.description) lines.push(`    description: "${r.description}"`);
    }
    const ok = await saveFile('04-intents/intents.yaml', lines.join('\n') + '\n');
    if (ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-intents/intents.yaml</div>
        <div className="btn-group">
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error">Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 140 }}>ID</th>
                <th style={{ width: 200 }}>Label</th>
                <th>Beschreibung</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <input className="form-input form-input-sm" value={r.id}
                      onChange={e => updateRow(idx, 'id', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.label}
                      onChange={e => updateRow(idx, 'label', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.description || ''}
                      onChange={e => updateRow(idx, 'description', e.target.value)} />
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm btn-icon"
                      onClick={() => deleteRow(idx)} title="Löschen"
                      style={{ padding: '2px 6px', fontSize: '.7rem' }}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

// ── Editable State Table ────────────────────────────────────────────
function StateEditor({ states, loadFile, saveFile, onReload }: {
  states: StateData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<StateData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRows(states.map(s => ({ ...s })));
    setDirty(false);
  }, [states]);

  const updateRow = (idx: number, field: string, value: string) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], [field]: value };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    const lines = [
      '# State-Definitionen',
      '# Jeder State repräsentiert einen Gesprächszustand.',
      '',
      'states:',
    ];
    for (const r of rows) {
      lines.push(`  - id: ${r.id}`);
      lines.push(`    label: "${r.label}"`);
      if (r.cluster) lines.push(`    cluster: ${r.cluster}`);
      if (r.description) lines.push(`    description: "${r.description}"`);
    }
    const ok = await saveFile('04-states/states.yaml', lines.join('\n') + '\n');
    if (ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-states/states.yaml</div>
        <div className="btn-group">
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error">Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 120 }}>ID</th>
                <th style={{ width: 180 }}>Label</th>
                <th style={{ width: 120 }}>Cluster</th>
                <th>Beschreibung</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <input className="form-input form-input-sm" value={r.id}
                      onChange={e => updateRow(idx, 'id', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.label}
                      onChange={e => updateRow(idx, 'label', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.cluster || ''}
                      onChange={e => updateRow(idx, 'cluster', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.description || ''}
                      onChange={e => updateRow(idx, 'description', e.target.value)} />
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm btn-icon"
                      onClick={() => deleteRow(idx)} title="Löschen"
                      style={{ padding: '2px 6px', fontSize: '.7rem' }}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

// ── Editable Entity Table ───────────────────────────────────────────
function EntityEditor({ entities, loadFile, saveFile, onReload }: {
  entities: EntityData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<(EntityData & { examplesStr?: string })[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRows(entities.map(e => ({ ...e, examplesStr: (e.examples || []).join(', ') })));
    setDirty(false);
  }, [entities]);

  const updateRow = (idx: number, field: string, value: string) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], [field]: value };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    const lines = [
      '# Entity-/Slot-Definitionen',
      '# Diese Entities werden aus der Nutzernachricht extrahiert und akkumuliert.',
      '',
      'entities:',
    ];
    for (const r of rows) {
      lines.push(`  - id: ${r.id}`);
      if (r.label) lines.push(`    label: "${r.label}"`);
      lines.push(`    type: ${r.type || 'string'}`);
      const examples = (r.examplesStr || '').split(',').map(s => s.trim()).filter(Boolean);
      if (examples.length > 0) {
        lines.push(`    examples:`);
        for (const ex of examples) lines.push(`      - "${ex}"`);
      } else {
        lines.push(`    examples: []`);
      }
    }
    const ok = await saveFile('04-entities/entities.yaml', lines.join('\n') + '\n');
    if (ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-entities/entities.yaml</div>
        <div className="btn-group">
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error">Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 120 }}>ID</th>
                <th style={{ width: 160 }}>Label</th>
                <th style={{ width: 100 }}>Typ</th>
                <th>Beispiele (kommagetrennt)</th>
                <th style={{ width: 40 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <input className="form-input form-input-sm" value={r.id}
                      onChange={e => updateRow(idx, 'id', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.label || ''}
                      onChange={e => updateRow(idx, 'label', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.type || 'string'}
                      onChange={e => updateRow(idx, 'type', e.target.value)} />
                  </td>
                  <td>
                    <input className="form-input form-input-sm" value={r.examplesStr || ''}
                      onChange={e => updateRow(idx, 'examplesStr', e.target.value)}
                      placeholder="z.B. Mathematik, Deutsch, Biologie" />
                  </td>
                  <td>
                    <button className="btn btn-danger btn-sm btn-icon"
                      onClick={() => deleteRow(idx)} title="Löschen"
                      style={{ padding: '2px 6px', fontSize: '.7rem' }}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

// ── Editable Signal Table (structured columns) ─────────────────────
const TONE_OPTIONS = [
  'sachlich', 'empathisch', 'beruhigend', 'niedrigschwellig', 'spielerisch',
  'transparent', 'einladend', 'empfehlend', 'orientierend', 'analytisch',
  'belegend', 'proaktiv',
];
const LENGTH_OPTIONS = ['kurz', 'mittel', 'lang'];
const BOOL_FLAGS = [
  { key: 'skip_intro',  label: 'Intro\u00ADskip',    title: 'Skip Intro: Bot überspringt Begrüßung, kommt direkt zur Sache' },
  { key: 'one_option',  label: 'Nur 1\u00ADOption',   title: 'Nur 1 Option: Bot zeigt nur ein Ergebnis, um nicht zu überfordern' },
  { key: 'show_more',   label: 'Mehr\u00ADzeigen',    title: 'Mehr zeigen: Bot bietet proaktiv an, weitere Ergebnisse zu zeigen' },
  { key: 'add_sources', label: 'Quellen\u00ADbelege', title: 'Quellenbelege: Bot fügt Quellennachweise und Links hinzu' },
] as const;

interface SignalRow {
  id: string;
  dimension: string;
  tone: string;
  length: string;
  skip_intro: boolean;
  one_option: boolean;
  show_more: boolean;
  add_sources: boolean;
}

function signalToRow(s: SignalData): SignalRow {
  const m = s.modulations || {};
  return {
    id: s.id,
    dimension: s.dimension || '',
    tone: m.tone || '',
    length: m.length || '',
    skip_intro: m.skip_intro === true || m.skip_intro === 'true',
    one_option: m.one_option === true || m.one_option === 'true',
    show_more: m.show_more === true || m.show_more === 'true',
    add_sources: m.add_sources === true || m.add_sources === 'true',
  };
}

function SignalEditor({ signals, loadFile, saveFile, onReload }: {
  signals: SignalData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<SignalRow[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setRows(signals.map(signalToRow));
    setDirty(false);
  }, [signals]);

  const updateRow = (idx: number, field: string, value: any) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], [field]: value };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    const lines = [
      '# Signal-Modulationen',
      '# Jedes Signal kann Ton, Länge und weitere Ausgabe-Parameter modulieren.',
      '',
      'signals:',
    ];
    for (const r of rows) {
      lines.push(`  - id: ${r.id}`);
      if (r.dimension) lines.push(`    dimension: ${r.dimension}`);
      const mods: string[] = [];
      if (r.tone) mods.push(`      tone: ${r.tone}`);
      if (r.length) mods.push(`      length: ${r.length}`);
      if (r.skip_intro) mods.push(`      skip_intro: true`);
      if (r.one_option) mods.push(`      one_option: true`);
      if (r.show_more) mods.push(`      show_more: true`);
      if (r.add_sources) mods.push(`      add_sources: true`);
      if (mods.length > 0) {
        lines.push(`    modulations:`);
        lines.push(...mods);
      }
    }
    const ok = await saveFile('04-signals/signal-modulations.yaml', lines.join('\n') + '\n');
    if (ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-signals/signal-modulations.yaml</div>
        <div className="btn-group">
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error">Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      <div className="card">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 150 }}>Signal</th>
                <th style={{ width: 120 }}>Ton</th>
                <th style={{ width: 90 }}>Länge</th>
                {BOOL_FLAGS.map(f => (
                  <th key={f.key} style={{ width: 72, textAlign: 'center', cursor: 'help' }} title={f.title}>
                    {f.label}
                  </th>
                ))}
                <th style={{ width: 36 }}></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={idx}>
                  <td>
                    <input className="form-input form-input-sm" value={r.id}
                      onChange={e => updateRow(idx, 'id', e.target.value)} />
                  </td>
                  <td>
                    <select className="form-select form-input-sm"
                      value={r.tone}
                      onChange={e => updateRow(idx, 'tone', e.target.value)}>
                      <option value="">–</option>
                      {TONE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </td>
                  <td>
                    <select className="form-select form-input-sm"
                      value={r.length}
                      onChange={e => updateRow(idx, 'length', e.target.value)}>
                      <option value="">–</option>
                      {LENGTH_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </td>
                  {BOOL_FLAGS.map(f => (
                    <td key={f.key} style={{ textAlign: 'center' }}>
                      <input type="checkbox" checked={r[f.key]}
                        onChange={e => updateRow(idx, f.key, e.target.checked)}
                        title={f.title}
                        style={{ width: 16, height: 16, cursor: 'pointer' }} />
                    </td>
                  ))}
                  <td>
                    <button className="btn btn-danger btn-sm btn-icon"
                      onClick={() => deleteRow(idx)} title="Löschen"
                      style={{ padding: '2px 6px', fontSize: '.7rem' }}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────
export default function ElementEditor({ elements, loadFile, saveFile, onReload, createFile, appendToYaml }: Props) {
  const [tab, setTab] = useState<DimTab>('personas');
  const [selectedPersona, setSelectedPersona] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newId, setNewId] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [newDesc, setNewDesc] = useState('');

  const personas = elements.personas || [];
  const intents = elements.intents || [];
  const states = elements.states || [];
  const entities = elements.entities || [];
  const signals = elements.signals || [];

  const handleCreate = async () => {
    const id = newId.trim();
    const label = newLabel.trim() || id;
    if (!id) return;

    let ok = false;
    if (tab === 'personas') {
      const filename = id.toLowerCase().replace(/[^a-z0-9-]/g, '-') + '.md';
      const path = `04-personas/${filename}`;
      const content = `---\nid: ${id}\nlabel: ${label}\ndescription: "${newDesc}"\nhints: []\n---\n\n# ${label}\n\nBeschreibe hier die Persona.`;
      ok = await createFile(path, content);
      if (ok) setSelectedPersona(id);
    } else if (tab === 'intents') {
      const snippet = `  - id: ${id}\n    label: "${label}"\n    description: "${newDesc}"`;
      ok = await appendToYaml('04-intents/intents.yaml', snippet);
    } else if (tab === 'states') {
      const snippet = `  - id: ${id}\n    label: "${label}"\n    description: "${newDesc}"\n    cluster: general`;
      ok = await appendToYaml('04-states/states.yaml', snippet);
    } else if (tab === 'entities') {
      const snippet = `  - id: ${id}\n    label: "${label}"\n    type: string\n    examples: []`;
      ok = await appendToYaml('04-entities/entities.yaml', snippet);
    } else if (tab === 'signals') {
      const snippet = `  - id: ${id}\n    dimension: custom\n    modulations:\n      tone: sachlich`;
      ok = await appendToYaml('04-signals/signal-modulations.yaml', snippet);
    }

    if (ok) {
      setShowCreateDialog(false);
      setNewId('');
      setNewLabel('');
      setNewDesc('');
      await onReload();
    }
  };

  const createLabels: Record<DimTab, { title: string; idHint: string; idPlaceholder: string }> = {
    personas: { title: 'Neue Persona', idHint: 'z.B. P-NEW', idPlaceholder: 'P-NEW' },
    intents: { title: 'Neuer Intent', idHint: 'z.B. INT-NEW-01', idPlaceholder: 'INT-NEW-01' },
    states: { title: 'Neuer State', idHint: 'z.B. state-new', idPlaceholder: 'state-new' },
    entities: { title: 'Neue Entity', idHint: 'z.B. entity-name', idPlaceholder: 'entity-name' },
    signals: { title: 'Neues Signal', idHint: 'z.B. sig-custom', idPlaceholder: 'sig-custom' },
  };

  return (
    <div>
      <div className="page-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div className="page-title">Dimensionen</div>
          <div className="page-subtitle">Schicht 4: Klassifikations-Dimensionen, die jeden Nutzer-Input einordnen.</div>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreateDialog(true)}>+ Neu</button>
      </div>

      {/* Dimensionen-Übersicht — listet alle 7 Dimensionen,
          inkl. der nicht-editierbaren (Turn-Count / Tonalitäts-Modifier),
          damit Studio-User wissen WAS pro Turn klassifiziert wird. */}
      <div className="card" style={{ marginBottom: 16, background: '#F9FAFB', padding: '12px 16px' }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>
          Pro Nutzer-Turn produziert der Classifier (<code>llm_service.classify_input</code>)
          folgende Dimensionen — die fünf bearbeitbaren als Tabs unten, die zwei restlichen
          sind Laufzeit-Werte bzw. an Personas gekoppelt:
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8, fontSize: 12 }}>
          <div><strong style={{ color: '#1F2937' }}>👤 Personas ({personas.length})</strong> — WER fragt</div>
          <div><strong style={{ color: '#1F2937' }}>🎯 Intents ({intents.length})</strong> — WAS will der/die User:in</div>
          <div><strong style={{ color: '#1F2937' }}>🌀 States ({states.length})</strong> — wo im Gespräch sind wir</div>
          <div><strong style={{ color: '#1F2937' }}>🏷 Entities ({entities.length})</strong> — Slots: Fach/Stufe/Thema/Medientyp/Material-Typ</div>
          <div><strong style={{ color: '#1F2937' }}>📡 Signale ({signals.length})</strong> — Stimmung/Erfahrung/Eile/Skepsis</div>
          <div style={{ color: '#6B7280' }}>
            <strong style={{ color: '#374151' }}>🔁 Turn-Count</strong> — laufende Turn-Nummer (1, 2, 3…) der Session, kein Konfig-Element. Wird in <code>quality_logs.turn_count</code> persistiert und steuert State-Eskalation (state-1 → state-5 → state-6) sowie Soft-Probing-Cooldowns.
          </div>
          <div style={{ color: '#6B7280' }}>
            <strong style={{ color: '#374151' }}>🎚️ Tonalitäts-Modifier</strong> — pro Persona im Frontmatter (<code>tone</code>, <code>length_bias</code>, <code>formality</code>, <code>card_text_mode</code>, <code>override</code>). Editor unter dem Personas-Tab → Detailansicht.
          </div>
        </div>
      </div>

      {/* Create Dialog */}
      {showCreateDialog && (
        <div className="dialog-overlay" onClick={() => setShowCreateDialog(false)}>
          <div className="dialog" onClick={e => e.stopPropagation()}>
            <div className="dialog-title">{createLabels[tab].title} anlegen</div>
            <div className="form-group">
              <label className="form-label">ID</label>
              <input className="form-input" value={newId} onChange={e => setNewId(e.target.value)}
                placeholder={createLabels[tab].idPlaceholder} autoFocus />
              <div className="form-hint">{createLabels[tab].idHint}</div>
            </div>
            <div className="form-group">
              <label className="form-label">Label</label>
              <input className="form-input" value={newLabel} onChange={e => setNewLabel(e.target.value)}
                placeholder="Anzeigename" />
            </div>
            {(tab === 'personas' || tab === 'intents' || tab === 'states') && (
              <div className="form-group">
                <label className="form-label">Beschreibung</label>
                <input className="form-input" value={newDesc} onChange={e => setNewDesc(e.target.value)}
                  placeholder="Kurze Beschreibung"
                  onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }} />
              </div>
            )}
            <div className="btn-group" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
              <button className="btn btn-secondary" onClick={() => setShowCreateDialog(false)}>Abbrechen</button>
              <button className="btn btn-primary" onClick={handleCreate} disabled={!newId.trim()}>Erstellen</button>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="tabs">
        {([
          ['personas', 'Personas', personas.length],
          ['intents', 'Intents', intents.length],
          ['states', 'States', states.length],
          ['entities', 'Entities', entities.length],
          ['signals', 'Signale', signals.length],
        ] as [DimTab, string, number][]).map(([id, label, count]) => (
          <button key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {label}<span className="tab-count">{count}</span>
          </button>
        ))}
      </div>

      {/* ── Personas ──────────────────────────────────────── */}
      {tab === 'personas' && (
        <div className="split-layout" style={{ gridTemplateColumns: '260px 1fr' }}>
          <div className="split-left">
            {personas.map(p => (
              <div
                key={p.id}
                className={`pattern-item ${selectedPersona === p.id ? 'selected' : ''}`}
                onClick={() => setSelectedPersona(p.id)}
              >
                <span className="pattern-id" style={{ fontSize: '.65rem' }}>{p.id}</span>
                <span className="pattern-label">{p.label}</span>
              </div>
            ))}
          </div>
          <div className="split-right">
            {selectedPersona ? (
              <PersonaDetail
                persona={personas.find(p => p.id === selectedPersona)!}
                loadFile={loadFile}
                saveFile={saveFile}
              />
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">{'\u{1F464}'}</div>
                <div className="empty-state-text">Persona auswählen</div>
                <div className="empty-state-hint">Wähle links eine Persona zum Bearbeiten.</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Intents ───────────────────────────────────────── */}
      {tab === 'intents' && (
        <IntentEditor intents={intents} loadFile={loadFile} saveFile={saveFile} onReload={onReload} />
      )}

      {/* ── States ────────────────────────────────────────── */}
      {tab === 'states' && (
        <StateEditor states={states} loadFile={loadFile} saveFile={saveFile} onReload={onReload} />
      )}

      {/* ── Entities ──────────────────────────────────────── */}
      {tab === 'entities' && (
        <EntityEditor entities={entities} loadFile={loadFile} saveFile={saveFile} onReload={onReload} />
      )}

      {/* ── Signals ───────────────────────────────────────── */}
      {tab === 'signals' && (
        <SignalEditor signals={signals} loadFile={loadFile} saveFile={saveFile} onReload={onReload} />
      )}
    </div>
  );
}
