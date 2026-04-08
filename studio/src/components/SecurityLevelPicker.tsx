'use client';

import { useEffect, useState } from 'react';

const LEVELS: { id: string; label: string; desc: string; color: string }[] = [
  { id: 'off',      label: 'Off',      desc: 'Nur Regex-Blocks (Suizid). Keine LLM-Calls.',        color: '#9ca3af' },
  { id: 'basic',    label: 'Basic',    desc: 'Regex + OpenAI Moderation immer (gratis, ~150ms).', color: '#10b981' },
  { id: 'standard', label: 'Standard', desc: 'Basic + Legal-Classifier bei Verdacht + Injection.', color: '#3b82f6' },
  { id: 'strict',   label: 'Strict',   desc: 'Alles immer. Legal auch bei low. Mehr Latenz/Kosten.', color: '#f59e0b' },
  { id: 'paranoid', label: 'Paranoid', desc: 'Strict + halbierte Schwellen + Output-Review.',     color: '#ef4444' },
];

const PATH = '01-base/safety-config.yaml';

export default function SecurityLevelPicker() {
  const [current, setCurrent] = useState<string>('standard');
  const [raw, setRaw] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string>('');

  useEffect(() => {
    (async () => {
      const r = await fetch(`/api/config/file?path=${encodeURIComponent(PATH)}`);
      if (!r.ok) return;
      const data = await r.json();
      const text = data.content || '';
      setRaw(text);
      const m = text.match(/^\s*security_level\s*:\s*([a-zA-Z_]+)/m);
      if (m) setCurrent(m[1].toLowerCase());
    })();
  }, []);

  const setLevel = async (lvl: string) => {
    setSaving(true);
    setMsg('');
    try {
      let next: string;
      if (/^\s*security_level\s*:/m.test(raw)) {
        next = raw.replace(/^(\s*security_level\s*:\s*).*$/m, `$1${lvl}`);
      } else {
        next = `security_level: ${lvl}\n` + raw;
      }
      const r = await fetch('/api/config/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: PATH, content: next, file_type: 'yaml' }),
      });
      if (r.ok) {
        setRaw(next);
        setCurrent(lvl);
        setMsg('✓ Übernommen');
      } else {
        setMsg('✗ Fehler beim Speichern');
      }
    } catch {
      setMsg('✗ Netzwerkfehler');
    } finally {
      setSaving(false);
      setTimeout(() => setMsg(''), 2500);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14 }}>🛡️ Sicherheitslevel</div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Steuert, welche Safety-Stages laufen. Wirkt sofort ohne Neustart.
          </div>
        </div>
        {msg && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{msg}</span>}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
        {LEVELS.map(l => {
          const active = current === l.id;
          return (
            <button
              key={l.id}
              disabled={saving}
              onClick={() => setLevel(l.id)}
              style={{
                textAlign: 'left',
                padding: 10,
                border: `2px solid ${active ? l.color : '#e5e7eb'}`,
                background: active ? `${l.color}15` : '#fff',
                borderRadius: 6,
                cursor: 'pointer',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13, color: l.color }}>
                {active ? '● ' : ''}{l.label}
              </div>
              <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>{l.desc}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
