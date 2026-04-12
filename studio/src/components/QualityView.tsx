'use client';

import { useState, useEffect, useCallback } from 'react';

/* ── Types ─────────────────────────────────────────────────────────── */
interface QualityLog {
  id: number;
  session_id: string;
  message: string;
  turn_count: number;
  persona_id: string;
  intent_id: string;
  state_id: string;
  turn_type: string;
  pattern_id: string;
  confidence: number;
  phase2_winner_score: number;
  phase2_score_gap: number;
  eliminated_count: number;
  candidate_count: number;
  response_length: number;
  cards_count: number;
  degradation: number;
  missing_slots: string;
  page: string;
  device: string;
  created_at: string;
}

interface QualityStats {
  total_turns: number;
  pattern_distribution: Record<string, number>;
  intent_distribution: Record<string, number>;
  avg_confidence: number;
  avg_score_gap: number;
  degradation_rate: number;
  tight_races: number;
  empty_entity_rate: number;
  avg_response_length: number;
}

/* ── Helpers ───────────────────────────────────────────────────────── */
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const num = (v: number, d = 2) => v?.toFixed(d) ?? '–';

function BarChart({ data, color = 'var(--primary)' }: { data: Record<string, number>; color?: string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  if (entries.length === 0) return <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Keine Daten</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {entries.map(([label, count]) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
          <span style={{ width: 90, textAlign: 'right', color: 'var(--text-muted)', flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
          <div style={{ flex: 1, background: '#f3f4f6', borderRadius: 4, height: 18, position: 'relative' }}>
            <div style={{ width: `${(count / max) * 100}%`, background: color, borderRadius: 4, height: '100%', minWidth: 2 }} />
          </div>
          <span style={{ width: 36, textAlign: 'right', fontWeight: 600, fontSize: 11 }}>{count}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────── */
export default function QualityView() {
  const [logs, setLogs] = useState<QualityLog[]>([]);
  const [stats, setStats] = useState<QualityStats | null>(null);
  const [selected, setSelected] = useState<QualityLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<'overview' | 'logs'>('overview');

  /* Filters */
  const [filterPattern, setFilterPattern] = useState('');
  const [filterIntent, setFilterIntent] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (filterPattern) params.set('pattern_id', filterPattern);
      if (filterIntent) params.set('intent_id', filterIntent);
      const [logsRes, statsRes] = await Promise.all([
        fetch(`/api/quality/logs?${params}`),
        fetch('/api/quality/stats'),
      ]);
      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(data.logs || []);
      }
      if (statsRes.ok) {
        setStats(await statsRes.json());
      }
    } catch (e) {
      console.error('Quality load error', e);
    } finally {
      setLoading(false);
    }
  }, [filterPattern, filterIntent]);

  useEffect(() => { load(); }, [load]);

  /* ── Derived metrics ─────────────────────────────────────────────── */
  const tightRaceLogs = logs.filter(l => l.phase2_score_gap < 0.02 && l.phase2_score_gap >= 0);
  const degradedLogs = logs.filter(l => l.degradation);

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 className="card-title">📊 Quality-Analytics</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className={`btn btn-sm ${tab === 'overview' ? 'btn-primary' : ''}`} onClick={() => setTab('overview')}>Übersicht</button>
          <button className={`btn btn-sm ${tab === 'logs' ? 'btn-primary' : ''}`} onClick={() => setTab('logs')}>Logs</button>
          <button className="btn btn-sm" onClick={load} disabled={loading}>
            {loading ? '…' : '↻ Neu laden'}
          </button>
        </div>
      </div>

      {/* ════════════════════ OVERVIEW TAB ════════════════════ */}
      {tab === 'overview' && stats && (
        <>
          {/* KPI Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12, marginBottom: 20 }}>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700 }}>{stats.total_turns}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Turns gesamt</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700 }}>{num(stats.avg_confidence)}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Ø Confidence</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700 }}>{num(stats.avg_score_gap, 3)}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Ø Score-Gap</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700, color: stats.degradation_rate > 0.1 ? 'var(--danger)' : 'var(--success)' }}>
                {pct(stats.degradation_rate)}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Degradation-Rate</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700, color: stats.tight_races > 5 ? 'var(--warning)' : undefined }}>
                {stats.tight_races}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Tight Races (&lt;0.02)</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700 }}>{pct(stats.empty_entity_rate)}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Leere Entities</div>
            </div>
            <div className="card">
              <div style={{ fontSize: 28, fontWeight: 700 }}>{Math.round(stats.avg_response_length)}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Ø Antwortlänge (Zeichen)</div>
            </div>
          </div>

          {/* Charts */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
            <div className="card">
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Pattern-Verteilung</div>
              <BarChart data={stats.pattern_distribution} color="var(--primary)" />
            </div>
            <div className="card">
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 10 }}>Intent-Verteilung</div>
              <BarChart data={stats.intent_distribution} color="#8B5CF6" />
            </div>
          </div>

          {/* Alerts */}
          {(stats.degradation_rate > 0.05 || stats.tight_races > 3 || stats.empty_entity_rate > 0.3) && (
            <div className="card" style={{ borderLeft: '3px solid var(--warning)', marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>⚠️ Hinweise</div>
              <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {stats.degradation_rate > 0.05 && (
                  <div>• Degradation-Rate bei {pct(stats.degradation_rate)} — Patterns oder Slots prüfen</div>
                )}
                {stats.tight_races > 3 && (
                  <div>• {stats.tight_races} Tight Races — Pattern-Signale schärfen, um eindeutigere Zuordnung zu erreichen</div>
                )}
                {stats.empty_entity_rate > 0.3 && (
                  <div>• {pct(stats.empty_entity_rate)} Turns ohne Entities — Entity-Erkennung prüfen</div>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {tab === 'overview' && !stats && !loading && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Keine Quality-Daten vorhanden. Starte einen Chat, um Daten zu sammeln.
        </div>
      )}

      {/* ════════════════════ LOGS TAB ════════════════════ */}
      {tab === 'logs' && (
        <>
          {/* Filters */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              className="input"
              placeholder="Pattern-ID (z.B. PAT-10)"
              value={filterPattern}
              onChange={e => setFilterPattern(e.target.value)}
              style={{ padding: '6px 10px', width: 180 }}
            />
            <input
              className="input"
              placeholder="Intent-ID (z.B. INT-W-06)"
              value={filterIntent}
              onChange={e => setFilterIntent(e.target.value)}
              style={{ padding: '6px 10px', width: 180 }}
            />
            {(filterPattern || filterIntent) && (
              <button className="btn btn-sm" onClick={() => { setFilterPattern(''); setFilterIntent(''); }}>✕ Filter zurücksetzen</button>
            )}
            <span style={{ fontSize: 12, color: 'var(--text-muted)', alignSelf: 'center', marginLeft: 'auto' }}>
              {logs.length} Einträge
            </span>
          </div>

          {/* Split: List + Detail */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Log list */}
            <div style={{ maxHeight: '65vh', overflowY: 'auto' }}>
              {logs.length === 0 && (
                <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                  Keine Quality-Logs gefunden.
                </div>
              )}
              {logs.map(log => {
                const isTight = log.phase2_score_gap >= 0 && log.phase2_score_gap < 0.02;
                const borderColor = log.degradation ? 'var(--danger)' : isTight ? 'var(--warning)' : 'var(--border)';
                return (
                  <div
                    key={log.id}
                    className="card"
                    onClick={() => setSelected(log)}
                    style={{
                      cursor: 'pointer',
                      borderLeft: `3px solid ${borderColor}`,
                      marginBottom: 8,
                      padding: 10,
                      background: selected?.id === log.id ? 'var(--primary-lt)' : undefined,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{log.pattern_id}</span>
                      <span style={{ color: 'var(--text-muted)' }}>
                        {new Date(log.created_at).toLocaleString('de-DE')}
                      </span>
                    </div>
                    <div style={{ fontSize: 13, marginTop: 4, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {log.message || '(leer)'}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                      <span>{log.intent_id}</span>
                      <span>·</span>
                      <span>Conf {num(log.confidence)}</span>
                      <span>·</span>
                      <span>Gap {num(log.phase2_score_gap, 3)}</span>
                      {log.degradation ? <span style={{ color: 'var(--danger)' }}>· Degradation</span> : null}
                      {isTight ? <span style={{ color: 'var(--warning)' }}>· Tight Race</span> : null}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Detail */}
            <div>
              {!selected && (
                <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 32 }}>
                  Wähle einen Eintrag links aus.
                </div>
              )}
              {selected && (
                <div className="card" style={{ position: 'sticky', top: 16 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <span style={{ padding: '3px 10px', background: 'var(--primary)', color: '#fff', borderRadius: 4, fontSize: 12, fontWeight: 600 }}>
                      {selected.pattern_id}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                      Turn {selected.turn_count} · {selected.turn_type || '–'}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                      Session: {selected.session_id.slice(0, 8)}…
                    </span>
                  </div>

                  <div style={{ background: '#f9fafb', padding: 10, borderRadius: 6, marginBottom: 12, fontSize: 13 }}>
                    {selected.message || '(leer)'}
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 }}>
                    <div><span style={{ color: 'var(--text-muted)' }}>Persona:</span> {selected.persona_id}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Intent:</span> {selected.intent_id}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>State:</span> {selected.state_id}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Device:</span> {selected.device}</div>
                  </div>

                  <div className="nav-divider" style={{ margin: '12px 0' }} />

                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Pattern-Engine</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 }}>
                    <div><span style={{ color: 'var(--text-muted)' }}>Winner Score:</span> {num(selected.phase2_winner_score, 3)}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Score Gap:</span> <span style={{ color: selected.phase2_score_gap < 0.02 ? 'var(--warning)' : undefined }}>{num(selected.phase2_score_gap, 3)}</span></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Confidence:</span> {num(selected.confidence)}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Kandidaten:</span> {selected.candidate_count} (elim. {selected.eliminated_count})</div>
                  </div>

                  <div className="nav-divider" style={{ margin: '12px 0' }} />

                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>Antwort</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13 }}>
                    <div><span style={{ color: 'var(--text-muted)' }}>Länge:</span> {selected.response_length} Zeichen</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Cards:</span> {selected.cards_count}</div>
                    <div><span style={{ color: 'var(--text-muted)' }}>Seite:</span> {selected.page || '–'}</div>
                    <div>
                      <span style={{ color: 'var(--text-muted)' }}>Degradation:</span>{' '}
                      {selected.degradation
                        ? <span style={{ color: 'var(--danger)', fontWeight: 600 }}>Ja</span>
                        : <span style={{ color: 'var(--success)' }}>Nein</span>}
                    </div>
                  </div>

                  {selected.missing_slots && (
                    <div style={{ marginTop: 8, fontSize: 13 }}>
                      <span style={{ color: 'var(--text-muted)' }}>Fehlende Slots:</span> {selected.missing_slots}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
