'use client';

// ── useCollectionEditor — gemeinsames Editor-Gerüst (2026-06-10) ─────
//
// Dedupliziert das vorher 4–5-fach kopierte Gerüst der Dimensionen-
// Editoren (Intent/State/Entity/Signal/Persona in ElementEditor.tsx):
// rows/status/errorMsg/dirty-State, Seed-Effect aus den Props,
// updateRow/deleteRow/addRow und der wortgleiche handleSave-Ablauf.
//
// Verhalten ist 1:1 dem bisherigen Inline-Code nachgebildet:
// - Seed-Effect ersetzt rows bei JEDER Änderung der Quelle (auch nach
//   onReload) und setzt dirty zurück; status bleibt dabei unangetastet
//   (Intent/State/Entity/Signal) — außer `resetStatusOnSeed` ist
//   gesetzt (Persona-Editor-Verhalten).
// - update/delete/add arbeiten bewusst auf dem Render-Scope-`rows`
//   (kein functional update) — exakt wie die Originale.
// - handleSave: saving → save() → saved + dirty=false + onSaved()
//   + 2s-Timeout zurück auf idle; Fehlerpfad setzt status=error und
//   errorMsg (res.error || `HTTP ${status}`).
//
// `onDirtyChange` meldet den Dirty-Zustand an den Eltern-Component —
// Grundlage für den Tab-Wechsel-Guard im ElementEditor.

import { useEffect, useState } from 'react';

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error';

export interface SaveResult {
  ok: boolean;
  status?: number;
  error?: string;
}

export interface CollectionEditorOptions<S, T> {
  /** Quelle aus den Props — jede Identitätsänderung re-seedet rows. */
  source: S[];
  /** Pro-Element-Normalisierung beim Seed (Array-Defaults etc.). */
  normalize?: (item: S) => T;
  /** Persistenz — bekommt die aktuellen rows, liefert ok/error. */
  save: (rows: T[]) => Promise<SaveResult>;
  /** Nach erfolgreichem Save (typischerweise onReload). */
  onSaved?: () => Promise<void> | void;
  /** Dirty-Reporting an den Eltern-Component (Tab-Guard). */
  onDirtyChange?: (dirty: boolean) => void;
  /** Persona-Editor-Verhalten: Seed setzt auch status/errorMsg zurück. */
  resetStatusOnSeed?: boolean;
}

export function useCollectionEditor<S, T = S>(opts: CollectionEditorOptions<S, T>) {
  const { source, normalize, save, onSaved, onDirtyChange, resetStatusOnSeed } = opts;
  const [rows, setRows] = useState<T[]>([]);
  const [status, setStatus] = useState<SaveStatus>('idle');
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    // Ohne normalize ist T = S (Default-Generic) — der Cast deckt nur
    // diesen Fall ab; mit abweichendem T MUSS normalize gesetzt sein.
    setRows(normalize ? source.map(normalize) : (source as unknown as T[]));
    setDirty(false);
    if (resetStatusOnSeed) {
      setStatus('idle');
      setErrorMsg('');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const updateRow = (idx: number, patch: Partial<T>) => {
    const updated = [...rows];
    updated[idx] = { ...updated[idx], ...patch };
    setRows(updated);
    setDirty(true);
  };

  /** Löscht Zeile idx; mit confirmMsg vorher nativer confirm()-Dialog. */
  const deleteRow = (idx: number, confirmMsg?: string) => {
    if (confirmMsg && !confirm(confirmMsg)) return;
    setRows(rows.filter((_, i) => i !== idx));
    setDirty(true);
  };

  /** Hängt make(rows) an und gibt die neue Zeile zurück (für expandedId). */
  const addRow = (make: (rows: T[]) => T): T => {
    const row = make(rows);
    setRows([...rows, row]);
    setDirty(true);
    return row;
  };

  const handleSave = async () => {
    setStatus('saving');
    setErrorMsg('');
    const res = await save(rows);
    if (res.ok) {
      setStatus('saved');
      setDirty(false);
      if (onSaved) await onSaved();
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
      setErrorMsg(res.error || `HTTP ${res.status}`);
    }
  };

  return {
    rows,
    status,
    errorMsg,
    dirty,
    updateRow,
    deleteRow,
    addRow,
    handleSave,
  };
}
