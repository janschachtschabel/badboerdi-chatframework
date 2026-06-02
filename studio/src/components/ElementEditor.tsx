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

// ── Persona Form-Editor (Welle E v2, 2026-05-25) ─────────────────────
//
// Alle strukturierten Daten leben jetzt im YAML-Frontmatter — Marker,
// Anti-Marker, Diskriminatoren, Ziele, Regeln, Modifier. Body ist nur
// noch optionale Persönlichkeits-Prosa.
// Save geht durch PUT /api/config/personas (atomar für alle Personas
// gemeinsam; Backend schreibt einzelne MD-Files pro Persona).
function PersonaDetail({ persona, allPersonas, allIntents, onPersonaChange, onSaveAll, saveStatus, saveError }: {
  persona: PersonaData;
  allPersonas: PersonaData[];
  allIntents: IntentData[];
  onPersonaChange: (patch: Partial<PersonaData>) => void;
  onSaveAll: () => Promise<void>;
  saveStatus: 'idle' | 'saving' | 'saved' | 'error';
  saveError: string;
}) {
  const otherPersonaIds = allPersonas
    .map(p => p.id)
    .filter(pid => pid !== persona.id);
  const allIntentIds = allIntents.map(i => i.id);

  // Tonalitäts-Defaults wenn das Frontmatter ein Feld nicht setzt.
  const tone = persona.tone ?? 'locker';
  const lengthBias = typeof persona.length_bias === 'number' ? persona.length_bias : 0;
  const formality = persona.formality ?? 'wie_user';
  const cardTextMode = persona.card_text_mode ?? 'minimal';
  const override = persona.override ?? false;

  return (
    <div>
      {/* Header mit Save-Button — Save ist global für alle Personas */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>{persona.id}: {persona.label}</h3>
          <div className="text-xs text-muted font-mono mt-1">{persona.file || `04-personas/${persona.id.toLowerCase().replace('p-', '')}.md`}</div>
        </div>
        <div className="btn-group">
          {saveStatus === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {saveStatus === 'error' && <span className="save-status error" title={saveError}>Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={onSaveAll} disabled={saveStatus === 'saving'}>
            {saveStatus === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      {saveError && (
        <div style={{
          background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 4,
          padding: 8, marginBottom: 12, fontSize: 12, color: '#7F1D1D',
        }}>{saveError}</div>
      )}

      {/* Welle E v4 (2026-05-25) — Verantwortlichkeits-Hinweis */}
      <div style={{
        background: '#EFF6FF', border: '1px solid #BFDBFE',
        borderRadius: 6, padding: '8px 10px', marginBottom: 12,
        fontSize: 12, color: '#1E3A8A',
      }}>
        <strong>Persona steuert Stil und Anrede, nicht das Pattern.</strong>{' '}
        Tone, Length-Bias, Formality und Card-Mode landen direkt im Antwort-Prompt.
        Die <em>Klassifikations-Marker</em> (positiv/anti/discriminators) helfen dem
        LLM-Klassifikator nur, die Persona zuverlässig zu erkennen — sie wählen kein
        Pattern aus.
      </div>

      {/* Stammdaten */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 8, marginBottom: 12 }}>
        <div>
          <label className="form-label" style={{ fontSize: 12 }}>ID</label>
          <input className="form-input form-input-sm" value={persona.id}
            onChange={e => onPersonaChange({ id: e.target.value })}
            style={{ fontFamily: 'monospace', fontWeight: 600 }} />
        </div>
        <div>
          <label className="form-label" style={{ fontSize: 12 }}>Label</label>
          <input className="form-input form-input-sm" value={persona.label}
            onChange={e => onPersonaChange({ label: e.target.value })} />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label className="form-label" style={{ fontSize: 12 }}>Kurzbeschreibung</label>
          <input className="form-input form-input-sm"
            value={persona.description || ''}
            placeholder="1–2 Sätze: wer ist diese Persona, wie klingt sie?"
            onChange={e => onPersonaChange({ description: e.target.value })} />
        </div>
      </div>

      {/* Tonalitäts-Modifier */}
      <div style={{
        background: '#F9FAFB', border: '1px solid #E5E7EB', borderRadius: 8,
        padding: 12, marginBottom: 12,
      }}>
        <h4 style={{ margin: 0, fontSize: 13, fontWeight: 600, color: '#1F2937', marginBottom: 10 }}>
          Tonalitäts-Modifier
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>Tone</label>
            <select className="form-input form-input-sm" value={tone}
              onChange={e => onPersonaChange({ tone: e.target.value })}
              style={{ width: '100%', fontSize: 13 }}>
              {_TONE_OPTIONS.map(o => <option key={o} value={o}>{o}</option>)}
              {!_TONE_OPTIONS.includes(tone) && (
                <option value={tone}>{tone} (custom)</option>
              )}
            </select>
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>
              Length-Bias: {lengthBias > 0 ? '+' : ''}{lengthBias.toFixed(2)}
              <span style={{ color: '#6B7280', fontWeight: 400 }}>
                {' '}({lengthBias > 0.15 ? 'eine Stufe länger' :
                       lengthBias < -0.15 ? 'eine Stufe kürzer' : 'unverändert'})
              </span>
            </label>
            <input type="range" min={-0.3} max={0.3} step={0.05}
              value={lengthBias}
              onChange={e => onPersonaChange({ length_bias: parseFloat(e.target.value) })}
              style={{ width: '100%' }} />
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>Anrede (Formality)</label>
            <select className="form-input form-input-sm" value={formality}
              onChange={e => onPersonaChange({ formality: e.target.value })}
              style={{ width: '100%', fontSize: 13 }}>
              {_FORMALITY_OPTIONS.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
            </select>
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>Card-Text-Mode</label>
            <select className="form-input form-input-sm" value={cardTextMode}
              onChange={e => onPersonaChange({ card_text_mode: e.target.value })}
              style={{ width: '100%', fontSize: 13 }}>
              {_CARD_MODE_OPTIONS.map(o => <option key={o.v} value={o.v}>{o.l}</option>)}
            </select>
          </div>
          <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="checkbox" id={`override-${persona.id}`}
              checked={override}
              onChange={e => onPersonaChange({ override: e.target.checked })} />
            <label htmlFor={`override-${persona.id}`} style={{ fontSize: 12, cursor: 'pointer' }}>
              <strong>Override aktiv</strong> — Modifier überschreibt Pattern-Defaults.
            </label>
          </div>
        </div>
      </div>

      {/* Klassifikations-Felder */}
      <StringListField
        label="Positiv-Marker"
        hint="Phrasen, die diese Persona aktiv erkennen lassen. P-AND lässt das leer."
        values={persona.positive_markers || []}
        onChange={v => onPersonaChange({ positive_markers: v, hints: v })}
        placeholder='z.B. „ich verstehe nicht", „mein Kind", „Wahlkreis"'
      />

      <RecordListField
        label="Anti-Marker"
        hint="Phrasen, die NICHT zu dieser Persona gehören — wohin sie statt dessen routen."
        values={persona.anti_markers || []}
        onChange={v => onPersonaChange({ anti_markers: v })}
        makeEmpty={() => ({ phrase: '', redirect_to: '', rationale: '' })}
        renderItem={(item, update) => (
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 110px 1fr', gap: 6, paddingRight: 24 }}>
            <input className="form-input form-input-sm"
              value={item.phrase}
              placeholder="Phrase (pipe-separiert ok)"
              onChange={e => update({ phrase: e.target.value })}
              style={{ fontSize: 12 }} />
            <select className="form-input form-input-sm"
              value={item.redirect_to || ''}
              onChange={e => update({ redirect_to: e.target.value })}
              style={{ fontSize: 12 }}>
              <option value="">→ Persona</option>
              {otherPersonaIds.map(pid => <option key={pid} value={pid}>{pid}</option>)}
            </select>
            <input className="form-input form-input-sm"
              value={item.rationale || ''}
              placeholder="Warum?"
              onChange={e => update({ rationale: e.target.value })}
              style={{ fontSize: 12 }} />
          </div>
        )}
      />

      <RecordListField
        label="Diskriminatoren (Cross-Persona-Disambig)"
        hint="Wann ist es eher die andere Persona? Mit Beispielen für beide Seiten."
        values={persona.discriminators || []}
        onChange={v => onPersonaChange({ discriminators: v })}
        makeEmpty={() => ({ vs: '', rule: '', example_a: '', example_b: '' })}
        renderItem={(item, update) => (
          <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 6, paddingRight: 24 }}>
            <select className="form-input form-input-sm"
              value={item.vs}
              onChange={e => update({ vs: e.target.value })}
              style={{ fontSize: 12 }}>
              <option value="">vs. ?</option>
              {otherPersonaIds.map(pid => <option key={pid} value={pid}>{pid}</option>)}
            </select>
            <input className="form-input form-input-sm"
              value={item.rule}
              placeholder="Faustregel"
              onChange={e => update({ rule: e.target.value })}
              style={{ fontSize: 12 }} />
            <input className="form-input form-input-sm"
              value={item.example_a || ''}
              placeholder={`Beispiel → ${persona.id}`}
              onChange={e => update({ example_a: e.target.value })}
              style={{ gridColumn: '1 / -1', fontSize: 12 }} />
            <input className="form-input form-input-sm"
              value={item.example_b || ''}
              placeholder={`Beispiel → ${item.vs || 'andere'}`}
              onChange={e => update({ example_b: e.target.value })}
              style={{ gridColumn: '1 / -1', fontSize: 12 }} />
          </div>
        )}
      />

      <StringListField
        label="Ziele"
        hint="Was will diese Persona vom Bot — als Bullet-Liste."
        values={persona.goals || []}
        onChange={v => onPersonaChange({ goals: v })}
        placeholder='z.B. „Lernmaterial finden"'
      />

      <StringListField
        label="Regeln"
        hint="Wie soll der Bot mit dieser Persona umgehen — Antwort-Stil, Anzahl Rückfragen, Filter."
        values={persona.rules || []}
        onChange={v => onPersonaChange({ rules: v })}
        placeholder='z.B. „Max. 1 Rückfrage pro Turn"'
      />

      {/* Typische Intents — Multi-Select über Chip-Toggles */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>
          Typische Intents
          <span style={{ color: '#9CA3AF', fontWeight: 400 }}> ({(persona.typical_intents || []).length})</span>
        </label>
        <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>
          Welche Intents kommen typischerweise von dieser Persona? (für Eval-Combos)
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {allIntentIds.map(iid => {
            const checked = (persona.typical_intents || []).includes(iid);
            return (
              <label key={iid} style={{
                fontSize: 12, padding: '2px 8px', borderRadius: 12,
                border: '1px solid',
                background: checked ? '#3B82F6' : '#FFFFFF',
                borderColor: checked ? '#3B82F6' : '#D1D5DB',
                color: checked ? '#FFFFFF' : '#374151',
                cursor: 'pointer', userSelect: 'none',
              }}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => {
                    const cur = persona.typical_intents || [];
                    onPersonaChange({
                      typical_intents: checked ? cur.filter(x => x !== iid) : [...cur, iid],
                    });
                  }}
                  style={{ display: 'none' }}
                />
                {checked ? '✓ ' : ''}{iid}
              </label>
            );
          })}
        </div>
      </div>

      {/* Persönlichkeits-Prosa (Body) */}
      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>
          Persönlichkeits-Text (Markdown-Body)
        </label>
        <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>
          Frei formulierte Prosa — wird zur Persona-Beschreibung im Bot-Persona-Prompt. Optional.
        </div>
        <textarea
          className="form-textarea"
          value={persona.personality_text || ''}
          onChange={e => onPersonaChange({ personality_text: e.target.value })}
          rows={6}
          placeholder="z.B. „Freundlich, unterstützend, einfache Sprache. Siezen Default, Sorge-Unterton ..."
          style={{ width: '100%', fontSize: 12, fontFamily: 'monospace' }}
        />
      </div>
    </div>
  );
}

// ── Persona Editor Container — manages list state + Save-All ─────────
function PersonaEditor({ personas, intents, selectedId, onSelect, onReload }: {
  personas: PersonaData[];
  intents: IntentData[];
  selectedId: string;
  onSelect: (id: string) => void;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<PersonaData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');

  useEffect(() => {
    setRows(personas.map(p => ({
      ...p,
      positive_markers: p.positive_markers ?? p.hints ?? [],
      anti_markers: p.anti_markers ?? [],
      discriminators: p.discriminators ?? [],
      goals: p.goals ?? [],
      rules: p.rules ?? [],
      typical_intents: p.typical_intents ?? [],
    })));
    setStatus('idle');
    setErrorMsg('');
  }, [personas]);

  const selected = rows.find(p => p.id === selectedId);

  const updateSelected = (patch: Partial<PersonaData>) => {
    if (!selected) return;
    const idx = rows.findIndex(p => p.id === selectedId);
    if (idx < 0) return;
    const updated = [...rows];
    updated[idx] = { ...updated[idx], ...patch };
    setRows(updated);
  };

  const handleSaveAll = async () => {
    setStatus('saving');
    setErrorMsg('');
    // hints-Alias für Backward-Compat-Konsumenten: spiegelt positive_markers.
    const payload = rows.map(p => ({
      ...p,
      hints: p.positive_markers ?? [],
    }));
    const res = await _savePut('personas', { personas: payload });
    if (res.ok) {
      setStatus('saved');
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
      setErrorMsg(res.error || `HTTP ${res.status}`);
    }
  };

  return (
    <div className="split-layout" style={{ gridTemplateColumns: '260px 1fr' }}>
      <div className="split-left">
        {rows.map(p => (
          <div
            key={p.id}
            className={`pattern-item ${selectedId === p.id ? 'selected' : ''}`}
            onClick={() => onSelect(p.id)}
          >
            <span className="pattern-id" style={{ fontSize: '.65rem' }}>{p.id}</span>
            <span className="pattern-label">{p.label}</span>
          </div>
        ))}
      </div>
      <div className="split-right">
        {selected ? (
          <PersonaDetail
            persona={selected}
            allPersonas={rows}
            allIntents={intents}
            onPersonaChange={updateSelected}
            onSaveAll={handleSaveAll}
            saveStatus={status}
            saveError={errorMsg}
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
  );
}


// ──────────────────────────────────────────────────────────────────────
// Welle E (2026-05-25) — Form-basierte Element-Editoren
//
// Ablöse für die alten YAML-Texteditor-Tabellen: jede Dimension hat jetzt
// einen Karten-Editor pro Element mit allen Feldern als richtigen
// Form-Controls (Listen mit Add/Remove, Sub-Forms für nested objects).
//
// Save geht NICHT mehr durch den generischen /api/config/file PUT
// (der die Datei als Text ersetzt) sondern durch die strukturierten
// /api/config/intents (PUT), /api/config/states (PUT), /api/config/
// entities (PUT)-Endpoints. Diese validieren via Pydantic, machen einen
// ruamel.yaml round-trip und behalten Header-Kommentare.
// ──────────────────────────────────────────────────────────────────────

/** Klein-Helper-Komponente: editierbare String-Liste mit Add/Remove. */
function StringListField({ label, hint, values, onChange, placeholder }: {
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
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>
          {label} <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({items.length})</span>
        </label>
        <button type="button" className="btn btn-sm" onClick={add}
          style={{ fontSize: '.7rem', padding: '2px 8px' }}>+ hinzufügen</button>
      </div>
      {hint && <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>{hint}</div>}
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

/** Generic helper: editable record list (one nested form per item). */
function RecordListField<T>({
  label, hint, values, onChange, makeEmpty, renderItem,
}: {
  label: string;
  hint?: string;
  values: T[];
  onChange: (v: T[]) => void;
  makeEmpty: () => T;
  renderItem: (item: T, update: (patch: Partial<T>) => void) => React.ReactNode;
}) {
  const items = values || [];
  const update = (idx: number, patch: Partial<T>) => {
    const next = [...items];
    next[idx] = { ...next[idx], ...patch };
    onChange(next);
  };
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, makeEmpty()]);
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>
          {label} <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({items.length})</span>
        </label>
        <button type="button" className="btn btn-sm" onClick={add}
          style={{ fontSize: '.7rem', padding: '2px 8px' }}>+ hinzufügen</button>
      </div>
      {hint && <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>{hint}</div>}
      {items.length === 0 && (
        <div style={{ fontSize: 11, color: '#9CA3AF', fontStyle: 'italic', padding: '4px 0' }}>
          (keine Einträge)
        </div>
      )}
      {items.map((it, idx) => (
        <div key={idx} style={{
          background: '#FFF', border: '1px solid #E5E7EB', borderRadius: 4,
          padding: 8, marginBottom: 6, position: 'relative',
        }}>
          <button type="button" className="btn btn-danger btn-sm btn-icon"
            onClick={() => remove(idx)} title="Eintrag entfernen"
            style={{
              position: 'absolute', top: 4, right: 4,
              padding: '2px 6px', fontSize: '.7rem',
            }}>✕</button>
          {renderItem(it, (patch) => update(idx, patch))}
        </div>
      ))}
    </div>
  );
}

/** Save-Helper für die strukturierten Backend-PUT-Endpoints. */
async function _savePut(path: string, body: unknown): Promise<{ ok: boolean; status?: number; error?: string }> {
  try {
    const r = await fetch(`/api/config/${path}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const txt = await r.text().catch(() => '');
      return { ok: false, status: r.status, error: txt };
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// ── Form-based Intent Editor ─────────────────────────────────────────
//
// Karten-Layout: pro Intent eine ausklappbare Card mit allen Feldern.
// Save geht durch PUT /api/config/intents (strukturierter Endpoint mit
// Pydantic-Validierung + ruamel-Roundtrip).
function IntentEditor({ intents, onReload }: {
  intents: IntentData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<IntentData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [dirty, setDirty] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setRows(intents.map(i => ({
      ...i,
      examples: i.examples ?? [],
      trigger_verbs: i.trigger_verbs ?? [],
      negative_triggers: i.negative_triggers ?? [],
      discriminators: i.discriminators ?? [],
    })));
    setDirty(false);
  }, [intents]);

  const updateRow = (idx: number, patch: Partial<IntentData>) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], ...patch };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    if (!confirm(`Intent "${rows[idx].id}" wirklich löschen?`)) return;
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const addRow = () => {
    const newId = `I${String(rows.length + 1).padStart(2, '0')}`;
    setRows([...rows, {
      id: newId, label: 'Neuer Intent', description: '',
      examples: [], trigger_verbs: [], negative_triggers: [], discriminators: [],
    }]);
    setExpandedId(newId);
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    setErrorMsg('');
    const res = await _savePut('intents', { intents: rows });
    if (res.ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
      setErrorMsg(res.error || `HTTP ${res.status}`);
    }
  };

  return (
    <div>
      <div style={{
        background: '#ECFDF5', border: '1px solid #10B981', borderRadius: 6,
        padding: 10, marginBottom: 12, fontSize: 12, color: '#065F46',
      }}>
        <strong>Form-Editor (Welle E):</strong> Alle Felder editierbar — Trigger-Verben,
        Negativ-Trigger und Diskriminatoren als Listen mit Add/Remove. Save geht durch
        einen validierten Backend-Endpoint, der Header-Kommentare in der YAML erhält.
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-intents/intents.yaml</div>
        <div className="btn-group">
          <button className="btn btn-sm" onClick={addRow}>+ Neuer Intent</button>
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error" title={errorMsg}>Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      {errorMsg && (
        <div style={{
          background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 4,
          padding: 8, marginBottom: 8, fontSize: 12, color: '#7F1D1D',
        }}>{errorMsg}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r, idx) => (
          <IntentCard
            key={`${r.id}-${idx}`}
            intent={r}
            isOpen={expandedId === r.id}
            allIntents={rows}
            onToggle={() => setExpandedId(expandedId === r.id ? null : r.id)}
            onChange={(patch) => updateRow(idx, patch)}
            onDelete={() => deleteRow(idx)}
          />
        ))}
      </div>

      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

/** Karte pro Intent — alle Felder als Form-Controls. */
function IntentCard({ intent, isOpen, allIntents, onToggle, onChange, onDelete }: {
  intent: IntentData;
  isOpen: boolean;
  allIntents: IntentData[];
  onToggle: () => void;
  onChange: (patch: Partial<IntentData>) => void;
  onDelete: () => void;
}) {
  const has = (a?: unknown[]) => Array.isArray(a) && a.length > 0;
  // Other intent IDs als Dropdown-Optionen für redirect_to / vs.
  const otherIds = allIntents.filter(i => i.id !== intent.id).map(i => i.id);

  const summary = [
    has(intent.trigger_verbs) && `${intent.trigger_verbs!.length} Trigger`,
    has(intent.negative_triggers) && `${intent.negative_triggers!.length} Neg.`,
    has(intent.discriminators) && `${intent.discriminators!.length} Disc.`,
    has(intent.examples) && `${intent.examples!.length} Bsp.`,
  ].filter(Boolean).join(' · ');

  return (
    <div style={{
      border: '1px solid #E5E7EB', borderRadius: 8, background: '#FFFFFF',
      overflow: 'hidden',
    }}>
      {/* Karten-Header — immer sichtbar */}
      <div style={{
        display: 'flex', gap: 6, padding: 8, alignItems: 'center',
        background: isOpen ? '#F9FAFB' : '#FFFFFF',
        borderBottom: isOpen ? '1px solid #E5E7EB' : 'none',
      }}>
        <button type="button" className="btn btn-sm" onClick={onToggle}
          style={{ width: 30, padding: '2px 0', fontSize: '.75rem' }}>
          {isOpen ? '▾' : '▸'}
        </button>
        <input className="form-input form-input-sm" value={intent.id}
          onChange={e => onChange({ id: e.target.value })}
          style={{ width: 80, fontFamily: 'monospace', fontWeight: 600 }} />
        <input className="form-input form-input-sm" value={intent.label}
          onChange={e => onChange({ label: e.target.value })}
          style={{ width: 200, fontWeight: 500 }} />
        <input className="form-input form-input-sm"
          value={intent.description || ''}
          placeholder="Kurzbeschreibung — 1–2 Sätze"
          onChange={e => onChange({ description: e.target.value })}
          style={{ flex: 1 }} />
        {summary && (
          <span style={{ fontSize: 11, color: '#6B7280', whiteSpace: 'nowrap' }}>
            {summary}
          </span>
        )}
        <button type="button" className="btn btn-danger btn-sm btn-icon"
          onClick={onDelete} title="Intent löschen"
          style={{ padding: '2px 6px', fontSize: '.7rem' }}>✕</button>
      </div>

      {/* Karten-Body — Felder im Detail */}
      {isOpen && (
        <div style={{ padding: 12, background: '#F9FAFB' }}>
          <StringListField
            label="Beispiele (positive Mustersätze)"
            hint="Werden im Klassifizier-Prompt und im Evaluator als Gold-Set genutzt."
            values={intent.examples || []}
            onChange={v => onChange({ examples: v })}
            placeholder="z.B. „Erstelle ein Arbeitsblatt zu Photosynthese"
          />

          <StringListField
            label="Trigger-Verben"
            hint="Verben/Phrasen, die diesen Intent stark anziehen."
            values={intent.trigger_verbs || []}
            onChange={v => onChange({ trigger_verbs: v })}
            placeholder="z.B. „erstelle, generiere, mach mir"
          />

          <RecordListField
            label="Negativ-Trigger"
            hint="Phrasen, die diesen Intent AUSSCHLIESSEN — plus, wohin sie umleiten."
            values={intent.negative_triggers || []}
            onChange={v => onChange({ negative_triggers: v })}
            makeEmpty={() => ({ phrase: '', redirect_to: '', rationale: '', when: '' })}
            renderItem={(item, update) => (
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 90px 1fr', gap: 6, paddingRight: 24 }}>
                <input className="form-input form-input-sm"
                  value={item.phrase}
                  placeholder="Phrase (pipe-separiert ok)"
                  onChange={e => update({ phrase: e.target.value })}
                  style={{ fontSize: 12 }} />
                <select className="form-input form-input-sm"
                  value={item.redirect_to || ''}
                  onChange={e => update({ redirect_to: e.target.value })}
                  style={{ fontSize: 12 }}>
                  <option value="">→ Intent</option>
                  {otherIds.map(id => <option key={id} value={id}>{id}</option>)}
                </select>
                <input className="form-input form-input-sm"
                  value={item.rationale || ''}
                  placeholder="Warum?"
                  onChange={e => update({ rationale: e.target.value })}
                  style={{ fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.when || ''}
                  placeholder='optional: when, z.B. „canvas_state.mode == "material"'
                  onChange={e => update({ when: e.target.value })}
                  style={{ gridColumn: '1 / -1', fontSize: 12 }} />
              </div>
            )}
          />

          <RecordListField
            label="Diskriminatoren (Cross-Intent-Disambig)"
            hint="Wann ist es eher der andere Intent? Mit Beispielen für beide Seiten."
            values={intent.discriminators || []}
            onChange={v => onChange({ discriminators: v })}
            makeEmpty={() => ({ vs: '', rule: '', example_a: '', example_b: '' })}
            renderItem={(item, update) => (
              <div style={{ display: 'grid', gridTemplateColumns: '90px 1fr', gap: 6, paddingRight: 24 }}>
                <select className="form-input form-input-sm"
                  value={item.vs}
                  onChange={e => update({ vs: e.target.value })}
                  style={{ fontSize: 12 }}>
                  <option value="">vs. ?</option>
                  {otherIds.map(id => <option key={id} value={id}>{id}</option>)}
                </select>
                <input className="form-input form-input-sm"
                  value={item.rule}
                  placeholder="Faustregel"
                  onChange={e => update({ rule: e.target.value })}
                  style={{ fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.example_a || ''}
                  placeholder={`Beispiel → ${intent.id}`}
                  onChange={e => update({ example_a: e.target.value })}
                  style={{ gridColumn: '1 / -1', fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.example_b || ''}
                  placeholder={`Beispiel → ${item.vs || 'andere'}`}
                  onChange={e => update({ example_b: e.target.value })}
                  style={{ gridColumn: '1 / -1', fontSize: 12 }} />
              </div>
            )}
          />
        </div>
      )}
    </div>
  );
}

// ── Form-based State Editor ──────────────────────────────────────────
function StateEditor({ states, onReload }: {
  states: StateData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<StateData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [dirty, setDirty] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setRows(states.map(s => ({
      ...s,
      next_likely: s.next_likely ?? [],
      selection_criteria: s.selection_criteria ?? [],
    })));
    setDirty(false);
  }, [states]);

  const updateRow = (idx: number, patch: Partial<StateData>) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], ...patch };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    if (!confirm(`State "${rows[idx].id}" wirklich löschen?`)) return;
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const addRow = () => {
    const newId = `S${rows.length + 1}`;
    setRows([...rows, {
      id: newId, label: 'Neue Phase', description: '',
      role: '', bot_directive: '',
      next_likely: [], selection_criteria: [],
    }]);
    setExpandedId(newId);
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    setErrorMsg('');
    const res = await _savePut('states', { states: rows });
    if (res.ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
      setErrorMsg(res.error || `HTTP ${res.status}`);
    }
  };

  const allStateIds = rows.map(r => r.id);

  return (
    <div>
      <div style={{
        background: '#ECFDF5', border: '1px solid #10B981', borderRadius: 6,
        padding: 10, marginBottom: 12, fontSize: 12, color: '#065F46',
      }}>
        <strong>Form-Editor (Welle E):</strong> Alle Felder editierbar — inkl.
        <code>role</code>, <code>bot_directive</code> (Multi-Line),{' '}
        <code>next_likely</code> und <code>selection_criteria</code>. Backend-
        Validation + ruamel-Roundtrip erhält Kommentare.
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-states/states.yaml</div>
        <div className="btn-group">
          <button className="btn btn-sm" onClick={addRow}>+ Neuer State</button>
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error" title={errorMsg}>Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      {errorMsg && (
        <div style={{
          background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 4,
          padding: 8, marginBottom: 8, fontSize: 12, color: '#7F1D1D',
        }}>{errorMsg}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r, idx) => (
          <StateCard
            key={`${r.id}-${idx}`}
            state={r}
            isOpen={expandedId === r.id}
            allStateIds={allStateIds}
            onToggle={() => setExpandedId(expandedId === r.id ? null : r.id)}
            onChange={(patch) => updateRow(idx, patch)}
            onDelete={() => deleteRow(idx)}
          />
        ))}
      </div>

      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

function StateCard({ state, isOpen, allStateIds, onToggle, onChange, onDelete }: {
  state: StateData;
  isOpen: boolean;
  allStateIds: string[];
  onToggle: () => void;
  onChange: (patch: Partial<StateData>) => void;
  onDelete: () => void;
}) {
  const summary = [
    state.role && 'Rolle',
    state.bot_directive && 'Direktive',
    state.next_likely?.length && `${state.next_likely.length} next`,
    state.selection_criteria?.length && `${state.selection_criteria.length} Krit.`,
  ].filter(Boolean).join(' · ');

  // Toggle helper für next_likely-Multi-Select
  const toggleNext = (sid: string) => {
    const next = state.next_likely || [];
    if (next.includes(sid)) {
      onChange({ next_likely: next.filter(x => x !== sid) });
    } else {
      onChange({ next_likely: [...next, sid] });
    }
  };

  return (
    <div style={{
      border: '1px solid #E5E7EB', borderRadius: 8, background: '#FFFFFF',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', gap: 6, padding: 8, alignItems: 'center',
        background: isOpen ? '#F9FAFB' : '#FFFFFF',
        borderBottom: isOpen ? '1px solid #E5E7EB' : 'none',
      }}>
        <button type="button" className="btn btn-sm" onClick={onToggle}
          style={{ width: 30, padding: '2px 0', fontSize: '.75rem' }}>
          {isOpen ? '▾' : '▸'}
        </button>
        <input className="form-input form-input-sm" value={state.id}
          onChange={e => onChange({ id: e.target.value })}
          style={{ width: 60, fontFamily: 'monospace', fontWeight: 600 }} />
        <input className="form-input form-input-sm" value={state.label}
          onChange={e => onChange({ label: e.target.value })}
          style={{ width: 160, fontWeight: 500 }} />
        <input className="form-input form-input-sm"
          value={state.description || ''}
          placeholder="Kurzbeschreibung der Phase"
          onChange={e => onChange({ description: e.target.value })}
          style={{ flex: 1 }} />
        {summary && (
          <span style={{ fontSize: 11, color: '#6B7280', whiteSpace: 'nowrap' }}>
            {summary}
          </span>
        )}
        <button type="button" className="btn btn-danger btn-sm btn-icon"
          onClick={onDelete} title="State löschen"
          style={{ padding: '2px 6px', fontSize: '.7rem' }}>✕</button>
      </div>

      {isOpen && (
        <div style={{ padding: 12, background: '#F9FAFB' }}>
          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>
              Rolle in dieser Phase
            </label>
            <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>
              Kurzcharakter — fließt in den Response-Prompt als Kontextzeile.
            </div>
            <input className="form-input form-input-sm"
              value={state.role || ''}
              onChange={e => onChange({ role: e.target.value })}
              placeholder='z.B. „Bot sondiert offen, ohne Pre-Commitment."'
              style={{ width: '100%', fontSize: 12 }} />
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>
              bot_directive (Multi-Line)
            </label>
            <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>
              Handlungs-Anweisung an den Response-Prompt — was BOERDi in dieser Phase tun soll.
            </div>
            <textarea
              className="form-textarea"
              value={state.bot_directive || ''}
              onChange={e => onChange({ bot_directive: e.target.value })}
              rows={4}
              placeholder='z.B. „EINE offene Frage, 2-3 Quick-Reply-Optionen. Kein Tool-Call. Max. 2 Sätze."'
              style={{ width: '100%', fontSize: 12, fontFamily: 'monospace' }}
            />
          </div>

          <div style={{ marginBottom: 12 }}>
            <label style={{ fontSize: 12, fontWeight: 600, color: '#374151', display: 'block', marginBottom: 4 }}>
              next_likely <span style={{ color: '#9CA3AF', fontWeight: 400 }}>(plausible Folge-States)</span>
            </label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {allStateIds.filter(sid => sid !== state.id).map(sid => {
                const checked = (state.next_likely || []).includes(sid);
                return (
                  <label key={sid} style={{
                    fontSize: 12, padding: '2px 8px', borderRadius: 12,
                    border: '1px solid',
                    background: checked ? '#3B82F6' : '#FFFFFF',
                    borderColor: checked ? '#3B82F6' : '#D1D5DB',
                    color: checked ? '#FFFFFF' : '#374151',
                    cursor: 'pointer', userSelect: 'none',
                  }}>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleNext(sid)}
                      style={{ display: 'none' }}
                    />
                    {checked ? '✓ ' : ''}{sid}
                  </label>
                );
              })}
            </div>
          </div>

          <StringListField
            label="Selection-Kriterien"
            hint="WANN wählt der Klassifikator diesen State? Eine Regel pro Eintrag."
            values={state.selection_criteria || []}
            onChange={v => onChange({ selection_criteria: v })}
            placeholder='z.B. „Slot fehlt — Klärung nötig"'
          />
        </div>
      )}
    </div>
  );
}

// ── Form-based Entity Editor ─────────────────────────────────────────
function EntityEditor({ entities, onReload }: {
  entities: EntityData[];
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
  onReload: () => Promise<void>;
}) {
  const [rows, setRows] = useState<EntityData[]>([]);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [dirty, setDirty] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    setRows(entities.map(e => ({
      ...e,
      examples: e.examples ?? [],
      positive_examples: e.positive_examples ?? [],
      negative_examples: e.negative_examples ?? [],
      discriminators: e.discriminators ?? [],
    })));
    setDirty(false);
  }, [entities]);

  const updateRow = (idx: number, patch: Partial<EntityData>) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], ...patch };
    setRows(updated);
    setDirty(true);
  };

  const deleteRow = (idx: number) => {
    if (!confirm(`Entity "${rows[idx].id}" wirklich löschen?`)) return;
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  const addRow = () => {
    setRows([...rows, {
      id: 'neu', label: '', type: 'string', description: '',
      examples: [], positive_examples: [], negative_examples: [], discriminators: [],
    }]);
    setExpandedId('neu');
    setDirty(true);
  };

  const handleSave = async () => {
    setStatus('saving');
    setErrorMsg('');
    const res = await _savePut('entities', { entities: rows });
    if (res.ok) {
      setStatus('saved');
      setDirty(false);
      await onReload();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
      setErrorMsg(res.error || `HTTP ${res.status}`);
    }
  };

  return (
    <div>
      <div style={{
        background: '#ECFDF5', border: '1px solid #10B981', borderRadius: 6,
        padding: 10, marginBottom: 12, fontSize: 12, color: '#065F46',
      }}>
        <strong>Form-Editor (Welle E):</strong> Alle Felder editierbar — inkl. Positiv-Beispiele
        (mit Wert), Negativ-Beispiele (mit Rationale) und Diskriminatoren. Backend-
        Validation + ruamel-Roundtrip erhält Kommentare.
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div className="text-xs text-muted font-mono">04-entities/entities.yaml</div>
        <div className="btn-group">
          <button className="btn btn-sm" onClick={addRow}>+ Neue Entity</button>
          {status === 'saved' && <span className="save-status saved">Gespeichert</span>}
          {status === 'error' && <span className="save-status error" title={errorMsg}>Fehler</span>}
          <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={!dirty || status === 'saving'}>
            {status === 'saving' ? 'Speichert...' : 'Speichern'}
          </button>
        </div>
      </div>
      {errorMsg && (
        <div style={{
          background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 4,
          padding: 8, marginBottom: 8, fontSize: 12, color: '#7F1D1D',
        }}>{errorMsg}</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rows.map((r, idx) => (
          <EntityCard
            key={`${r.id}-${idx}`}
            entity={r}
            isOpen={expandedId === r.id}
            allEntityIds={rows.map(x => x.id)}
            onToggle={() => setExpandedId(expandedId === r.id ? null : r.id)}
            onChange={(patch) => updateRow(idx, patch)}
            onDelete={() => deleteRow(idx)}
          />
        ))}
      </div>

      {dirty && (
        <div className="form-hint mt-2" style={{ color: 'var(--warning)' }}>
          Ungespeicherte Änderungen vorhanden
        </div>
      )}
    </div>
  );
}

function EntityCard({ entity, isOpen, allEntityIds, onToggle, onChange, onDelete }: {
  entity: EntityData;
  isOpen: boolean;
  allEntityIds: string[];
  onToggle: () => void;
  onChange: (patch: Partial<EntityData>) => void;
  onDelete: () => void;
}) {
  const otherIds = allEntityIds.filter(id => id !== entity.id);
  const summary = [
    entity.examples?.length && `${entity.examples.length} Bsp.`,
    entity.positive_examples?.length && `${entity.positive_examples.length} pos`,
    entity.negative_examples?.length && `${entity.negative_examples.length} neg`,
    entity.discriminators?.length && `${entity.discriminators.length} Disc.`,
  ].filter(Boolean).join(' · ');

  return (
    <div style={{
      border: '1px solid #E5E7EB', borderRadius: 8, background: '#FFFFFF',
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', gap: 6, padding: 8, alignItems: 'center',
        background: isOpen ? '#F9FAFB' : '#FFFFFF',
        borderBottom: isOpen ? '1px solid #E5E7EB' : 'none',
      }}>
        <button type="button" className="btn btn-sm" onClick={onToggle}
          style={{ width: 30, padding: '2px 0', fontSize: '.75rem' }}>
          {isOpen ? '▾' : '▸'}
        </button>
        <input className="form-input form-input-sm" value={entity.id}
          onChange={e => onChange({ id: e.target.value })}
          style={{ width: 100, fontFamily: 'monospace', fontWeight: 600 }} />
        <input className="form-input form-input-sm" value={entity.label || ''}
          onChange={e => onChange({ label: e.target.value })}
          placeholder="Anzeigename"
          style={{ width: 200, fontWeight: 500 }} />
        <select className="form-input form-input-sm" value={entity.type || 'string'}
          onChange={e => onChange({ type: e.target.value })}
          style={{ width: 90, fontSize: 12 }}>
          <option value="string">string</option>
          <option value="number">number</option>
          <option value="boolean">boolean</option>
          <option value="array">array</option>
        </select>
        <input className="form-input form-input-sm"
          value={entity.description || ''}
          placeholder="Beschreibung — was extrahiert dieser Slot?"
          onChange={e => onChange({ description: e.target.value })}
          style={{ flex: 1 }} />
        {summary && (
          <span style={{ fontSize: 11, color: '#6B7280', whiteSpace: 'nowrap' }}>
            {summary}
          </span>
        )}
        <button type="button" className="btn btn-danger btn-sm btn-icon"
          onClick={onDelete} title="Entity löschen"
          style={{ padding: '2px 6px', fontSize: '.7rem' }}>✕</button>
      </div>

      {isOpen && (
        <div style={{ padding: 12, background: '#F9FAFB' }}>
          <StringListField
            label="Beispielwerte (für Enum / Inline-Liste)"
            hint='Werte, die in der YAML als "examples"-Block stehen — Studio-Anzeige + Eval-Test.'
            values={entity.examples || []}
            onChange={v => onChange({ examples: v })}
            placeholder="z.B. Mathematik / Video / CC BY"
          />

          <RecordListField
            label="Positiv-Beispiele (Satz → erwarteter Wert)"
            hint="Diese Beispiele werden im Klassifizier-Prompt als Positiv-Block angezeigt."
            values={entity.positive_examples || []}
            onChange={v => onChange({ positive_examples: v })}
            makeEmpty={() => ({ text: '', value: '' })}
            renderItem={(item, update) => (
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 6, paddingRight: 24 }}>
                <input className="form-input form-input-sm"
                  value={item.text}
                  placeholder='Beispielsatz, z.B. „Klasse 6"'
                  onChange={e => update({ text: e.target.value })}
                  style={{ fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.value || ''}
                  placeholder='Erwarteter Wert, z.B. „Sekundarstufe I"'
                  onChange={e => update({ value: e.target.value })}
                  style={{ fontSize: 12 }} />
              </div>
            )}
          />

          <RecordListField
            label="Negativ-Beispiele (Slot bleibt LEER)"
            hint="Sätze, bei denen der Slot NICHT gefüllt werden darf (Substring-Klau verhindern)."
            values={entity.negative_examples || []}
            onChange={v => onChange({ negative_examples: v })}
            makeEmpty={() => ({ text: '', rationale: '' })}
            renderItem={(item, update) => (
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 6, paddingRight: 24 }}>
                <input className="form-input form-input-sm"
                  value={item.text}
                  placeholder='Beispielsatz, z.B. „Erstelle mir ein neues Material"'
                  onChange={e => update({ text: e.target.value })}
                  style={{ fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.rationale || ''}
                  placeholder="Warum leer? (kurz)"
                  onChange={e => update({ rationale: e.target.value })}
                  style={{ fontSize: 12 }} />
              </div>
            )}
          />

          <RecordListField
            label="Diskriminatoren (Cross-Slot-Disambig)"
            hint="Wann ist es eher der andere Slot? Mit Beispielen für beide Seiten."
            values={entity.discriminators || []}
            onChange={v => onChange({ discriminators: v })}
            makeEmpty={() => ({ vs: '', rule: '', example_a: '', example_b: '' })}
            renderItem={(item, update) => (
              <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 6, paddingRight: 24 }}>
                <select className="form-input form-input-sm"
                  value={item.vs}
                  onChange={e => update({ vs: e.target.value })}
                  style={{ fontSize: 12 }}>
                  <option value="">vs. ?</option>
                  {otherIds.map(id => <option key={id} value={id}>{id}</option>)}
                </select>
                <input className="form-input form-input-sm"
                  value={item.rule}
                  placeholder="Faustregel"
                  onChange={e => update({ rule: e.target.value })}
                  style={{ fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.example_a || ''}
                  placeholder={`Beispiel → ${entity.id}`}
                  onChange={e => update({ example_a: e.target.value })}
                  style={{ gridColumn: '1 / -1', fontSize: 12 }} />
                <input className="form-input form-input-sm"
                  value={item.example_b || ''}
                  placeholder={`Beispiel → ${item.vs || 'andere'}`}
                  onChange={e => update({ example_b: e.target.value })}
                  style={{ gridColumn: '1 / -1', fontSize: 12 }} />
              </div>
            )}
          />
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
            <strong style={{ color: '#374151' }}>🔁 Turn-Count</strong> — laufende Turn-Nummer (1, 2, 3…) der Session, kein Konfig-Element. Wird in <code>quality_logs.turn_count</code> persistiert und steuert State-Eskalation (S1 → S3 → S3) sowie Soft-Probing-Cooldowns.
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
        <PersonaEditor
          personas={personas}
          intents={intents}
          selectedId={selectedPersona || ''}
          onSelect={(id) => setSelectedPersona(id)}
          onReload={onReload}
        />
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
