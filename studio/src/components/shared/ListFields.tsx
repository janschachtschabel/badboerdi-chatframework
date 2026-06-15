'use client';

// ── Shared List-Field-Komponenten (2026-06-10) ───────────────────────
//
// Vorher als Quasi-Kopien in ElementEditor.tsx (StringListField/
// RecordListField) UND PatternEditor.tsx (PatternStringList) gepflegt.
// Die `variant`-Prop bildet die beiden bisherigen Stylings exakt ab:
//   - 'element' (Default): Inline-Styles wie im ElementEditor
//   - 'pattern': form-group/form-label/form-hint wie im PatternEditor
// DOM und Verhalten sind je Variante 1:1 die der alten Kopien.

import React from 'react';

export type ListFieldVariant = 'element' | 'pattern';

/** Klein-Helper-Komponente: editierbare String-Liste mit Add/Remove. */
export function StringListField({ label, hint, values, onChange, placeholder, variant = 'element' }: {
  label: string;
  hint?: string;
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  variant?: ListFieldVariant;
}) {
  const items = values || [];
  const update = (idx: number, v: string) => {
    const next = [...items];
    next[idx] = v;
    onChange(next);
  };
  const remove = (idx: number) => onChange(items.filter((_, i) => i !== idx));
  const add = () => onChange([...items, '']);
  const isPattern = variant === 'pattern';
  return (
    <div className={isPattern ? 'form-group' : undefined}
      style={isPattern ? undefined : { marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label className={isPattern ? 'form-label' : undefined}
          style={isPattern ? { margin: 0 } : { fontSize: 12, fontWeight: 600, color: '#374151' }}>
          {label} <span style={{ color: '#9CA3AF', fontWeight: 400 }}>({items.length})</span>
        </label>
        <button type="button" className="btn btn-sm" onClick={add}
          style={{ fontSize: '.7rem', padding: '2px 8px' }}>+ hinzufügen</button>
      </div>
      {hint && (
        isPattern
          ? <div className="form-hint" style={{ fontSize: '.8rem', marginBottom: 6 }}>{hint}</div>
          : <div style={{ fontSize: 11, color: '#6B7280', marginBottom: 4 }}>{hint}</div>
      )}
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
export function RecordListField<T>({
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
