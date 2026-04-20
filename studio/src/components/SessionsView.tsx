'use client';

import { useState, useEffect } from 'react';

interface Session {
  session_id: string;
  persona_id: string;
  state_id: string;
  turn_count: number;
  created_at: string;
  updated_at: string;
}

interface Message {
  role: string;
  content: string;
}

export function SessionsView() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => { loadSessions(); }, []);

  const loadSessions = async () => {
    try {
      const resp = await fetch('/api/sessions/');
      if (!resp.ok) return;
      setSessions(await resp.json());
    } catch {}
  };

  const loadMessages = async (sessionId: string) => {
    setSelected(sessionId);
    try {
      const resp = await fetch(`/api/sessions/${sessionId}/messages`);
      if (!resp.ok) return;
      setMessages(await resp.json());
    } catch {}
  };

  const showFlash = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3500);
  };

  const deleteSession = async (sessionId: string) => {
    if (!confirm(
      `Session "${sessionId.slice(0, 20)}…" WIRKLICH komplett löschen?\n\n` +
      `Das entfernt:\n` +
      `  • Alle Chat-Nachrichten\n` +
      `  • Memory-Einträge\n` +
      `  • Quality-Logs\n` +
      `  • Safety-Logs\n` +
      `  • Die Session selbst\n\n` +
      `Diese Aktion ist nicht rückgängig zu machen.`
    )) return;
    setBusy(sessionId);
    try {
      const resp = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      if (!resp.ok) {
        showFlash(`❌ Löschen fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const data = await resp.json();
      const d = data.deleted || {};
      showFlash(
        `✅ Session gelöscht — ` +
        `${d.messages || 0} Nachrichten, ` +
        `${d.memory || 0} Memory, ` +
        `${d.quality_logs || 0} Quality, ` +
        `${d.safety_logs || 0} Safety`
      );
      if (selected === sessionId) {
        setSelected(null);
        setMessages([]);
      }
      await loadSessions();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const clearMessages = async (sessionId: string) => {
    if (!confirm(
      `Chatverlauf für "${sessionId.slice(0, 20)}…" leeren?\n\n` +
      `Das löscht NUR die Nachrichten — Session, Memory und Analytics bleiben erhalten.`
    )) return;
    setBusy(sessionId);
    try {
      const resp = await fetch(`/api/sessions/${sessionId}/messages`, { method: 'DELETE' });
      if (!resp.ok) {
        showFlash(`❌ Löschen fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      const data = await resp.json();
      showFlash(`✅ ${data.deleted_messages || 0} Nachrichten gelöscht`);
      if (selected === sessionId) setMessages([]);
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <h2 className="card-title" style={{ marginBottom: 16 }}>💬 Sessions</h2>

      {flash && (
        <div className="card" style={{
          marginBottom: 12,
          background: flash.startsWith('❌') ? '#FEE2E2' : '#DCFCE7',
          borderColor: flash.startsWith('❌') ? '#FCA5A5' : '#86EFAC',
          fontSize: '.82rem',
        }}>
          {flash}
        </div>
      )}

      <div className="grid-2">
        {/* Session list */}
        <div>
          {sessions.length === 0 && (
            <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
              Noch keine Sessions vorhanden.
            </div>
          )}
          {sessions.map(s => (
            <div key={s.session_id}
                 className="card"
                 style={{
                   cursor: 'pointer',
                   borderLeft: selected === s.session_id ? '3px solid var(--primary)' : undefined,
                   opacity: busy === s.session_id ? 0.5 : 1,
                 }}
                 onClick={() => loadMessages(s.session_id)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: '.82rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {s.session_id.slice(0, 20)}…
                  </div>
                  <div style={{ fontSize: '.72rem', color: 'var(--text-muted)' }}>
                    {s.turn_count} Turns · {s.persona_id || 'unbekannt'} · {s.state_id}
                  </div>
                  <div style={{ fontSize: '.68rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    {new Date(s.updated_at).toLocaleString('de-DE')}
                  </div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <button
                    className="btn btn-secondary"
                    title="Nur Chatverlauf leeren (Session, Memory, Analytics bleiben)"
                    disabled={busy === s.session_id}
                    onClick={(e) => { e.stopPropagation(); clearMessages(s.session_id); }}
                    style={{ fontSize: '.68rem', padding: '3px 8px' }}
                  >
                    🧹 Verlauf
                  </button>
                  <button
                    className="btn"
                    title="Session komplett löschen (inkl. Memory, Analytics)"
                    disabled={busy === s.session_id}
                    onClick={(e) => { e.stopPropagation(); deleteSession(s.session_id); }}
                    style={{
                      fontSize: '.68rem',
                      padding: '3px 8px',
                      background: '#DC2626',
                      color: 'white',
                      border: 'none',
                    }}
                  >
                    🗑 Löschen
                  </button>
                </div>
              </div>
            </div>
          ))}
          <button className="btn btn-secondary" onClick={loadSessions} style={{ marginTop: 8 }}>
            🔄 Aktualisieren
          </button>
        </div>

        {/* Messages */}
        <div>
          {selected && (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <h3 style={{ fontSize: '.9rem', margin: 0 }}>Gesprächsverlauf</h3>
                {messages.length > 0 && (
                  <button
                    className="btn btn-secondary"
                    disabled={busy === selected}
                    onClick={() => clearMessages(selected)}
                    style={{ fontSize: '.72rem', padding: '4px 10px' }}
                    title="Nur Nachrichten löschen"
                  >
                    🧹 Verlauf leeren
                  </button>
                )}
              </div>
              {messages.map((m, i) => (
                <div key={i} style={{
                  padding: '8px 12px',
                  marginBottom: 6,
                  borderRadius: 8,
                  background: m.role === 'user' ? '#DAE8F5' : '#F8FAFC',
                  border: '1px solid var(--border)',
                  fontSize: '.82rem',
                }}>
                  <div style={{ fontWeight: 600, fontSize: '.72rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                    {m.role === 'user' ? '👤 Nutzer:in' : '🦉 Boerdi'}
                  </div>
                  {m.content}
                </div>
              ))}
              {messages.length === 0 && (
                <div className="card" style={{ color: 'var(--text-muted)' }}>
                  Keine Nachrichten in dieser Session.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
