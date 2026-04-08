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

  return (
    <div>
      <h2 className="card-title" style={{ marginBottom: 16 }}>💬 Sessions</h2>

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
                 }}
                 onClick={() => loadMessages(s.session_id)}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, fontSize: '.82rem' }}>
                    {s.session_id.slice(0, 20)}…
                  </div>
                  <div style={{ fontSize: '.72rem', color: 'var(--text-muted)' }}>
                    {s.turn_count} Turns · {s.persona_id || 'unbekannt'} · {s.state_id}
                  </div>
                </div>
                <div style={{ fontSize: '.68rem', color: 'var(--text-muted)' }}>
                  {new Date(s.updated_at).toLocaleDateString('de-DE')}
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
              <h3 style={{ fontSize: '.9rem', marginBottom: 8 }}>Gesprächsverlauf</h3>
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
