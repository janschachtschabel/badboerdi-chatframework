'use client';

import { useState, useEffect, useCallback } from 'react';

/* ── Types ─────────────────────────────────────────────────────────── */

interface Persona { id: string; label: string; description?: string; }
interface Intent { id: string; label: string; description?: string; }

interface RunSummary {
  id: string;
  created_at: string;
  completed_at: string | null;
  status: 'running' | 'done' | 'failed';
  mode: 'scenarios' | 'conversations' | 'both';
  config_slug: string;
  total_turns: number;
  avg_score: number;
  personas: string[];
  intents: string[];
  error_message?: string;
  target_turns?: number;
  current_activity?: string;
}

interface TurnJudge {
  intent_fit: number;
  persona_tone: number;
  pattern_match: number;
  safety: number;
  info_quality: number;
  total: number;
  notes: string;
  issues?: string[];
  missing_info?: string[];
}

interface TraceEntry {
  step: string;
  label: string;
  duration_ms: number;
  data?: Record<string, unknown>;
}

interface RunTurn {
  user: string;
  bot: string;
  debug: {
    pattern?: string;
    persona?: string;
    intent?: string;
    safety?: string;
    tools_called?: string[];
    trace?: TraceEntry[];
    state?: string;
    intent_confidence?: number;
    persona_confidence?: number;
  };
  judge?: TurnJudge;
  error?: string;
}

interface RunConversation {
  kind: 'scenario' | 'conversation';
  persona_id: string;
  intent_id: string;
  session_id: string | null;
  ended_early?: boolean;
  turns: RunTurn[];
}

interface RunDetail extends RunSummary {
  summary: {
    matrix?: Record<string, Record<string, number>>;
    pattern_usage?: Record<string, number>;
    avg_score?: number;
    total_judged_turns?: number;
    target_turns?: number;
    current_activity?: string;
  };
  conversations: RunConversation[];
}

interface CostEstimate {
  scenarios: number;
  conversations: number;
  total_turns: number;
  chat_calls: number;
  judge_calls: number;
  simulator_calls: number;
  est_usd: number;
  est_usd_min?: number;
  est_usd_max?: number;
}

// Analytics lives on the Quality tab now — types kept out of this file.

/* ── Helpers ───────────────────────────────────────────────────────── */

const scoreColor = (s: number) => {
  if (s >= 0.8) return '#10B981';       // green
  if (s >= 0.6) return '#84CC16';       // lime
  if (s >= 0.4) return '#F59E0B';       // amber
  if (s > 0)   return '#EF4444';        // red
  return '#6B7280';                      // gray (no data)
};

const formatDate = (iso: string) => {
  if (!iso) return '–';
  try {
    // Ensure the string has a timezone marker — old rows (pre-fix) may lack
    // one; we interpret those as UTC to match what the backend wrote.
    const needsZ = !/[Zz]|[+-]\d{2}:?\d{2}$/.test(iso);
    const parsed = new Date(needsZ ? iso + 'Z' : iso);
    if (isNaN(parsed.getTime())) return iso;
    return parsed.toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
  } catch { return iso; }
};

/* ── Main Component ────────────────────────────────────────────────── */

export default function EvaluationView() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunDetail | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch('/api/eval/runs');
      if (!r.ok) {
        if (r.status === 404) {
          throw new Error(
            'Der Evaluation-Endpunkt antwortet mit 404. Das Backend muss einmal ' +
            'neu gestartet werden, damit der Eval-Router geladen wird.'
          );
        }
        throw new Error(`HTTP ${r.status}`);
      }
      const data = await r.json();
      setRuns(Array.isArray(data.runs) ? data.runs : []);
      setError(null);
    } catch (e: any) {
      setError(e.message);
      setRuns([]);
    } finally { setLoading(false); }
  }, []);

  // Analytics moved to Quality tab — this view only manages eval runs now.

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // Auto-poll running jobs every 3s
  useEffect(() => {
    const hasRunning = runs.some(r => r.status === 'running');
    if (!hasRunning) return;
    const t = setInterval(() => loadRuns(), 3000);
    return () => clearInterval(t);
  }, [runs, loadRuns]);

  const openRun = async (runId: string) => {
    setLoading(true);
    try {
      const r = await fetch(`/api/eval/runs/${runId}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSelectedRun(await r.json());
    } catch (e: any) {
      setError(e.message);
    } finally { setLoading(false); }
  };

  const deleteRun = async (runId: string) => {
    if (!confirm(`Run ${runId} löschen?`)) return;
    await fetch(`/api/eval/runs/${runId}`, { method: 'DELETE' });
    if (selectedRun?.id === runId) setSelectedRun(null);
    loadRuns();
  };

  const deleteAllRuns = async () => {
    if (runs.length === 0) return;
    const ok = confirm(
      `Wirklich alle ${runs.length} Eval-Protokolle löschen?\n\n` +
      `Das entfernt auch die zugehörigen quality_logs-Einträge, damit die ` +
      `Quality-Statistik (mit Scope „Nur Eval") sauber zurückgesetzt wird.`
    );
    if (!ok) return;
    const r = await fetch('/api/eval/runs?confirm=true', { method: 'DELETE' });
    if (!r.ok) { alert(`Fehler beim Löschen: HTTP ${r.status}`); return; }
    // Cascade the eval quality_logs so Quality analytics match
    await fetch('/api/eval/quality-logs', { method: 'DELETE' });
    setSelectedRun(null);
    loadRuns();
  };

  const deleteFailedRuns = async () => {
    const failed = runs.filter(r => r.status === 'failed').length;
    if (failed === 0) { alert('Keine fehlgeschlagenen Runs vorhanden.'); return; }
    if (!confirm(`${failed} fehlgeschlagene Runs löschen?`)) return;
    await fetch('/api/eval/runs?status=failed', { method: 'DELETE' });
    loadRuns();
  };

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Evaluation · Persona-getriebene Chat-Tests</h2>
        <button
          className="btn-primary"
          onClick={() => setShowNew(true)}
          style={{ padding: '8px 16px', background: 'var(--primary)', color: '#fff', border: 0, borderRadius: 6, cursor: 'pointer' }}
        >
          ＋ Neuer Eval-Run
        </button>
      </div>

      {error && (
        <div style={{ padding: 12, background: '#FEF2F2', color: '#991B1B', borderRadius: 6, marginBottom: 16 }}>
          {error}
        </div>
      )}

      {!selectedRun && (
        <>
          {runs.length > 0 && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 12, justifyContent: 'flex-end' }}>
              <button onClick={deleteFailedRuns}
                style={{ padding: '6px 10px', background: '#fff', border: '1px solid #D1D5DB', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
                Fehlgeschlagene löschen
              </button>
              <button onClick={deleteAllRuns}
                style={{ padding: '6px 10px', background: '#fff', color: '#DC2626', border: '1px solid #FCA5A5', borderRadius: 4, cursor: 'pointer', fontSize: 12 }}>
                Alle Protokolle löschen
              </button>
            </div>
          )}
          <RunsList runs={runs} onOpen={openRun} onDelete={deleteRun} loading={loading} />

          {/* Hinweis auf Quality-Tab statt redundanter Analytics-Panel hier. */}
          <div style={{
            marginTop: 24, padding: 12, background: '#F0F9FF', borderRadius: 6,
            fontSize: 13, color: '#0C4A6E', border: '1px solid #BAE6FD',
          }}>
            💡 <strong>Analytics &amp; Pattern-Diagnose:</strong> Die Pattern-Häufigkeiten,
            Intent-Verteilung und Tight-Race-Analyse sind im <strong>Quality</strong>-Tab.
            Dort lässt sich per Scope-Umschalter zwischen „Alle", „Produktion" und „Nur Eval"
            wechseln — so vergleichst du, wie sich reale Nutzung und Eval-Runs unterscheiden.
          </div>
        </>
      )}

      {selectedRun && (
        <RunDetailView run={selectedRun} onBack={() => setSelectedRun(null)} />
      )}

      {showNew && (
        <NewRunModal
          onClose={() => setShowNew(false)}
          onStarted={() => { setShowNew(false); loadRuns(); }}
        />
      )}
    </div>
  );
}

/* ── Runs List ─────────────────────────────────────────────────────── */

function RunsList({ runs, onOpen, onDelete, loading }: {
  runs: RunSummary[]; onOpen: (id: string) => void; onDelete: (id: string) => void; loading: boolean;
}) {
  if (loading && runs.length === 0) return <div>Lade …</div>;
  if (runs.length === 0) return (
    <div style={{ padding: 24, background: '#F9FAFB', borderRadius: 8, textAlign: 'center', color: 'var(--text-muted)' }}>
      Noch keine Eval-Runs. Klicke oben auf <strong>Neuer Eval-Run</strong>, um einen zu starten.
    </div>
  );
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
      <thead>
        <tr style={{ borderBottom: '2px solid #E5E7EB', textAlign: 'left' }}>
          <th style={{ padding: 8 }}>ID</th>
          <th style={{ padding: 8 }}>Start</th>
          <th style={{ padding: 8 }}>Modus</th>
          <th style={{ padding: 8 }}>Status</th>
          <th style={{ padding: 8, textAlign: 'right' }}>Turns</th>
          <th style={{ padding: 8, textAlign: 'right' }}>Ø Score</th>
          <th style={{ padding: 8 }}>Umfang</th>
          <th style={{ padding: 8 }}></th>
        </tr>
      </thead>
      <tbody>
        {runs.map(r => (
          <tr key={r.id} style={{ borderBottom: '1px solid #F3F4F6' }}>
            <td style={{ padding: 8, fontFamily: 'monospace', fontSize: 12 }}>
              <button onClick={() => onOpen(r.id)} style={{ background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer', padding: 0 }}>
                {r.id}
              </button>
            </td>
            <td style={{ padding: 8 }}>{formatDate(r.created_at)}</td>
            <td style={{ padding: 8 }}>{r.mode}</td>
            <td style={{ padding: 8 }}>
              {r.status === 'running' && (
                <div>
                  <div style={{ color: '#2563EB', fontSize: 12 }}>⏳ läuft</div>
                  {r.target_turns && r.target_turns > 0 && (
                    <div style={{ marginTop: 2, width: 140, background: '#E5E7EB', borderRadius: 2, height: 5, overflow: 'hidden' }}>
                      <div style={{
                        width: `${Math.min(100, ((r.total_turns ?? 0) / r.target_turns) * 100)}%`,
                        height: '100%', background: '#2563EB', transition: 'width 0.5s',
                      }} />
                    </div>
                  )}
                  {r.current_activity && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                         title={r.current_activity}>
                      {r.current_activity}
                    </div>
                  )}
                </div>
              )}
              {r.status === 'done' && <span style={{ color: '#059669' }}>✓ fertig</span>}
              {r.status === 'failed' && <span style={{ color: '#DC2626' }} title={r.error_message}>✕ Fehler</span>}
            </td>
            <td style={{ padding: 8, textAlign: 'right' }}>
              {r.status === 'running' && r.target_turns ?
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{r.total_turns ?? 0} / {r.target_turns}</span> :
                (r.total_turns ?? 0)}
            </td>
            <td style={{ padding: 8, textAlign: 'right' }}>
              {r.status === 'done' && typeof r.avg_score === 'number' ? (
                <span style={{ color: scoreColor(r.avg_score), fontWeight: 600 }}>
                  {(r.avg_score * 100).toFixed(0)}%
                </span>
              ) : '–'}
            </td>
            <td style={{ padding: 8, fontSize: 12, color: 'var(--text-muted)' }}>
              {r.personas.length}P × {r.intents.length}I
            </td>
            <td style={{ padding: 8, textAlign: 'right' }}>
              <button onClick={() => onDelete(r.id)} title="löschen"
                      style={{ background: 'none', border: 0, cursor: 'pointer', color: '#9CA3AF' }}>🗑</button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/* ── Run Detail (Matrix + Transcripts) ─────────────────────────────── */

function RunDetailView({ run, onBack }: { run: RunDetail; onBack: () => void }) {
  const [selectedConv, setSelectedConv] = useState<RunConversation | null>(null);
  const [sortMode, setSortMode] = useState<'score_asc' | 'score_desc' | 'default'>('score_asc');
  const matrix = run.summary?.matrix || {};
  const patternUsage = run.summary?.pattern_usage || {};
  const conversations = run.conversations || [];
  const avgScore = typeof run.avg_score === 'number' ? run.avg_score : 0;
  const totalTurns = typeof run.total_turns === 'number' ? run.total_turns : 0;
  const personaIds = Object.keys(matrix);
  const intentIds = Array.from(new Set(Object.values(matrix).flatMap(o => Object.keys(o || {}))));

  // Collect every turn with a problem (score < 1.0) for the focus section
  type ProblemTurn = { conv: RunConversation; turnIdx: number; turn: RunTurn };
  const problems: ProblemTurn[] = [];
  conversations.forEach(c => {
    (c.turns || []).forEach((t, idx) => {
      if (t.judge && typeof t.judge.total === 'number' && t.judge.total < 1.0) {
        problems.push({ conv: c, turnIdx: idx, turn: t });
      }
    });
  });
  problems.sort((a, b) => (a.turn.judge?.total || 0) - (b.turn.judge?.total || 0));

  // Sort conversations by their avg score
  const convsWithAvg = conversations.map(c => {
    const judged = (c.turns || []).filter(t => t.judge);
    const convAvg = judged.length === 0 ? 0 :
      judged.reduce((a, t) => a + (t.judge?.total || 0), 0) / judged.length;
    return { conv: c, convAvg };
  });
  if (sortMode === 'score_asc') convsWithAvg.sort((a, b) => a.convAvg - b.convAvg);
  else if (sortMode === 'score_desc') convsWithAvg.sort((a, b) => b.convAvg - a.convAvg);

  return (
    <div>
      <button onClick={onBack} style={{ marginBottom: 12, background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer' }}>
        ← zurück zur Liste
      </button>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 16, marginBottom: 24 }}>
        <StatCard label="Gesamt-Score" value={`${(avgScore * 100).toFixed(0)}%`} color={scoreColor(avgScore)} />
        <StatCard label="Turns bewertet" value={totalTurns.toString()} />
        <StatCard label="Konversationen" value={conversations.length.toString()} />
        <StatCard label="Probleme (<100%)" value={problems.length.toString()}
                  color={problems.length > 0 ? '#EF4444' : '#10B981'} />
      </div>

      {/* Problem-Fokus: zeigt alle Turns mit Score < 100% mit konkreten Issues */}
      {problems.length > 0 && (
        <div style={{ marginBottom: 24, padding: 16, background: '#FEF2F2', borderRadius: 8, border: '1px solid #FCA5A5' }}>
          <h3 style={{ marginTop: 0, color: '#991B1B' }}>
            🔍 {problems.length} Turn{problems.length !== 1 ? 's' : ''} mit Problemen
          </h3>
          <p style={{ fontSize: 12, color: '#7F1D1D', marginBottom: 12 }}>
            Alle Turns mit Score unter 100%, sortiert nach Schwere (niedrigster Score zuerst).
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 400, overflowY: 'auto' }}>
            {problems.slice(0, 20).map((p, i) => {
              const j = p.turn.judge!;
              const allDims: Array<[string, number]> = [
                ['Intent', j.intent_fit], ['Ton', j.persona_tone],
                ['Pattern', j.pattern_match], ['Safety', j.safety], ['Info', j.info_quality],
              ];
              const weakDims = allDims.filter(([, v]) => v < 2);
              return (
                <div key={i}
                     onClick={() => setSelectedConv(p.conv)}
                     style={{
                       padding: 8, background: '#fff', borderRadius: 4, cursor: 'pointer',
                       borderLeft: `3px solid ${scoreColor(j.total)}`,
                     }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                    <span><strong>{p.conv.persona_id}</strong> × <strong>{p.conv.intent_id}</strong>{' '}
                      <span style={{ color: 'var(--text-muted)' }}>· Turn {p.turnIdx + 1} · Pattern {p.turn.debug?.pattern || '?'}</span></span>
                    <span style={{ color: scoreColor(j.total), fontWeight: 600 }}>
                      {(j.total * 100).toFixed(0)}%
                    </span>
                  </div>
                  <div style={{ fontSize: 11, display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                    {weakDims.map(([label, v]) => (
                      <span key={label} style={{ padding: '1px 5px', background: v === 1 ? '#FDE68A' : '#FECACA', borderRadius: 2 }}>
                        {label}: {v}/2
                      </span>
                    ))}
                  </div>
                  {j.issues && j.issues.length > 0 && (
                    <ul style={{ fontSize: 12, margin: '4px 0', paddingLeft: 20, color: '#7F1D1D' }}>
                      {j.issues.map((issue, k) => <li key={k}>{issue}</li>)}
                    </ul>
                  )}
                  {j.missing_info && j.missing_info.length > 0 && (
                    <div style={{ fontSize: 11, color: '#7F1D1D', marginTop: 4 }}>
                      <strong>Fehlt:</strong> {j.missing_info.join(' · ')}
                    </div>
                  )}
                  {(!j.issues || j.issues.length === 0) && j.notes && (
                    <div style={{ fontSize: 12, color: '#7F1D1D', fontStyle: 'italic' }}>„{j.notes}"</div>
                  )}
                </div>
              );
            })}
            {problems.length > 20 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 8 }}>
                … und {problems.length - 20} weitere. Nutze die Transkript-Liste unten (Sortierung: niedrigster Score zuerst).
              </div>
            )}
          </div>
        </div>
      )}

      {/* Heatmap */}
      {personaIds.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3>Persona × Intent Matrix</h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ padding: 6, textAlign: 'left', position: 'sticky', left: 0, background: '#fff' }}>Persona \ Intent</th>
                  {intentIds.map(i => (
                    <th key={i} style={{ padding: 6, fontWeight: 500, writingMode: 'vertical-rl', transform: 'rotate(180deg)', minWidth: 28 }}>{i}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {personaIds.map(p => (
                  <tr key={p}>
                    <td style={{ padding: 6, fontWeight: 500, position: 'sticky', left: 0, background: '#fff' }}>{p}</td>
                    {intentIds.map(i => {
                      const v = matrix[p]?.[i];
                      return (
                        <td key={i}
                            title={`${p} × ${i}: ${v !== undefined ? (v * 100).toFixed(0) + '%' : '–'}`}
                            style={{
                              padding: 0, minWidth: 40, height: 32, textAlign: 'center',
                              background: v !== undefined ? scoreColor(v) : '#F3F4F6',
                              color: v !== undefined && v < 0.5 ? '#fff' : '#111',
                              fontSize: 11,
                            }}>
                          {v !== undefined ? (v * 100).toFixed(0) : ''}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pattern Usage in this run */}
      {Object.keys(patternUsage).length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <h3>Pattern-Häufigkeit in diesem Run</h3>
          <BarChart data={patternUsage} />
        </div>
      )}

      {/* Transcripts */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3>Transkripte ({conversations.length})</h3>
        <div style={{ fontSize: 12 }}>
          <label style={{ marginRight: 4, color: 'var(--text-muted)' }}>Sortierung:</label>
          <select value={sortMode} onChange={e => setSortMode(e.target.value as typeof sortMode)}
                  style={{ padding: '3px 6px', border: '1px solid #D1D5DB', borderRadius: 4, fontSize: 12 }}>
            <option value="score_asc">Niedrigster Score zuerst</option>
            <option value="score_desc">Höchster Score zuerst</option>
            <option value="default">Reihenfolge des Runs</option>
          </select>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 16 }}>
        <div style={{ maxHeight: 600, overflowY: 'auto', border: '1px solid #E5E7EB', borderRadius: 6 }}>
          {convsWithAvg.map(({ conv: c, convAvg }, idx) => {
            const turns = c.turns || [];
            return (
              <button key={idx}
                onClick={() => setSelectedConv(c)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: 10,
                  borderBottom: '1px solid #F3F4F6', background: selectedConv === c ? '#F3F4F6' : '#fff',
                  border: 0, cursor: 'pointer',
                }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{c.persona_id} · {c.intent_id}</span>
                  <span style={{ fontSize: 11, color: scoreColor(convAvg), fontWeight: 600 }}>
                    {(convAvg * 100).toFixed(0)}%
                  </span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {c.kind} · {turns.length} turn{turns.length !== 1 ? 's' : ''}
                  {c.ended_early ? ' · früh beendet' : ''}
                </div>
              </button>
            );
          })}
        </div>

        <div style={{ border: '1px solid #E5E7EB', borderRadius: 6, padding: 16, maxHeight: 600, overflowY: 'auto' }}>
          {!selectedConv && <div style={{ color: 'var(--text-muted)' }}>Konversation auswählen …</div>}
          {selectedConv && <ConversationView conv={selectedConv} />}
        </div>
      </div>
    </div>
  );
}

function ConversationView({ conv }: { conv: RunConversation }) {
  const turns = conv.turns || [];
  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 13, color: 'var(--text-muted)' }}>
        <strong>{conv.persona_id}</strong> · <strong>{conv.intent_id}</strong> · {conv.kind}
        {conv.session_id && <> · <code style={{ fontSize: 11 }}>{conv.session_id}</code></>}
      </div>
      {turns.map((t, i) => (
        <div key={i} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px dashed #E5E7EB' }}>
          <div style={{ background: '#EFF6FF', padding: 8, borderRadius: 6, fontSize: 13, marginBottom: 6 }}>
            <strong>User:</strong> {t.user}
          </div>
          <div style={{ background: '#F9FAFB', padding: 8, borderRadius: 6, fontSize: 13 }}>
            <strong>Bot:</strong> {t.bot}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            Pattern: <code>{t.debug?.pattern || '?'}</code>
            {' · '}Intent: <code>{t.debug?.intent || '?'}</code>
            {' · '}Persona: <code>{t.debug?.persona || '?'}</code>
            {t.debug?.tools_called && t.debug.tools_called.length > 0 && (
              <> · Tools: {t.debug.tools_called.join(', ')}</>
            )}
          </div>
          <TurnTrace trace={t.debug?.trace || []} />
          {t.judge && (
            <>
              <div style={{ marginTop: 6, fontSize: 11, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <JudgeScore label="Intent" v={t.judge.intent_fit} />
                <JudgeScore label="Ton" v={t.judge.persona_tone} />
                <JudgeScore label="Pattern" v={t.judge.pattern_match} />
                <JudgeScore label="Safety" v={t.judge.safety} />
                <JudgeScore label="Info" v={t.judge.info_quality} />
                <span style={{ padding: '2px 6px', background: scoreColor(t.judge.total), color: '#fff', borderRadius: 3, fontWeight: 600 }}>
                  = {(t.judge.total * 100).toFixed(0)}%
                </span>
              </div>
              {t.judge.notes && (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic', marginTop: 4 }}>
                  „{t.judge.notes}"
                </div>
              )}
              {t.judge.issues && t.judge.issues.length > 0 && (
                <div style={{ marginTop: 6, padding: 6, background: '#FEF2F2', borderRadius: 4, fontSize: 12 }}>
                  <strong style={{ color: '#991B1B' }}>Probleme:</strong>
                  <ul style={{ margin: '2px 0', paddingLeft: 18, color: '#7F1D1D' }}>
                    {t.judge.issues.map((issue, k) => <li key={k}>{issue}</li>)}
                  </ul>
                </div>
              )}
              {t.judge.missing_info && t.judge.missing_info.length > 0 && (
                <div style={{ marginTop: 4, padding: 6, background: '#FEF3C7', borderRadius: 4, fontSize: 12 }}>
                  <strong style={{ color: '#78350F' }}>Fehlende Informationen:</strong>
                  <ul style={{ margin: '2px 0', paddingLeft: 18, color: '#78350F' }}>
                    {t.judge.missing_info.map((m, k) => <li key={k}>{m}</li>)}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      ))}
    </div>
  );
}

function JudgeScore({ label, v }: { label: string; v: number }) {
  const c = v >= 2 ? '#10B981' : v === 1 ? '#F59E0B' : '#EF4444';
  return (
    <span style={{ padding: '2px 6px', background: c, color: '#fff', borderRadius: 3 }}>
      {label}: {v}/2
    </span>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ padding: 16, background: '#F9FAFB', borderRadius: 8 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, color: color || '#111', marginTop: 4 }}>{value}</div>
    </div>
  );
}

/* ── Inline BarChart used for per-run pattern usage in the detail view ── */

function BarChart({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, v]) => v), 1);
  if (entries.length === 0) return <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Keine Daten</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {entries.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
          <span style={{ width: 160, textAlign: 'right', color: 'var(--text-muted)' }}>{k}</span>
          <div style={{ flex: 1, background: '#F3F4F6', borderRadius: 2, height: 16, position: 'relative' }}>
            <div style={{ width: `${(v / max) * 100}%`, height: '100%', background: 'var(--primary)', borderRadius: 2 }} />
          </div>
          <span style={{ width: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{v}</span>
        </div>
      ))}
    </div>
  );
}

/* ── New Run Modal ─────────────────────────────────────────────────── */

function NewRunModal({ onClose, onStarted }: { onClose: () => void; onStarted: () => void }) {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [intents, setIntents] = useState<Intent[]>([]);
  const [selectedPersonas, setSelectedPersonas] = useState<Set<string>>(new Set());
  const [selectedIntents, setSelectedIntents] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<'scenarios' | 'conversations' | 'both'>('scenarios');
  const [scenariosPerCombo, setScenariosPerCombo] = useState(1);
  const [turnsPerConv, setTurnsPerConv] = useState(3);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/eval/config')
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(data => {
        setPersonas(data.personas || []);
        setIntents(data.intents || []);
        setSelectedPersonas(new Set((data.personas || []).map((p: Persona) => p.id)));
        setSelectedIntents(new Set((data.intents || []).map((i: Intent) => i.id)));
      })
      .catch(e => setError(
        `Config konnte nicht geladen werden (${e.message}). Läuft das Backend mit der aktuellen Version? ` +
        `Nach dem Einspielen des Evaluation-Features muss das Backend einmal neu gestartet werden.`
      ));
  }, []);

  // Re-estimate on any change. Any non-ok response clears the estimate
  // instead of passing through malformed JSON (which would crash .toFixed()).
  useEffect(() => {
    fetch('/api/eval/estimate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        persona_ids: Array.from(selectedPersonas),
        intent_ids: Array.from(selectedIntents),
        scenarios_per_combo: scenariosPerCombo,
        turns_per_conv: turnsPerConv,
      }),
    })
      .then(r => r.ok ? r.json() : null)
      .then((data: CostEstimate | null) => {
        // Only accept well-formed estimates (est_usd must be a number)
        if (data && typeof data.est_usd === 'number') setEstimate(data);
        else setEstimate(null);
      })
      .catch(() => setEstimate(null));
  }, [mode, selectedPersonas, selectedIntents, scenariosPerCombo, turnsPerConv]);

  const toggleId = (set: Set<string>, setter: (s: Set<string>) => void, id: string) => {
    const next = new Set(set);
    next.has(id) ? next.delete(id) : next.add(id);
    setter(next);
  };

  const start = async () => {
    setStarting(true); setError(null);
    try {
      const r = await fetch('/api/eval/runs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          persona_ids: Array.from(selectedPersonas),
          intent_ids: Array.from(selectedIntents),
          scenarios_per_combo: scenariosPerCombo,
          turns_per_conv: turnsPerConv,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
      const data = await r.json();
      if (data.warnings && data.warnings.length > 0) {
        alert(`Run gestartet (${data.run_id}).\n\nWarnungen:\n${data.warnings.join('\n')}`);
      }
      onStarted();
    } catch (e: any) {
      setError(e.message);
      setStarting(false);
    }
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ background: '#fff', borderRadius: 8, maxWidth: 720, width: '100%', maxHeight: '90vh', overflowY: 'auto', padding: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>Neuer Eval-Run</h3>
          <button onClick={onClose} style={{ background: 'none', border: 0, fontSize: 24, cursor: 'pointer', color: '#6B7280' }}>×</button>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, fontWeight: 500 }}>Modus</label>
          <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
            {(['scenarios', 'conversations', 'both'] as const).map(m => (
              <button key={m} onClick={() => setMode(m)}
                style={{
                  padding: '6px 12px', border: '1px solid', borderColor: mode === m ? 'var(--primary)' : '#D1D5DB',
                  background: mode === m ? 'var(--primary)' : '#fff', color: mode === m ? '#fff' : '#111',
                  borderRadius: 6, cursor: 'pointer', fontSize: 13,
                }}>
                {m === 'scenarios' ? 'Szenarien (1-Turn)' : m === 'conversations' ? 'Dialoge (Multi-Turn)' : 'Beides'}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          {(mode === 'scenarios' || mode === 'both') && (
            <div>
              <label style={{ fontSize: 13, fontWeight: 500 }}>Szenarien pro Persona×Intent</label>
              <input type="number" min={1} max={10} value={scenariosPerCombo}
                     onChange={e => setScenariosPerCombo(Math.max(1, Math.min(10, +e.target.value)))}
                     style={{ width: '100%', padding: 6, marginTop: 4, border: '1px solid #D1D5DB', borderRadius: 4 }} />
            </div>
          )}
          {(mode === 'conversations' || mode === 'both') && (
            <div>
              <label style={{ fontSize: 13, fontWeight: 500 }}>Turns pro Dialog</label>
              <input type="number" min={1} max={10} value={turnsPerConv}
                     onChange={e => setTurnsPerConv(Math.max(1, Math.min(10, +e.target.value)))}
                     style={{ width: '100%', padding: 6, marginTop: 4, border: '1px solid #D1D5DB', borderRadius: 4 }} />
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <PillSelector title="Personas" items={personas} selected={selectedPersonas}
                        onToggle={id => toggleId(selectedPersonas, setSelectedPersonas, id)} />
          <PillSelector title="Intents" items={intents} selected={selectedIntents}
                        onToggle={id => toggleId(selectedIntents, setSelectedIntents, id)} />
        </div>

        {estimate && typeof estimate.est_usd === 'number' && (
          <div style={{ padding: 12, background: '#F0F9FF', borderRadius: 6, marginBottom: 16, fontSize: 13 }}>
            <strong>Geschätzter Aufwand:</strong> {estimate.scenarios} Szenarien + {estimate.conversations} Dialoge
            = <strong>{estimate.total_turns} Turns</strong> · {estimate.chat_calls} Chat-Calls · {estimate.judge_calls} Judge-Calls
            {' '}· <strong>~${estimate.est_usd.toFixed(2)}</strong>
            {typeof estimate.est_usd_min === 'number' && typeof estimate.est_usd_max === 'number' && (
              <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                {' '}(Spanne ${estimate.est_usd_min.toFixed(2)}–${estimate.est_usd_max.toFixed(2)})
              </span>
            )}
          </div>
        )}

        {error && <div style={{ padding: 8, background: '#FEF2F2', color: '#991B1B', borderRadius: 4, marginBottom: 12 }}>{error}</div>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} disabled={starting}
                  style={{ padding: '8px 16px', background: '#fff', border: '1px solid #D1D5DB', borderRadius: 6, cursor: 'pointer' }}>
            Abbrechen
          </button>
          <button onClick={start} disabled={starting || selectedPersonas.size === 0 || selectedIntents.size === 0}
                  style={{ padding: '8px 16px', background: 'var(--primary)', color: '#fff', border: 0, borderRadius: 6, cursor: 'pointer' }}>
            {starting ? 'Starte …' : 'Run starten'}
          </button>
        </div>
      </div>
    </div>
  );
}

function PillSelector({ title, items, selected, onToggle }: {
  title: string;
  items: Array<{ id: string; label: string }>;
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div>
      <label style={{ fontSize: 13, fontWeight: 500 }}>
        {title} ({selected.size}/{items.length})
      </label>
      <div style={{ marginTop: 6, padding: 8, border: '1px solid #E5E7EB', borderRadius: 6, maxHeight: 180, overflowY: 'auto', display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {items.map(it => (
          <button key={it.id} onClick={() => onToggle(it.id)}
            title={it.label}
            style={{
              padding: '3px 8px', fontSize: 11,
              background: selected.has(it.id) ? 'var(--primary)' : '#F3F4F6',
              color: selected.has(it.id) ? '#fff' : '#374151',
              border: 0, borderRadius: 10, cursor: 'pointer',
            }}>
            {it.id}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Per-turn pipeline trace ───────────────────────────────────────
 *
 * Renders the trace entries the backend records for each chat turn
 * (safety-classify, pattern, response …). Helps UX-Fachkräfte
 * understand WHY a particular pattern was picked or where time was
 * spent. Collapsed by default — click the summary to expand.
 */
function TurnTrace({ trace }: { trace: TraceEntry[] }) {
  const [open, setOpen] = useState(false);
  if (!trace || trace.length === 0) return null;
  const total = trace.reduce((s, e) => s + (e.duration_ms || 0), 0);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      style={{ marginTop: 6 }}
    >
      <summary
        style={{
          fontSize: 11,
          color: 'var(--text-muted)',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        Pipeline-Trace ({trace.length} Schritte, {total} ms)
      </summary>
      <div style={{ marginTop: 4, fontSize: 11, fontFamily: 'monospace' }}>
        {trace.map((entry, i) => {
          const isEngine = entry.step.includes('classify') || entry.step === 'pattern';
          const isSlow = entry.duration_ms > 1000;
          return (
            <div
              key={i}
              style={{
                display: 'grid',
                gridTemplateColumns: '110px 1fr 60px',
                gap: 6,
                padding: '2px 4px',
                background: i % 2 ? '#F9FAFB' : 'transparent',
                color: '#1F2937',
                borderLeft: isEngine ? '2px solid #0EA5E9' : '2px solid transparent',
              }}
            >
              <span style={{ color: '#6B7280' }}>[{entry.step}]</span>
              <span>
                {entry.label}
                {entry.data && Object.keys(entry.data).length > 0 && (
                  <span style={{ color: '#6B7280', marginLeft: 4 }}>
                    {Object.entries(entry.data)
                      .filter(([k]) =>
                        ['intent', 'persona', 'state_final', 'winner',
                         'risk_level', 'fired_rules'].includes(k))
                      .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                      .join(' ')}
                  </span>
                )}
              </span>
              <span style={{ textAlign: 'right', color: isSlow ? '#DC2626' : '#374151' }}>
                {entry.duration_ms} ms
              </span>
            </div>
          );
        })}
      </div>
    </details>
  );
}
