'use client';

import { useState, useEffect, useCallback } from 'react';

/**
 * Begrüßung & Start-Quick-Replies (welcome-config.yaml).
 * Liest/schreibt die typisierten Endpunkte:
 *   GET  /api/config/welcome  → { greeting, quick_replies, tour_reply }
 *   PUT  /api/config/welcome  → speichert (live, mtime-Cache)
 * Die Begrüßungsblase + Start-Chips erscheinen im Widget am Chat-Anfang.
 * Ein Chip kann als Web-Tour-Starter markiert werden (tour_reply).
 */
export default function WelcomeView() {
  const [greeting, setGreeting] = useState('');
  const [replies, setReplies] = useState<string[]>([]);
  const [tourIdx, setTourIdx] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/config/welcome');
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.quick_replies) ? data.quick_replies.map(String) : [];
        setGreeting(String(data.greeting || ''));
        setReplies(list);
        const tr = String(data.tour_reply || '');
        const idx = tr ? list.indexOf(tr) : -1;
        setTourIdx(idx >= 0 ? idx : null);
      }
    } catch {
      /* ignore — leere Felder bleiben */
    }
    setLoading(false);
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const save = async () => {
    setStatus('saving');
    setError('');
    const cleanReplies = replies.map((r) => r.trim()).filter((r) => r.length > 0);
    if (!greeting.trim()) { setStatus('error'); setError('Begrüßung darf nicht leer sein.'); return; }
    if (cleanReplies.length === 0) { setStatus('error'); setError('Mindestens eine Quick-Reply nötig.'); return; }
    // tour_reply = Text des markierten Chips (falls noch nicht leer)
    const tourText = (tourIdx != null && replies[tourIdx]?.trim()) ? replies[tourIdx].trim() : '';
    try {
      const res = await fetch('/api/config/welcome', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ greeting: greeting.trim(), quick_replies: cleanReplies, tour_reply: tourText }),
      });
      if (res.ok) {
        const data = await res.json();
        const list = Array.isArray(data.quick_replies) ? data.quick_replies.map(String) : [];
        setGreeting(String(data.greeting || ''));
        setReplies(list);
        const tr = String(data.tour_reply || '');
        const idx = tr ? list.indexOf(tr) : -1;
        setTourIdx(idx >= 0 ? idx : null);
        setStatus('saved');
        setTimeout(() => setStatus('idle'), 2000);
      } else {
        const body = await res.json().catch(() => ({}));
        setStatus('error');
        setError(body?.detail || `Fehler ${res.status}`);
      }
    } catch (e) {
      setStatus('error');
      setError(String(e));
    }
  };

  const setReply = (i: number, val: string) =>
    setReplies((prev) => prev.map((r, idx) => (idx === i ? val : r)));
  const addReply = () => setReplies((prev) => [...prev, '']);
  const removeReply = (i: number) => {
    setReplies((prev) => prev.filter((_, idx) => idx !== i));
    setTourIdx((cur) => (cur == null ? null : cur === i ? null : cur > i ? cur - 1 : cur));
  };

  const inputStyle: React.CSSProperties = {
    flex: 1, padding: '8px 10px', border: '1px solid #ccc',
    borderRadius: 6, fontSize: 14, boxSizing: 'border-box',
  };

  if (loading) {
    return <div style={{ padding: 24, color: '#888' }}>Lade Begrüßung…</div>;
  }

  return (
    <div style={{ padding: 24, maxWidth: 820 }}>
      <h2 style={{ marginTop: 0 }}>👋 Begrüßung &amp; Start</h2>
      <p style={{ color: '#666', maxWidth: 720, fontSize: 14 }}>
        Begrüßungsblase und Start-Chips, die das Widget <strong>vor</strong> der
        ersten Nutzer-Eingabe zeigt. Änderungen wirken live (mtime-Cache, kein
        Backend-Neustart). Quelle:{' '}
        <code style={{ background: '#f4f4f8', padding: '2px 6px', borderRadius: 4 }}>
          01-base/welcome-config.yaml
        </code>
      </p>

      <label style={{ display: 'block', fontWeight: 600, margin: '18px 0 6px' }}>
        Begrüßungstext
      </label>
      <textarea
        value={greeting}
        onChange={(e) => setGreeting(e.target.value)}
        rows={4}
        style={{ ...inputStyle, width: '100%', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.5 }}
        placeholder="Begrüßungstext (Markdown erlaubt, Zeilenumbrüche bleiben erhalten)…"
      />

      <label style={{ display: 'block', fontWeight: 600, margin: '22px 0 6px' }}>
        Start-Quick-Replies (Klick = wird als Nutzer-Eingabe gesendet)
      </label>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {replies.map((r, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ color: '#999', width: 18, textAlign: 'right' }}>{i + 1}.</span>
            <input value={r} onChange={(e) => setReply(i, e.target.value)} style={inputStyle} />
            <label
              title="Dieser Chip startet die geführte Web-Tour direkt"
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, color: tourIdx === i ? '#7a1f2b' : '#888', whiteSpace: 'nowrap', cursor: 'pointer' }}
            >
              <input
                type="radio"
                name="tour-reply"
                checked={tourIdx === i}
                onChange={() => setTourIdx(i)}
              />
              🧭 Web-Tour
            </label>
            <button
              onClick={() => removeReply(i)}
              title="Entfernen"
              style={{ border: '1px solid #ddd', background: '#fff', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}
            >✕</button>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 10 }}>
        <button
          onClick={addReply}
          style={{ border: '1px dashed #bbb', background: '#fafafa', borderRadius: 6, padding: '6px 12px', cursor: 'pointer', fontSize: 14 }}
        >+ Quick-Reply hinzufügen</button>
        {tourIdx != null && (
          <button
            onClick={() => setTourIdx(null)}
            style={{ border: 'none', background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 13 }}
          >🧭 Tour-Markierung entfernen</button>
        )}
      </div>

      <div style={{ marginTop: 18, padding: '10px 14px', background: '#f0f6ff', border: '1px solid #cfe0f7', borderRadius: 8, fontSize: 13, color: '#33506e', maxWidth: 720 }}>
        <strong>🧭 Web-Tour-Chip:</strong> Der markierte Chip startet die geführte
        Web-Tour <em>direkt</em> und zuverlässig — unabhängig von der
        Klassifikation und ohne dass der Text in der Tour-Konfiguration
        (<code>website-tour.yaml</code>) stehen muss. Ohne Markierung wird der
        Chip wie jede andere Eingabe an den Bot gesendet (und träfe die Tour nur
        zufällig über eine passende Trigger-Phrase).
      </div>

      <div style={{ marginTop: 24, display: 'flex', alignItems: 'center', gap: 14 }}>
        <button
          onClick={save}
          disabled={status === 'saving'}
          style={{ background: '#7a1f2b', color: '#fff', border: 'none', borderRadius: 6, padding: '10px 20px', fontSize: 14, cursor: 'pointer' }}
        >{status === 'saving' ? 'Speichere…' : 'Speichern'}</button>
        {status === 'saved' && <span style={{ color: '#1a7f37' }}>✓ Gespeichert</span>}
        {status === 'error' && <span style={{ color: '#c0392b' }}>✗ {error}</span>}
      </div>
    </div>
  );
}
