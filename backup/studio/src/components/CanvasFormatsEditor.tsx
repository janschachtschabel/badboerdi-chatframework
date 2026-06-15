'use client';

/**
 * GUI editor for canvas material types (05-canvas/material-types.yaml).
 *
 * Avoids the YAML-syntax-trap of the raw text editor by exposing each type
 * as a typed form: id, label, emoji, category, structure. Saves go through
 * /api/config/canvas/material-types which round-trips the multi-line
 * structure as a literal block scalar so diffs stay readable in Git.
 */

import { useEffect, useState, useCallback } from 'react';

interface MaterialType {
  id: string;
  label: string;
  emoji: string;
  category: 'didaktisch' | 'analytisch';
  structure: string;
}

const EMPTY_TYPE: MaterialType = { id: '', label: '', emoji: '📄', category: 'didaktisch', structure: '' };

const ID_RE = /^[a-z0-9_]+$/;

export default function CanvasFormatsEditor() {
  const [types, setTypes] = useState<MaterialType[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<MaterialType | null>(null);
  const [originalDraft, setOriginalDraft] = useState<MaterialType | null>(null);
  const [filter, setFilter] = useState<'all' | 'didaktisch' | 'analytisch'>('all');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  // ── Load on mount ──
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/config/canvas/material-types');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const items: MaterialType[] = (d.material_types || []).map((m: MaterialType) => ({
        id: m.id, label: m.label, emoji: m.emoji || '', category: m.category, structure: m.structure || '',
      }));
      setTypes(items);
      if (items.length > 0 && !selectedId) {
        setSelectedId(items[0].id);
      }
    } catch (e) {
      setError(`Konnte Material-Typen nicht laden: ${e}`);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Set draft from selection ──
  useEffect(() => {
    if (!types) return;
    if (selectedId === '__new__') {
      setDraft({ ...EMPTY_TYPE });
      setOriginalDraft(null);
      return;
    }
    const found = types.find(t => t.id === selectedId);
    if (found) {
      setDraft({ ...found });
      setOriginalDraft({ ...found });
    } else {
      setDraft(null);
      setOriginalDraft(null);
    }
  }, [selectedId, types]);

  const dirty = draft && (
    !originalDraft || JSON.stringify(draft) !== JSON.stringify(originalDraft)
  );

  // ── Save (full list back to backend) ──
  const persist = async (next: MaterialType[]) => {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch('/api/config/canvas/material-types', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ material_types: next }),
      });
      if (!r.ok) {
        const text = await r.text();
        throw new Error(`HTTP ${r.status}: ${text}`);
      }
      const d = await r.json();
      const items: MaterialType[] = d.material_types || [];
      setTypes(items);
      setInfo('Gespeichert. Backend übernimmt Änderungen live (mtime-Cache).');
      setTimeout(() => setInfo(null), 3500);
      return items;
    } catch (e) {
      setError(`Speichern fehlgeschlagen: ${e}`);
      return null;
    } finally {
      setSaving(false);
    }
  };

  const onSaveDraft = async () => {
    if (!draft || !types) return;
    if (!ID_RE.test(draft.id)) {
      setError(`Id "${draft.id}" ist ungültig — nur a-z, 0-9 und _ sind erlaubt.`);
      return;
    }
    if (!draft.label.trim()) {
      setError('Label darf nicht leer sein.');
      return;
    }

    let next: MaterialType[];
    if (selectedId === '__new__') {
      // New entry — id must be unique
      if (types.some(t => t.id === draft.id)) {
        setError(`Id "${draft.id}" existiert bereits.`);
        return;
      }
      next = [...types, draft];
    } else {
      // Update existing — id may change but must stay unique
      if (selectedId !== draft.id && types.some(t => t.id === draft.id)) {
        setError(`Id "${draft.id}" existiert bereits.`);
        return;
      }
      next = types.map(t => t.id === selectedId ? draft : t);
    }
    const saved = await persist(next);
    if (saved) {
      setSelectedId(draft.id);
    }
  };

  const onDelete = async () => {
    if (!draft || !types || selectedId === '__new__') return;
    if (!confirm(`Material-Typ "${draft.label}" (${draft.id}) wirklich löschen?`)) return;
    const next = types.filter(t => t.id !== selectedId);
    const saved = await persist(next);
    if (saved) {
      setSelectedId(saved[0]?.id ?? null);
    }
  };

  const onRevert = () => {
    if (originalDraft) setDraft({ ...originalDraft });
    else if (selectedId === '__new__') setDraft({ ...EMPTY_TYPE });
  };

  // ── Filter list ──
  const visibleTypes = (types || []).filter(t => filter === 'all' || t.category === filter);
  const counts = {
    all: types?.length ?? 0,
    didaktisch: types?.filter(t => t.category === 'didaktisch').length ?? 0,
    analytisch: types?.filter(t => t.category === 'analytisch').length ?? 0,
  };

  if (loading) {
    return <div className="card"><div className="text-sm text-muted">Lade Material-Typen…</div></div>;
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">🎨 Canvas-Formate</div>
        <div className="page-subtitle">
          18 Material-Typen, die der Bot in der Canvas-Arbeitsfläche erzeugen kann.
          Schicht 5 — wirken nur bei Intent <code>INT-W-11 Canvas-Create</code>.
        </div>
      </div>

      {error && (
        <div className="card mb-4" style={{ background: '#FEF2F2', borderColor: '#FECACA' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <span style={{ fontSize: 13, color: '#991B1B' }}>⚠️ {error}</span>
            <button onClick={() => setError(null)} style={{ all: 'unset', cursor: 'pointer', color: '#991B1B' }}>✕</button>
          </div>
        </div>
      )}
      {info && (
        <div className="card mb-4" style={{ background: '#F0FDF4', borderColor: '#BBF7D0' }}>
          <span style={{ fontSize: 13, color: '#166534' }}>✓ {info}</span>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) 2fr', gap: 14 }}>
        {/* ─── LEFT: list ─── */}
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{
            display: 'flex', gap: 4, padding: 8, borderBottom: '1px solid var(--border)',
            background: '#F8FAFC',
          }}>
            {(['all', 'didaktisch', 'analytisch'] as const).map(k => (
              <button
                key={k}
                onClick={() => setFilter(k)}
                style={{
                  flex: 1, padding: '6px 8px', fontSize: 12, fontWeight: 600,
                  background: filter === k ? '#fff' : 'transparent',
                  border: filter === k ? '1px solid var(--border)' : '1px solid transparent',
                  borderRadius: 6, cursor: 'pointer', color: 'var(--text)',
                }}
              >
                {k === 'all' ? 'Alle' : k === 'didaktisch' ? 'Didaktisch' : 'Analytisch'} ({counts[k]})
              </button>
            ))}
          </div>
          <div style={{ maxHeight: 600, overflowY: 'auto' }}>
            {visibleTypes.map(t => (
              <button
                key={t.id}
                onClick={() => setSelectedId(t.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                  padding: '10px 12px', borderTop: '1px solid var(--border)',
                  background: selectedId === t.id ? '#EFF6FF' : '#fff',
                  borderLeft: selectedId === t.id ? '3px solid var(--primary)' : '3px solid transparent',
                  cursor: 'pointer', textAlign: 'left', font: 'inherit', color: 'inherit',
                }}
              >
                <span style={{ fontSize: '1.2rem', width: 28, textAlign: 'center' }}>{t.emoji || '📄'}</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{t.label}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    <code>{t.id}</code> · {t.category}
                  </div>
                </div>
              </button>
            ))}
            <button
              onClick={() => setSelectedId('__new__')}
              style={{
                display: 'block', width: '100%', padding: '10px 12px',
                borderTop: '1px solid var(--border)',
                background: selectedId === '__new__' ? '#EFF6FF' : '#FAFAFA',
                borderLeft: selectedId === '__new__' ? '3px solid var(--primary)' : '3px solid transparent',
                cursor: 'pointer', textAlign: 'left', font: 'inherit',
                fontSize: 13, fontWeight: 600, color: 'var(--primary)',
              }}
            >+ Neuer Material-Typ</button>
          </div>
        </div>

        {/* ─── RIGHT: editor ─── */}
        <div className="card">
          {!draft ? (
            <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
              Wähle links einen Material-Typ oder lege einen neuen an.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <Field label="Id (intern, nur a-z, 0-9, _)" hint="Beispiel: arbeitsblatt, pressemitteilung">
                  <input
                    type="text"
                    value={draft.id}
                    onChange={e => setDraft({ ...draft, id: e.target.value.toLowerCase() })}
                    placeholder="arbeitsblatt"
                    className="form-input"
                  />
                </Field>
                <Field label="Label (UI-Anzeigename)" hint="Beispiel: Arbeitsblatt, Pressemitteilung">
                  <input
                    type="text"
                    value={draft.label}
                    onChange={e => setDraft({ ...draft, label: e.target.value })}
                    placeholder="Arbeitsblatt"
                    className="form-input"
                  />
                </Field>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 10 }}>
                <Field label="Emoji" hint="Genau 1 Symbol">
                  <input
                    type="text"
                    value={draft.emoji}
                    onChange={e => setDraft({ ...draft, emoji: e.target.value })}
                    placeholder="📝"
                    className="form-input"
                    style={{ textAlign: 'center', fontSize: 18 }}
                  />
                </Field>
                <Field label="Kategorie" hint="Steuert Badge-Farbe und Quick-Reply-Reihenfolge pro Persona">
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', height: 38 }}>
                    {(['didaktisch', 'analytisch'] as const).map(c => (
                      <label key={c} style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
                        background: draft.category === c ? (c === 'didaktisch' ? '#DCFCE7' : '#DBEAFE') : '#F1F5F9',
                        border: draft.category === c ? `1px solid ${c === 'didaktisch' ? '#16A34A' : '#2563EB'}` : '1px solid transparent',
                        fontSize: 13, fontWeight: 600,
                      }}>
                        <input
                          type="radio"
                          name={`cat-${draft.id || 'new'}`}
                          checked={draft.category === c}
                          onChange={() => setDraft({ ...draft, category: c })}
                          style={{ margin: 0 }}
                        />
                        {c === 'didaktisch' ? '🎓 Didaktisch' : '📊 Analytisch'}
                      </label>
                    ))}
                  </div>
                </Field>
              </div>

              <Field
                label="Markdown-Struktur (LLM-Anweisung)"
                hint="Konkrete Gliederungs-Vorgabe, die dem Modell beim Erzeugen mitgegeben wird. Multi-line wird als YAML-Block-Scalar (|) gespeichert."
              >
                <textarea
                  value={draft.structure}
                  onChange={e => setDraft({ ...draft, structure: e.target.value })}
                  rows={14}
                  placeholder="Erstelle ein Arbeitsblatt mit:&#10;1. H1-Überschrift '# Arbeitsblatt: [Thema]'&#10;2. ..."
                  className="input"
                  style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12, lineHeight: 1.5 }}
                />
              </Field>

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                {selectedId !== '__new__' && (
                  <button
                    onClick={onDelete}
                    disabled={saving}
                    style={{
                      padding: '8px 14px', borderRadius: 6, border: '1px solid #FCA5A5',
                      background: '#FEF2F2', color: '#991B1B', fontWeight: 600, cursor: 'pointer',
                      fontSize: 13,
                    }}
                  >Löschen</button>
                )}
                <div style={{ flex: 1 }} />
                <button
                  onClick={onRevert}
                  disabled={saving || !dirty}
                  style={{
                    padding: '8px 14px', borderRadius: 6, border: '1px solid var(--border)',
                    background: '#fff', cursor: dirty ? 'pointer' : 'not-allowed',
                    opacity: dirty ? 1 : 0.5, fontSize: 13,
                  }}
                >Verwerfen</button>
                <button
                  onClick={onSaveDraft}
                  disabled={saving || !dirty}
                  style={{
                    padding: '8px 16px', borderRadius: 6, border: '1px solid var(--primary)',
                    background: dirty ? 'var(--primary)' : '#94A3B8', color: '#fff',
                    fontWeight: 600, cursor: dirty ? 'pointer' : 'not-allowed', fontSize: 13,
                  }}
                >{saving ? 'Speichere…' : (selectedId === '__new__' ? 'Anlegen' : 'Speichern')}</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Tiny field wrapper ── */
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{label}</label>
      {hint && <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{hint}</div>}
      {children}
    </div>
  );
}
