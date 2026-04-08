'use client';

import { useState, useEffect, useCallback } from 'react';

interface SafetyLog {
  id: number;
  session_id: string;
  ip: string;
  risk_level: 'low' | 'medium' | 'high';
  stages_run: string[];
  reasons: string[];
  legal_flags: string[];
  flagged_categories: string[];
  blocked_tools: string[];
  enforced_pattern: string;
  escalated: number;
  rate_limited: number;
  message: string;
  categories_json: Record<string, number>;
  created_at: string;
}

interface Stats {
  total: number;
  by_risk: Record<string, number>;
  by_legal: Record<string, number>;
  rate_limited: number;
  escalated: number;
}

const RISK_COLORS: Record<string, string> = {
  low: '#9ca3af',
  medium: '#f59e0b',
  high: '#ef4444',
};

const LEGAL_LABELS: Record<string, string> = {
  strafrecht: '⚖️ Strafrecht',
  jugendschutz: '🛡️ Jugendschutz',
  persoenlichkeitsrechte: '👤 Persönlichkeitsrechte',
  datenschutz: '🔒 Datenschutz',
};

export default function SafetyLogsView() {
  const [logs, setLogs] = useState<SafetyLog[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [riskFilter, setRiskFilter] = useState<'' | 'medium' | 'high'>('');
  const [selected, setSelected] = useState<SafetyLog | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (riskFilter) params.set('risk_min', riskFilter);
      const [logsRes, statsRes] = await Promise.all([
        fetch(`/api/safety/logs?${params}`),
        fetch('/api/safety/stats'),
      ]);
      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(data.logs || []);
      }
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [riskFilter]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 className="card-title">🛡️ Safety-Logs</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <select value={riskFilter} onChange={e => setRiskFilter(e.target.value as any)}
                  className="input" style={{ padding: '6px 10px' }}>
            <option value="">Alle Risiken</option>
            <option value="medium">≥ Medium</option>
            <option value="high">Nur High</option>
          </select>
          <button className="btn btn-sm" onClick={load} disabled={loading}>
            {loading ? '…' : '↻ Neu laden'}
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginBottom: 16 }}>
          <div className="card"><div style={{ fontSize: 24, fontWeight: 600 }}>{stats.total}</div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Events gesamt</div></div>
          <div className="card"><div style={{ fontSize: 24, fontWeight: 600, color: RISK_COLORS.high }}>{stats.by_risk.high || 0}</div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>High Risk</div></div>
          <div className="card"><div style={{ fontSize: 24, fontWeight: 600, color: RISK_COLORS.medium }}>{stats.by_risk.medium || 0}</div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Medium Risk</div></div>
          <div className="card"><div style={{ fontSize: 24, fontWeight: 600 }}>{stats.escalated}</div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>LLM-eskaliert</div></div>
          <div className="card"><div style={{ fontSize: 24, fontWeight: 600 }}>{stats.rate_limited}</div><div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Rate-limited</div></div>
        </div>
      )}

      {stats && Object.keys(stats.by_legal).length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 6 }}>Verteilung nach Rechtsfeld</div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {Object.entries(stats.by_legal).map(([k, v]) => (
              <span key={k} style={{ padding: '4px 10px', background: '#f3f4f6', borderRadius: 12, fontSize: 13 }}>
                {LEGAL_LABELS[k] || k}: <strong>{v}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Logs list + detail */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div style={{ maxHeight: '60vh', overflowY: 'auto' }}>
          {logs.length === 0 && (
            <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
              Keine Safety-Events gefunden.
            </div>
          )}
          {logs.map(log => (
            <div key={log.id}
                 className="card"
                 onClick={() => setSelected(log)}
                 style={{
                   cursor: 'pointer',
                   borderLeft: `3px solid ${RISK_COLORS[log.risk_level]}`,
                   marginBottom: 8,
                   padding: 10,
                   background: selected?.id === log.id ? '#f9fafb' : undefined,
                 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                <span style={{ color: RISK_COLORS[log.risk_level], fontWeight: 600 }}>
                  {log.risk_level.toUpperCase()}
                </span>
                <span style={{ color: 'var(--text-muted)' }}>
                  {new Date(log.created_at).toLocaleString('de-DE')}
                </span>
              </div>
              <div style={{ fontSize: 13, marginTop: 4, color: '#374151', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {log.message || '(leer)'}
              </div>
              <div style={{ fontSize: 11, marginTop: 4, color: 'var(--text-muted)' }}>
                {log.legal_flags.map(f => LEGAL_LABELS[f] || f).join(' · ')}
                {log.rate_limited ? ' · ⏱ rate-limited' : ''}
                {log.escalated ? ' · 🤖 LLM' : ''}
              </div>
            </div>
          ))}
        </div>

        {/* Detail */}
        <div>
          {!selected && (
            <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
              Wähle einen Eintrag links aus.
            </div>
          )}
          {selected && (
            <div className="card">
              <div style={{ marginBottom: 12 }}>
                <span style={{ padding: '4px 10px', background: RISK_COLORS[selected.risk_level], color: '#fff', borderRadius: 4, fontSize: 12, fontWeight: 600 }}>
                  {selected.risk_level.toUpperCase()}
                </span>
                <span style={{ marginLeft: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                  Session: {selected.session_id.slice(0, 8)}…
                </span>
              </div>
              <div style={{ marginBottom: 10 }}>
                <strong>Nachricht:</strong>
                <div style={{ background: '#f9fafb', padding: 8, borderRadius: 4, marginTop: 4, fontSize: 13 }}>
                  {selected.message || '(leer)'}
                </div>
              </div>
              <div style={{ marginBottom: 8, fontSize: 13 }}>
                <strong>Stages:</strong> {selected.stages_run.join(' → ') || '–'}
              </div>
              <div style={{ marginBottom: 8, fontSize: 13 }}>
                <strong>Gründe:</strong> {selected.reasons.join(', ') || '–'}
              </div>
              <div style={{ marginBottom: 8, fontSize: 13 }}>
                <strong>Rechtsfelder:</strong> {selected.legal_flags.map(f => LEGAL_LABELS[f] || f).join(', ') || '–'}
              </div>
              {selected.flagged_categories.length > 0 && (
                <div style={{ marginBottom: 8, fontSize: 13 }}>
                  <strong>Geflaggte Kategorien:</strong> {selected.flagged_categories.join(', ')}
                </div>
              )}
              {selected.blocked_tools.length > 0 && (
                <div style={{ marginBottom: 8, fontSize: 13 }}>
                  <strong>Blockierte Tools:</strong> {selected.blocked_tools.join(', ')}
                </div>
              )}
              {selected.enforced_pattern && (
                <div style={{ marginBottom: 8, fontSize: 13 }}>
                  <strong>Erzwungenes Pattern:</strong> {selected.enforced_pattern}
                </div>
              )}
              {Object.keys(selected.categories_json || {}).length > 0 && (
                <details style={{ marginTop: 12 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13 }}>Alle Kategorie-Scores</summary>
                  <pre style={{ fontSize: 11, background: '#f3f4f6', padding: 8, borderRadius: 4, marginTop: 4, overflowX: 'auto' }}>
{JSON.stringify(selected.categories_json, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
