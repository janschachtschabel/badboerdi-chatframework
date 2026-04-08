'use client';

import { useState, FormEvent } from 'react';

export default function LoginPage() {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const resp = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (!resp.ok) {
        setError('Falsches Passwort');
        setBusy(false);
        return;
      }
      // Redirect to original target (or home).
      const params = new URLSearchParams(window.location.search);
      const target = params.get('from') || '/';
      window.location.href = target;
    } catch {
      setError('Verbindungsfehler');
      setBusy(false);
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#f9fafb',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <form
        onSubmit={handleSubmit}
        style={{
          background: '#fff',
          padding: '32px 36px',
          borderRadius: 12,
          boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
          width: 360,
        }}
      >
        <h1 style={{ margin: '0 0 4px', color: '#1c4587', fontSize: 22 }}>
          🦉 BOERDi Studio
        </h1>
        <p style={{ margin: '0 0 24px', color: '#6b7280', fontSize: 14 }}>
          Bitte Passwort eingeben.
        </p>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Passwort"
          autoFocus
          required
          style={{
            width: '100%',
            padding: '10px 12px',
            border: '1px solid #d1d5db',
            borderRadius: 8,
            fontSize: 15,
            boxSizing: 'border-box',
          }}
        />
        {error && (
          <div style={{ color: '#b91c1c', fontSize: 13, marginTop: 10 }}>{error}</div>
        )}
        <button
          type="submit"
          disabled={busy || !password}
          style={{
            marginTop: 18,
            width: '100%',
            padding: '10px 12px',
            background: '#1c4587',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            fontSize: 15,
            fontWeight: 600,
            cursor: busy ? 'wait' : 'pointer',
            opacity: busy ? 0.7 : 1,
          }}
        >
          {busy ? 'Prüfe …' : 'Anmelden'}
        </button>
      </form>
    </div>
  );
}
