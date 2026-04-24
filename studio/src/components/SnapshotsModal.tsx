'use client';

import { useCallback, useEffect, useState } from 'react';

export interface Snapshot {
  id: string;
  file: string;
  size: number;
  label: string;
  created_at: string;      // "YYYYMMDD-HHMMSS"
  mtime: number;
  include_db: boolean;
}

interface FactoryMeta {
  exists: boolean;
  size?: number;
  mtime?: number;
  has_db?: boolean;
  has_config?: boolean;
  config_files?: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onAfterRestore: () => void;
}

function parseTs(ts: string): string {
  // "20260419-132045" → "19.04.2026 13:20"
  if (!/^\d{8}-\d{6}$/.test(ts)) return ts;
  const y = ts.slice(0, 4), m = ts.slice(4, 6), d = ts.slice(6, 8);
  const hh = ts.slice(9, 11), mm = ts.slice(11, 13);
  return `${d}.${m}.${y} ${hh}:${mm}`;
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function SnapshotsModal({ open, onClose, onAfterRestore }: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [factory, setFactory] = useState<FactoryMeta>({ exists: false });
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [newLabel, setNewLabel] = useState('');
  const [newIncludeDb, setNewIncludeDb] = useState(true);

  const showFlash = useCallback((msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 4000);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [snapsResp, factResp] = await Promise.all([
        fetch('/api/config/snapshots'),
        fetch('/api/config/factory'),
      ]);
      if (!snapsResp.ok) {
        showFlash(`❌ Laden fehlgeschlagen: HTTP ${snapsResp.status}`);
        return;
      }
      setSnapshots(await snapsResp.json());
      if (factResp.ok) setFactory(await factResp.json());
    } finally {
      setLoading(false);
    }
  }, [showFlash]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const factoryRestore = async () => {
    if (!confirm(
      'Werkseinstellungen wiederherstellen?\n\n' +
      'Das spielt den Factory-Snapshot ein und überschreibt:\n' +
      '  • die gesamte Konfiguration (wipe: bestehende Dateien werden gelöscht)\n' +
      '  • die Datenbank (inkl. RAG-Chunks, Embeddings, Studio-Einstellungen)\n\n' +
      'Sessions, Memory und Quality/Safety-Logs gehen dabei verloren.',
    )) return;
    if (!confirm('Wirklich sicher? Diese Aktion ist nicht umkehrbar.')) return;
    setBusy('factory-restore');
    try {
      const resp = await fetch(
        '/api/config/factory/restore?wipe=true&include_db=true',
        { method: 'POST' },
      );
      if (!resp.ok) {
        showFlash(`❌ Factory-Restore fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const data = await resp.json();
      showFlash(
        `✅ Werkseinstellungen hergestellt — ` +
        `${data.config_files ?? 0} Config-Dateien, ` +
        `DB: ${data.db_restored ? 'ersetzt' : 'nicht ersetzt'}`,
      );
      onAfterRestore();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const factoryPromote = async (snap: Snapshot) => {
    if (!confirm(
      `Snapshot "${snap.label || snap.id}" als neuen Factory-Default übernehmen?\n\n` +
      'Damit wird er bei jeder zukünftigen leeren Installation automatisch ' +
      'eingespielt. Der bisherige Factory-Snapshot wird überschrieben.',
    )) return;
    setBusy(`factory-save-${snap.id}`);
    try {
      const params = new URLSearchParams({ from_snapshot: snap.id });
      const resp = await fetch(`/api/config/factory/save?${params}`, { method: 'POST' });
      if (!resp.ok) {
        showFlash(`❌ Factory-Update fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const meta: FactoryMeta = await resp.json();
      setFactory(meta);
      showFlash(`✅ Factory-Snapshot ersetzt (${meta.size ? (meta.size / 1024 / 1024).toFixed(2) : '?'} MB).`);
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const factorySaveFromLive = async () => {
    if (!confirm(
      'Aktuellen Live-Zustand (Config + DB inkl. Embeddings) als neuen ' +
      'Factory-Snapshot speichern?\n\n' +
      'Bisheriger Factory-Snapshot wird überschrieben.',
    )) return;
    setBusy('factory-save-live');
    try {
      const resp = await fetch('/api/config/factory/save', { method: 'POST' });
      if (!resp.ok) {
        showFlash(`❌ Factory-Save fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const meta: FactoryMeta = await resp.json();
      setFactory(meta);
      showFlash(`✅ Factory aus Live-Zustand gespeichert (${meta.size ? (meta.size / 1024 / 1024).toFixed(2) : '?'} MB).`);
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const factoryDownload = () => {
    window.location.href = '/api/config/factory/download';
  };

  const create = async () => {
    setBusy('create');
    try {
      const params = new URLSearchParams();
      if (newLabel.trim()) params.set('label', newLabel.trim());
      params.set('include_db', newIncludeDb ? 'true' : 'false');
      const resp = await fetch(`/api/config/snapshots?${params}`, {
        method: 'POST',
      });
      if (!resp.ok) {
        showFlash(`❌ Snapshot fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const snap = await resp.json();
      showFlash(`✅ Snapshot "${snap.label || snap.id}" erstellt (${fmtBytes(snap.size)})`);
      setNewLabel('');
      await load();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const restore = async (s: Snapshot) => {
    const dbWarning = s.include_db
      ? '\n\n⚠️ Der Snapshot enthält eine DATENBANK-KOPIE. Restore ersetzt die aktuelle Datenbank inklusive ALLER Sessions, Messages, Memory, Quality-Logs und RAG-Chunks.'
      : '';
    const wipe = confirm(
      `Snapshot "${s.label || s.id}" wiederherstellen?\n\n` +
      `OK  = Merge (nur Dateien aus dem Snapshot überschreiben)\n` +
      `Cancel = Abbruch${dbWarning}`,
    );
    if (!wipe) return;
    const wipeExtra = confirm(
      'Zusätzlich vorhandene Config-Dateien VOR dem Entpacken löschen?\n\n' +
      'OK  = wipe + restore (sauberer, entfernt Orphan-Dateien)\n' +
      'Cancel = nur mergen',
    );
    setBusy(s.id);
    try {
      const params = new URLSearchParams();
      params.set('wipe', wipeExtra ? 'true' : 'false');
      params.set('include_db', s.include_db ? 'true' : 'false');
      const resp = await fetch(
        `/api/config/snapshots/${encodeURIComponent(s.id)}/restore?${params}`,
        { method: 'POST' },
      );
      if (!resp.ok) {
        showFlash(`❌ Restore fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const data = await resp.json();
      showFlash(
        `✅ Wiederhergestellt: ${data.config_files} Config-Dateien` +
        (data.db_restored ? ' + Datenbank' : '') +
        (data.wiped ? ' (wipe)' : ''),
      );
      onAfterRestore();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const remove = async (s: Snapshot) => {
    if (!confirm(`Snapshot "${s.label || s.id}" endgültig löschen?`)) return;
    setBusy(s.id);
    try {
      const resp = await fetch(
        `/api/config/snapshots/${encodeURIComponent(s.id)}`,
        { method: 'DELETE' },
      );
      if (!resp.ok) {
        showFlash(`❌ Löschen fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      showFlash(`✅ Snapshot gelöscht`);
      await load();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const download = (s: Snapshot) => {
    window.location.href = `/api/config/snapshots/${encodeURIComponent(s.id)}/download`;
  };

  if (!open) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', zIndex: 100,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#fff', borderRadius: 12, padding: 24,
          width: 'min(760px, 92vw)', maxHeight: '86vh', display: 'flex',
          flexDirection: 'column', gap: 16, boxShadow: '0 10px 40px rgba(0,0,0,0.2)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0, fontSize: '1.2rem' }}>📸 Snapshots</h2>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>Schließen</button>
        </div>

        <p style={{ margin: 0, fontSize: '.82rem', color: 'var(--text-muted)' }}>
          Snapshots liegen auf dem Server und lassen sich ohne Up-/Download
          jederzeit zurückspielen. Inkl. Option, die Datenbank (Sessions,
          Messages, Memory, Quality-Logs, RAG-Chunks) mit zu sichern.
        </p>

        {flash && (
          <div className="card" style={{
            background: flash.startsWith('❌') ? '#FEE2E2' : '#DCFCE7',
            borderColor: flash.startsWith('❌') ? '#FCA5A5' : '#86EFAC',
            fontSize: '.82rem', padding: '10px 14px',
          }}>{flash}</div>
        )}

        {/* Neuer Snapshot */}
        <div className="card" style={{ padding: 12 }}>
          <div style={{ fontSize: '.82rem', fontWeight: 600, marginBottom: 8 }}>
            Neuen Snapshot erstellen
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder="Label (z.B. 'vor remix-umbau')"
              disabled={busy === 'create'}
              style={{
                flex: '1 1 220px', padding: '6px 10px', fontSize: '.82rem',
                border: '1px solid var(--border, #d1d5db)', borderRadius: 4,
              }}
            />
            <label style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: '.78rem', whiteSpace: 'nowrap',
            }}>
              <input
                type="checkbox"
                checked={newIncludeDb}
                onChange={(e) => setNewIncludeDb(e.target.checked)}
                disabled={busy === 'create'}
              />
              Datenbank einschließen
            </label>
            <button
              className="btn btn-primary btn-sm"
              onClick={create}
              disabled={busy === 'create'}
            >
              {busy === 'create' ? '…' : '+ Snapshot'}
            </button>
          </div>
        </div>

        {/* ── Factory-Snapshot: Werkseinstellungen ── */}
        <div className="card" style={{
          padding: 12,
          background: '#FFFBEB',
          borderColor: '#FDE68A',
        }}>
          <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'start', gap: 8,
          }}>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: '.82rem', fontWeight: 700, marginBottom: 2, color: '#92400E' }}>
                🏭 Werkseinstellungen (Factory-Snapshot)
              </div>
              <div style={{ fontSize: '.72rem', color: '#78350F', lineHeight: 1.45 }}>
                {factory.exists ? (
                  <>
                    Wird bei jeder komplett leeren Installation automatisch eingespielt.
                    Enthält Config + DB (inkl. Embeddings & Studio-Einstellungen).
                    <div style={{ marginTop: 4, opacity: 0.85 }}>
                      Größe: {factory.size ? (factory.size / 1024 / 1024).toFixed(2) : '?'} MB · {factory.config_files ?? 0} Config-Dateien ·{' '}
                      {factory.has_db ? 'mit DB' : 'ohne DB'} ·
                      Stand: {factory.mtime ? new Date(factory.mtime * 1000).toLocaleString('de-DE') : '—'}
                    </div>
                  </>
                ) : (
                  <>Kein Factory-Snapshot vorhanden. Speichere einen bestehenden Snapshot als Factory oder erzeuge einen aus dem Live-Zustand.</>
                )}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 4, flexDirection: 'column', flexShrink: 0 }}>
              <button
                className="btn btn-sm"
                onClick={factoryRestore}
                disabled={!factory.exists || busy !== null}
                title="Werkseinstellungen wiederherstellen (überschreibt Config + DB)"
                style={{
                  background: '#B45309', color: '#fff', border: 'none',
                  fontSize: '.72rem', padding: '4px 10px', whiteSpace: 'nowrap',
                }}
              >
                {busy === 'factory-restore' ? '…' : '↺ Zurücksetzen'}
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={factoryDownload}
                disabled={!factory.exists}
                title="Factory-Snapshot als ZIP herunterladen"
                style={{ fontSize: '.72rem', padding: '4px 10px', whiteSpace: 'nowrap' }}
              >
                ↓ DL
              </button>
              <button
                className="btn btn-secondary btn-sm"
                onClick={factorySaveFromLive}
                disabled={busy !== null}
                title="Aktuellen Live-Zustand als neuen Factory-Snapshot speichern"
                style={{ fontSize: '.72rem', padding: '4px 10px', whiteSpace: 'nowrap' }}
              >
                {busy === 'factory-save-live' ? '…' : '⇲ Live sichern'}
              </button>
            </div>
          </div>
        </div>

        {/* Liste */}
        <div style={{ overflow: 'auto', flex: 1, minHeight: 120 }}>
          {loading && (
            <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 24 }}>
              Lade Snapshots…
            </div>
          )}
          {!loading && snapshots.length === 0 && (
            <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
              Noch keine Snapshots vorhanden.
            </div>
          )}
          {!loading && snapshots.map((s) => (
            <div key={s.id} className="card" style={{
              padding: '10px 14px', marginBottom: 8,
              opacity: busy === s.id ? 0.5 : 1,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'start' }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '.86rem', marginBottom: 2 }}>
                    {s.label || '(ohne Label)'}
                    {s.include_db && (
                      <span style={{
                        marginLeft: 8, fontSize: '.68rem',
                        padding: '2px 6px', borderRadius: 4,
                        background: '#DBEAFE', color: '#1E40AF', fontWeight: 500,
                      }}>
                        + DB
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: '.72rem', color: 'var(--text-muted)' }}>
                    {parseTs(s.created_at)} · {fmtBytes(s.size)} · {s.id}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={busy !== null}
                    onClick={() => restore(s)}
                    title="Diesen Snapshot wiederherstellen"
                    style={{ fontSize: '.72rem', padding: '4px 10px' }}
                  >
                    ↺ Restore
                  </button>
                  <button
                    className="btn btn-secondary btn-sm"
                    disabled={busy !== null}
                    onClick={() => download(s)}
                    title="Als ZIP herunterladen (offline archivieren)"
                    style={{ fontSize: '.72rem', padding: '4px 10px' }}
                  >
                    ↓ DL
                  </button>
                  <button
                    className="btn btn-sm"
                    disabled={busy !== null}
                    onClick={() => factoryPromote(s)}
                    title="Diesen Snapshot zum neuen Factory-Default machen"
                    style={{
                      fontSize: '.72rem', padding: '4px 10px',
                      background: '#FEF3C7', color: '#92400E',
                      border: '1px solid #FDE68A',
                    }}
                  >
                    {busy === `factory-save-${s.id}` ? '…' : '🏭 Als Factory'}
                  </button>
                  <button
                    className="btn btn-sm"
                    disabled={busy !== null}
                    onClick={() => remove(s)}
                    title="Snapshot löschen"
                    style={{
                      fontSize: '.72rem', padding: '4px 10px',
                      background: '#DC2626', color: '#fff', border: 'none',
                    }}
                  >
                    🗑
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
