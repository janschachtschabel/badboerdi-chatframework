'use client';

import { useCallback, useEffect, useState } from 'react';

interface PrivacyConfig {
  messages: boolean;
  memory: boolean;
  quality: boolean;
  safety: boolean;  // always true, read-only
}

const DEFAULTS: PrivacyConfig = { messages: true, memory: true, quality: true, safety: true };

export default function PrivacyView() {
  const [cfg, setCfg] = useState<PrivacyConfig>(DEFAULTS);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);
  const [purgeBusy, setPurgeBusy] = useState<string | null>(null);

  const showFlash = useCallback((msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 4500);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/config/privacy');
      if (resp.ok) setCfg(await resp.json());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const save = async (next: PrivacyConfig) => {
    setSaving(true);
    try {
      const resp = await fetch('/api/config/privacy', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(next),
      });
      if (!resp.ok) {
        showFlash(`❌ Speichern fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const saved: PrivacyConfig = await resp.json();
      setCfg(saved);
      showFlash('✅ Einstellungen gespeichert — wirken sofort');
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  const toggle = (key: Exclude<keyof PrivacyConfig, 'safety'>) => {
    save({ ...cfg, [key]: !cfg[key] });
  };

  const runPurge = async (kind: 'chats' | 'all' | 'sessions') => {
    let params: URLSearchParams;
    let label: string;
    let warning: string;

    if (kind === 'chats') {
      params = new URLSearchParams({
        messages: 'true', memory: 'true', quality_logs: 'true',
        safety_logs: 'false', sessions: 'false', confirm: 'true',
      });
      label = 'Chatverläufe';
      warning =
        'Alle Chatverläufe (Messages + Memory + Quality-Logs) UNWIDERRUFLICH löschen?\n\n' +
        'Safety-Logs und Session-Rows bleiben erhalten.\n' +
        'Sessions laufen weiter (Personas / State-IDs bleiben).';
    } else if (kind === 'sessions') {
      params = new URLSearchParams({
        messages: 'true', memory: 'true', quality_logs: 'true',
        safety_logs: 'false', sessions: 'true', confirm: 'true',
      });
      label = 'Chats + Sessions';
      warning =
        'Alles löschen INKLUSIVE Sessions-Tabelle?\n\n' +
        'Laufende Nutzer:innen verlieren ihre Persona/State-Zuordnung.\n' +
        'Safety-Logs bleiben erhalten.';
    } else {
      params = new URLSearchParams({
        messages: 'true', memory: 'true', quality_logs: 'true',
        safety_logs: 'true', sessions: 'true', confirm: 'true',
      });
      label = 'ALLES (inkl. Safety-Logs!)';
      warning =
        '⚠️ ALLES LÖSCHEN — auch Safety-Logs und Sessions?\n\n' +
        'Das beseitigt den vollständigen Audit-Trail.\n' +
        'Nur nutzen, wenn das aus rechtlichen/organisatorischen Gründen ' +
        'unbedingt erforderlich ist und Ersatz-Logs existieren.\n\n' +
        'Diese Aktion ist NICHT umkehrbar.';
    }

    if (!confirm(warning)) return;
    if (!confirm(`Wirklich sicher? ${label} werden endgültig gelöscht.`)) return;

    setPurgeBusy(kind);
    try {
      const resp = await fetch(`/api/sessions/purge?${params}`, { method: 'POST' });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
        showFlash(`❌ Purge fehlgeschlagen: ${err.detail || resp.status}`);
        return;
      }
      const data = await resp.json();
      const d = data.deleted || {};
      const parts: string[] = [];
      if (d.messages !== undefined) parts.push(`${d.messages} Nachrichten`);
      if (d.memory !== undefined) parts.push(`${d.memory} Memory`);
      if (d.quality_logs !== undefined) parts.push(`${d.quality_logs} Quality-Logs`);
      if (d.safety_logs !== undefined) parts.push(`${d.safety_logs} Safety-Logs`);
      if (d.sessions !== undefined) parts.push(`${d.sessions} Sessions`);
      showFlash(`✅ ${label} gelöscht — ${parts.join(', ')}`);
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setPurgeBusy(null);
    }
  };

  return (
    <div>
      <h2 className="card-title" style={{ marginBottom: 8 }}>🔒 Datenschutz</h2>
      <p className="text-sm text-muted" style={{ marginBottom: 16 }}>
        Welche Gesprächsdaten darf der Chatbot dauerhaft speichern? Bei strengen
        Datenschutzanforderungen (z.B. im öffentlichen Bildungskontext ohne
        Session-Konto) können einzelne Logs abgeschaltet werden.
        Sicherheits-Events (Guardrail-Treffer, Rate-Limit, Legal-Klassifikator)
        sind aus Audit-Gründen immer aktiv.
      </p>

      {flash && (
        <div className="card" style={{
          marginBottom: 12,
          background: flash.startsWith('❌') ? '#FEE2E2' : '#DCFCE7',
          borderColor: flash.startsWith('❌') ? '#FCA5A5' : '#86EFAC',
          fontSize: '.82rem', padding: '10px 14px',
        }}>{flash}</div>
      )}

      {/* ── Toggles ── */}
      <section className="card" style={{ padding: 20, marginBottom: 20 }}>
        <h3 style={{ fontSize: '.95rem', marginTop: 0, marginBottom: 12 }}>
          Logging-Einstellungen {loading && <span style={{ color: 'var(--text-muted)' }}>(lade…)</span>}
        </h3>
        <ToggleRow
          label="📝 Chatverläufe speichern"
          desc="messages-Tabelle: jede User- und Bot-Nachricht. Aus = keine Cross-Page-Continuity (Tab-Wechsel verliert den Verlauf)."
          checked={cfg.messages}
          disabled={saving}
          onChange={() => toggle('messages')}
        />
        <ToggleRow
          label="🧠 Session-Memory speichern"
          desc="memory-Tabelle: key/value-Merker pro Session (z.B. gemerkte Fach-/Stufen-Voreinstellung). Aus = Bot vergisst zwischen Turns explizite Merker."
          checked={cfg.memory}
          disabled={saving}
          onChange={() => toggle('memory')}
        />
        <ToggleRow
          label="📊 Quality-Analytics speichern"
          desc="quality_logs-Tabelle: Pattern-Scoring, Intent, Confidence (enthält einen Auszug der Nachricht bis 500 Zeichen). Aus = Dashboard zeigt keine neuen Turns."
          checked={cfg.quality}
          disabled={saving}
          onChange={() => toggle('quality')}
        />
        <ToggleRow
          label="🛡️ Safety-Logs speichern"
          desc="safety_logs-Tabelle: Risk-Events, Rate-Limit-Treffer, Legal-Klassifikator. IMMER AN — nicht abschaltbar (Audit-Pflicht)."
          checked={cfg.safety}
          disabled
          locked
          onChange={() => {}}
        />
      </section>

      {/* ── Purge ── */}
      <section className="card" style={{ padding: 20, borderLeft: '4px solid #DC2626' }}>
        <h3 style={{ fontSize: '.95rem', marginTop: 0, marginBottom: 8, color: '#991B1B' }}>
          🗑 Bestehende Daten löschen
        </h3>
        <p className="text-sm text-muted" style={{ marginBottom: 14 }}>
          Einmaliges Bulk-Delete. Bereits gespeicherte Daten werden entfernt —
          die Logging-Einstellungen oben bleiben unberührt.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PurgeRow
            title="Chatverläufe löschen"
            desc="Messages + Memory + Quality-Logs. Safety-Logs und Sessions bleiben."
            variant="warning"
            disabled={purgeBusy !== null}
            busy={purgeBusy === 'chats'}
            onClick={() => runPurge('chats')}
          />
          <PurgeRow
            title="Chats + Sessions löschen"
            desc="Wie oben + Sessions-Tabelle. Laufende Nutzer:innen verlieren ihre Persona/State. Safety-Logs bleiben."
            variant="danger"
            disabled={purgeBusy !== null}
            busy={purgeBusy === 'sessions'}
            onClick={() => runPurge('sessions')}
          />
          <PurgeRow
            title="ALLES inkl. Safety-Logs löschen"
            desc="Nuclear-Option: entfernt auch den Audit-Trail. Nur nutzen, wenn rechtlich zwingend nötig."
            variant="danger"
            disabled={purgeBusy !== null}
            busy={purgeBusy === 'all'}
            onClick={() => runPurge('all')}
          />
        </div>
      </section>
    </div>
  );
}

/* ── sub-components ── */

function ToggleRow({
  label, desc, checked, disabled, locked, onChange,
}: {
  label: string; desc: string; checked: boolean;
  disabled?: boolean; locked?: boolean;
  onChange: () => void;
}) {
  return (
    <label
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 12,
        padding: '12px 0', borderBottom: '1px solid #f1f5f9',
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled && !locked ? 0.6 : 1,
      }}
    >
      <div style={{ paddingTop: 2 }}>
        <Switch checked={checked} disabled={disabled} onChange={onChange} locked={locked} />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '.88rem', fontWeight: 600, marginBottom: 2 }}>
          {label}
          {locked && <span style={{ marginLeft: 8, fontSize: '.7rem', color: '#b45309', fontWeight: 500 }}>🔒 fest aktiv</span>}
        </div>
        <div style={{ fontSize: '.76rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
          {desc}
        </div>
      </div>
    </label>
  );
}

function Switch({
  checked, disabled, locked, onChange,
}: { checked: boolean; disabled?: boolean; locked?: boolean; onChange: () => void }) {
  return (
    <span
      onClick={(e) => { e.preventDefault(); if (!disabled) onChange(); }}
      role="switch"
      aria-checked={checked}
      style={{
        display: 'inline-block',
        width: 36, height: 20,
        background: checked ? (locked ? '#b45309' : '#059669') : '#cbd5e1',
        borderRadius: 999,
        position: 'relative',
        transition: 'background 120ms',
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 2, left: checked ? 18 : 2,
          width: 16, height: 16,
          background: '#fff',
          borderRadius: '50%',
          transition: 'left 120ms',
          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
        }}
      />
    </span>
  );
}

function PurgeRow({
  title, desc, variant, disabled, busy, onClick,
}: {
  title: string; desc: string;
  variant: 'warning' | 'danger';
  disabled: boolean; busy: boolean;
  onClick: () => void;
}) {
  const color = variant === 'danger' ? '#dc2626' : '#d97706';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '10px 12px',
      background: '#fff7ed',
      border: `1px solid ${variant === 'danger' ? '#fca5a5' : '#fed7aa'}`,
      borderRadius: 6,
      opacity: disabled && !busy ? 0.5 : 1,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '.84rem', fontWeight: 600, color }}>{title}</div>
        <div style={{ fontSize: '.72rem', color: 'var(--text-muted)', marginTop: 2 }}>{desc}</div>
      </div>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        style={{
          padding: '6px 14px',
          fontSize: '.78rem',
          background: color,
          color: '#fff',
          border: 'none',
          borderRadius: 4,
          cursor: disabled ? 'not-allowed' : 'pointer',
          whiteSpace: 'nowrap',
        }}
      >
        {busy ? '…' : 'Löschen'}
      </button>
    </div>
  );
}
