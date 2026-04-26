'use client';

/**
 * RoutingRulesView — Studio page for the generic routing rule engine.
 *
 * Three sub-tabs:
 *   1. Rules — list with priority, when/then, live/shadow status, fire counts
 *   2. Test-Bench — dry-run engine against a hand-crafted context
 *   3. Stats — agreement rates and disagreement samples (last N days)
 *
 * Read-only. Editing rules goes through Git/YAML.
 */

import { useEffect, useMemo, useState } from 'react';

// Helper: read held-count from new or legacy field name (backend emits both)
function heldOf(s: { decision_held?: number; agree?: number }): number {
  return s.decision_held ?? s.agree ?? 0;
}
function overriddenOf(s: { decision_overridden?: number; disagree?: number }): number {
  return s.decision_overridden ?? s.disagree ?? 0;
}
function heldPctOf(s: { decision_held_pct?: number; agreement_pct?: number }): number {
  return s.decision_held_pct ?? s.agreement_pct ?? 0;
}

interface RuleDef {
  id: string;
  description: string;
  priority: number;
  live: boolean;
  when: Record<string, unknown>;
  then: Record<string, unknown>;
}

interface RuleStats {
  fired: number;
  live?: boolean;
  decision_held?: number;
  decision_overridden?: number;
  decision_held_pct?: number;
  override_meaning?: string;
  // legacy aliases (still emitted by backend for back-compat)
  agree: number;
  disagree: number;
  agreement_pct: number;
  sample_override?: {
    session?: string;
    message?: string;
    actual_pattern?: string;
    shadow_pattern?: string;
  };
  sample_disagreement?: {
    session?: string;
    message?: string;
    actual_pattern?: string;
    shadow_pattern?: string;
  };
}

type Tab = 'rules' | 'test' | 'stats';

export default function RoutingRulesView() {
  const [tab, setTab] = useState<Tab>('rules');
  const [rules, setRules] = useState<RuleDef[]>([]);
  const [stats, setStats] = useState<Record<string, RuleStats>>({});
  const [statsTotalTurns, setStatsTotalTurns] = useState(0);
  const [statsDays, setStatsDays] = useState(7);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadRules = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/api/routing-rules');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRules(data.rules || []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const r = await fetch(`/api/routing-rules/stats?days=${statsDays}`);
      if (!r.ok) return;
      const data = await r.json();
      setStats(data.rules || {});
      setStatsTotalTurns(data.total_turns || 0);
    } catch {}
  };

  useEffect(() => {
    loadRules();
  }, []);

  useEffect(() => {
    if (tab === 'stats' || tab === 'rules') loadStats();
  }, [tab, statsDays]);

  const liveCount = useMemo(() => rules.filter((r) => r.live).length, [rules]);

  const reload = async () => {
    setLoading(true);
    try {
      await fetch('/api/routing-rules/reload', { method: 'POST' });
      await loadRules();
      await loadStats();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="routing-rules-view" style={{ padding: '20px 28px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: '0 0 4px 0' }}>Routing Rules</h2>
          <p style={{ margin: 0, color: '#6B7280', fontSize: 14 }}>
            Generic rule engine for intent / pattern routing. {rules.length} rules total — {liveCount} live, {rules.length - liveCount} shadow.
          </p>
        </div>
        <button
          onClick={reload}
          disabled={loading}
          style={{
            padding: '8px 14px',
            background: '#3B82F6',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: loading ? 'wait' : 'pointer',
            fontSize: 13,
          }}
        >
          {loading ? 'Lädt …' : '⟳ YAML neu laden'}
        </button>
      </div>

      {/* Tab nav */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #E5E7EB', marginBottom: 16 }}>
        {([
          { id: 'rules', label: 'Regeln' },
          { id: 'test', label: 'Test-Bench' },
          { id: 'stats', label: 'Statistiken' },
        ] as { id: Tab; label: string }[]).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '8px 16px',
              background: 'transparent',
              border: 'none',
              borderBottom: tab === t.id ? '2px solid #3B82F6' : '2px solid transparent',
              color: tab === t.id ? '#1F2937' : '#6B7280',
              fontWeight: tab === t.id ? 600 : 400,
              cursor: 'pointer',
              fontSize: 14,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div style={{ color: '#DC2626', marginBottom: 12 }}>Fehler: {error}</div>}

      {tab === 'rules' && (
        <RulesList
          rules={rules}
          stats={stats}
          expandedId={expandedId}
          setExpandedId={setExpandedId}
          loading={loading}
        />
      )}
      {tab === 'test' && <TestBench />}
      {tab === 'stats' && (
        <StatsView
          stats={stats}
          totalTurns={statsTotalTurns}
          days={statsDays}
          setDays={setStatsDays}
          onReload={loadStats}
        />
      )}
    </div>
  );
}

function RulesList({
  rules,
  stats,
  expandedId,
  setExpandedId,
  loading,
}: {
  rules: RuleDef[];
  stats: Record<string, RuleStats>;
  expandedId: string | null;
  setExpandedId: (id: string | null) => void;
  loading: boolean;
}) {
  if (loading) return <div>Lade Regeln …</div>;
  if (!rules.length) return <div>Keine Regeln gefunden.</div>;

  return (
    <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: 8 }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '40px 80px 1fr 110px 90px 130px',
          gap: 8,
          padding: '10px 12px',
          background: '#F9FAFB',
          fontSize: 12,
          fontWeight: 600,
          color: '#6B7280',
          borderBottom: '1px solid #E5E7EB',
        }}
      >
        <div></div>
        <div>Priorität</div>
        <div>ID & Beschreibung</div>
        <div>Status</div>
        <div>Gefeuert</div>
        <div title="Wie oft die Entscheidung der Regel bis zum Ende durchgesetzt wurde (vs. von einer späteren Regel/Stufe überschrieben). Bei shadow-Regeln: immer 0%, weil ihre Entscheidung per Definition nicht angewendet wird.">Decision-Held&nbsp;%</div>
      </div>
      {rules.map((r) => {
        const s = stats[r.id];
        const expanded = expandedId === r.id;
        return (
          <div key={r.id}>
            <button
              onClick={() => setExpandedId(expanded ? null : r.id)}
              style={{
                display: 'grid',
                gridTemplateColumns: '40px 80px 1fr 110px 90px 130px',
                gap: 8,
                width: '100%',
                padding: '12px',
                background: 'transparent',
                border: 'none',
                borderBottom: '1px solid #F3F4F6',
                textAlign: 'left',
                cursor: 'pointer',
                fontSize: 13,
                alignItems: 'center',
              }}
            >
              <div>{expanded ? '▼' : '▶'}</div>
              <div style={{ fontWeight: 600 }}>{r.priority}</div>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600 }}>{r.id}</div>
                <div style={{ color: '#6B7280', fontSize: 12, marginTop: 2 }}>{r.description}</div>
              </div>
              <div>
                <span
                  style={{
                    padding: '2px 8px',
                    borderRadius: 12,
                    fontSize: 11,
                    fontWeight: 600,
                    background: r.live ? '#10B98120' : '#F3F4F6',
                    color: r.live ? '#065F46' : '#6B7280',
                  }}
                >
                  {r.live ? 'live' : 'shadow'}
                </span>
              </div>
              <div style={{ fontSize: 12, color: '#6B7280' }}>{s ? s.fired : '–'}</div>
              <div
                style={{ fontSize: 12, color: s ? (heldPctOf(s) > 80 ? '#065F46' : '#92400E') : '#6B7280' }}
                title={
                  !s ? '' :
                  r.live
                    ? `Entscheidung blieb bestehen in ${heldOf(s)} von ${s.fired} Fällen. Überschriebene Fälle deuten auf Regel-Konflikte hin.`
                    : `Shadow-only — Entscheidung wird nie angewendet, daher 0%. Disagreement ist by design.`
                }
              >
                {s ? `${heldPctOf(s)}%` : '–'}
              </div>
            </button>
            {expanded && (
              <div style={{ padding: '12px 24px', background: '#F9FAFB', borderBottom: '1px solid #E5E7EB' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#6B7280', marginBottom: 4 }}>WHEN</div>
                    <pre
                      style={{
                        margin: 0,
                        padding: 8,
                        background: '#fff',
                        border: '1px solid #E5E7EB',
                        borderRadius: 4,
                        fontSize: 11,
                        overflow: 'auto',
                      }}
                    >
                      {JSON.stringify(r.when, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#6B7280', marginBottom: 4 }}>THEN</div>
                    <pre
                      style={{
                        margin: 0,
                        padding: 8,
                        background: '#fff',
                        border: '1px solid #E5E7EB',
                        borderRadius: 4,
                        fontSize: 11,
                        overflow: 'auto',
                      }}
                    >
                      {JSON.stringify(r.then, null, 2)}
                    </pre>
                  </div>
                </div>
                {(() => {
                  const sample = s?.sample_override ?? s?.sample_disagreement;
                  if (!sample) return null;
                  const isLive = r.live;
                  return (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 8,
                        background: isLive ? '#FEE2E2' : '#FEF3C7',
                        borderRadius: 4,
                        fontSize: 12,
                      }}
                      title={
                        isLive
                          ? 'Diese Live-Regel wurde überschrieben — typischerweise durch eine andere Live-Regel oder die Pattern-Engine. Untersuchungswert.'
                          : 'Shadow-Regel: ihre Entscheidung wird per Definition nie angewendet. Das Beispiel zeigt was passieren würde, wenn die Regel live geschaltet wäre.'
                      }
                    >
                      <strong>{isLive ? 'Sample-Override' : 'Sample (Shadow-Decision)'}:</strong>{' '}
                      &quot;{sample.message}&quot;
                      <br />
                      <small>
                        actual pattern: {sample.actual_pattern} → rule wanted: {sample.shadow_pattern}
                      </small>
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TestBench() {
  const [intent, setIntent] = useState('INT-W-03b');
  const [state, setState] = useState('state-5');
  const [persona, setPersona] = useState('P-W-LK');
  const [thema, setThema] = useState('');
  const [fach, setFach] = useState('');
  const [materialTyp, setMaterialTyp] = useState('');
  const [message, setMessage] = useState('Materialien für Mathematikunterricht');
  const [confidence, setConfidence] = useState<number>(0.8);
  const [winner, setWinner] = useState('');
  const [runnerUp, setRunnerUp] = useState('');
  const [scoreGap, setScoreGap] = useState<number>(0.05);
  const [result, setResult] = useState<unknown>(null);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    try {
      const body = {
        intent,
        state,
        persona,
        message,
        intent_confidence: confidence,
        entities: {
          ...(thema && { thema }),
          ...(fach && { fach }),
          ...(materialTyp && { material_typ: materialTyp }),
        },
        ...(winner && { pattern_winner: winner }),
        ...(runnerUp && { pattern_runner_up: runnerUp }),
        ...(scoreGap && { pattern_score_gap: scoreGap }),
      };
      const r = await fetch('/api/routing-rules/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      setResult(data);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
      <div>
        <h3 style={{ marginTop: 0 }}>Eingabe</h3>
        <div style={{ display: 'grid', gap: 10 }}>
          <Field label="Message">
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={3}
              style={{ width: '100%', padding: 8, fontFamily: 'inherit', fontSize: 13 }}
            />
          </Field>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            <Field label="Intent">
              <input value={intent} onChange={(e) => setIntent(e.target.value)} style={inputStyle} />
            </Field>
            <Field label="State">
              <input value={state} onChange={(e) => setState(e.target.value)} style={inputStyle} />
            </Field>
            <Field label="Persona">
              <input value={persona} onChange={(e) => setPersona(e.target.value)} style={inputStyle} />
            </Field>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
            <Field label="thema">
              <input value={thema} onChange={(e) => setThema(e.target.value)} style={inputStyle} />
            </Field>
            <Field label="fach">
              <input value={fach} onChange={(e) => setFach(e.target.value)} style={inputStyle} />
            </Field>
            <Field label="material_typ">
              <input value={materialTyp} onChange={(e) => setMaterialTyp(e.target.value)} style={inputStyle} />
            </Field>
          </div>
          <Field label={`intent_confidence: ${confidence}`}>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={confidence}
              onChange={(e) => setConfidence(parseFloat(e.target.value))}
              style={{ width: '100%' }}
            />
          </Field>
          <div style={{ borderTop: '1px solid #E5E7EB', paddingTop: 10 }}>
            <h4 style={{ margin: '0 0 8px 0', fontSize: 13 }}>Pattern-Selection (für Tiebreaker-Tests)</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
              <Field label="winner">
                <input value={winner} onChange={(e) => setWinner(e.target.value)} placeholder="PAT-01" style={inputStyle} />
              </Field>
              <Field label="runner_up">
                <input value={runnerUp} onChange={(e) => setRunnerUp(e.target.value)} placeholder="PAT-02" style={inputStyle} />
              </Field>
              <Field label="score_gap">
                <input
                  type="number"
                  step={0.005}
                  value={scoreGap}
                  onChange={(e) => setScoreGap(parseFloat(e.target.value))}
                  style={inputStyle}
                />
              </Field>
            </div>
          </div>
          <button
            onClick={run}
            disabled={running}
            style={{
              padding: '10px 16px',
              background: '#3B82F6',
              color: '#fff',
              border: 'none',
              borderRadius: 6,
              cursor: running ? 'wait' : 'pointer',
              fontWeight: 600,
            }}
          >
            {running ? 'Läuft …' : 'Engine ausführen'}
          </button>
        </div>
      </div>
      <div>
        <h3 style={{ marginTop: 0 }}>Ergebnis</h3>
        {!result ? (
          <div style={{ color: '#6B7280', fontSize: 13 }}>Noch kein Test ausgeführt.</div>
        ) : (
          <TestResult result={result as { decision: { fired_rules: { rule_id: string; live: boolean; effects_applied: Record<string, unknown> }[] }; live_decision: { is_noop: boolean; enforced_pattern_id: string | null; intent_override: string | null; state_override: string | null; fired_rules: string[] } }} />
        )}
      </div>
    </div>
  );
}

function TestResult({ result }: {
  result: {
    decision: { fired_rules: { rule_id: string; live: boolean; effects_applied: Record<string, unknown> }[] };
    live_decision: { is_noop: boolean; enforced_pattern_id: string | null; intent_override: string | null; state_override: string | null; fired_rules: string[] };
  };
}) {
  const fired = result.decision.fired_rules || [];
  const live = result.live_decision;
  return (
    <div>
      {fired.length === 0 ? (
        <div style={{ padding: 12, background: '#F3F4F6', borderRadius: 6, fontSize: 13 }}>
          <strong>Keine Regel feuert.</strong> Pattern-Engine entscheidet ohne Override.
        </div>
      ) : (
        <>
          <div style={{ marginBottom: 12, fontSize: 13 }}>
            <strong>{fired.length}</strong> Regel(n) gefeuert, davon <strong>{live.fired_rules.length}</strong> live.
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {fired.map((f, i) => (
              <div
                key={i}
                style={{
                  padding: 10,
                  background: f.live ? '#ECFDF5' : '#F3F4F6',
                  borderLeft: `3px solid ${f.live ? '#10B981' : '#9CA3AF'}`,
                  borderRadius: 4,
                  fontSize: 12,
                }}
              >
                <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>
                  {f.rule_id} {f.live ? '🟢 live' : '⚪ shadow'}
                </div>
                <div style={{ marginTop: 4, color: '#374151' }}>
                  Effekte: {JSON.stringify(f.effects_applied)}
                </div>
              </div>
            ))}
          </div>
          {!live.is_noop && (
            <div style={{ marginTop: 12, padding: 12, background: '#DBEAFE', borderRadius: 6, fontSize: 13 }}>
              <strong>Live-Override:</strong>
              <ul style={{ margin: '6px 0 0 0', paddingLeft: 20 }}>
                {live.enforced_pattern_id && <li>enforced_pattern: {live.enforced_pattern_id}</li>}
                {live.intent_override && <li>intent_override: {live.intent_override}</li>}
                {live.state_override && <li>state_override: {live.state_override}</li>}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatsView({
  stats,
  totalTurns,
  days,
  setDays,
  onReload,
}: {
  stats: Record<string, RuleStats>;
  totalTurns: number;
  days: number;
  setDays: (d: number) => void;
  onReload: () => void;
}) {
  const sorted = Object.entries(stats).sort((a, b) => b[1].fired - a[1].fired);
  const [clearing, setClearing] = useState(false);

  const clearAllStats = async () => {
    if (!confirm('Alle Shadow-Log-Dateien löschen? Die Statistiken werden auf 0 zurückgesetzt.')) return;
    setClearing(true);
    try {
      const r = await fetch('/api/routing-rules/stats', { method: 'DELETE' });
      if (r.ok) {
        const data = await r.json();
        alert(`${data.deleted} Log-Datei(en) gelöscht.`);
        onReload();
      } else {
        alert('Löschen fehlgeschlagen: HTTP ' + r.status);
      }
    } catch (e) {
      alert('Löschen fehlgeschlagen: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setClearing(false);
    }
  };

  const clearOldStats = async () => {
    const thresholdDays = parseInt(prompt('Logs älter als wie viele Tage löschen?', '7') || '0');
    if (!thresholdDays || thresholdDays < 1) return;
    setClearing(true);
    try {
      const r = await fetch(`/api/routing-rules/stats?days=${thresholdDays}`, { method: 'DELETE' });
      if (r.ok) {
        const data = await r.json();
        alert(`${data.deleted} Log-Datei(en) (älter als ${thresholdDays} Tage) gelöscht. ${data.kept} behalten.`);
        onReload();
      }
    } catch (e) {
      alert('Löschen fehlgeschlagen: ' + (e instanceof Error ? e.message : String(e)));
    } finally {
      setClearing(false);
    }
  };

  return (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center' }}>
        <span style={{ fontSize: 13, color: '#6B7280' }}>Zeitraum:</span>
        {[1, 3, 7, 30].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            style={{
              padding: '4px 10px',
              background: days === d ? '#3B82F6' : '#fff',
              color: days === d ? '#fff' : '#374151',
              border: '1px solid #D1D5DB',
              borderRadius: 4,
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            {d}d
          </button>
        ))}
        <span style={{ fontSize: 13, color: '#6B7280', marginLeft: 'auto' }}>
          {totalTurns} Turns analysiert
        </span>
        <button
          onClick={clearOldStats}
          disabled={clearing || totalTurns === 0}
          style={{
            padding: '4px 10px',
            background: '#fff',
            color: '#92400E',
            border: '1px solid #F59E0B',
            borderRadius: 4,
            fontSize: 12,
            cursor: clearing ? 'wait' : 'pointer',
          }}
          title="Logs älter als N Tage löschen"
        >
          🗑 alte
        </button>
        <button
          onClick={clearAllStats}
          disabled={clearing || totalTurns === 0}
          style={{
            padding: '4px 10px',
            background: '#fff',
            color: '#DC2626',
            border: '1px solid #DC2626',
            borderRadius: 4,
            fontSize: 12,
            cursor: clearing ? 'wait' : 'pointer',
            fontWeight: 600,
          }}
          title="Alle Shadow-Log-Dateien löschen"
        >
          🗑 alle
        </button>
      </div>
      <div style={{ marginBottom: 8, padding: 8, background: '#F0F9FF', borderRadius: 4, fontSize: 12, color: '#0C4A6E' }}>
        <strong>Lese-Hilfe:</strong> &quot;<em>Held</em>&quot; = die Entscheidung der Regel wurde
        bis zum Ende durchgesetzt. &quot;<em>Overridden</em>&quot; = überschrieben (bei Live-Regeln
        meist durch eine andere Live-Regel; bei Shadow-Regeln by design, weil sie nie angewendet
        werden).
      </div>
      {sorted.length === 0 ? (
        <div style={{ color: '#6B7280' }}>Keine Daten — noch keine Regeln gefeuert.</div>
      ) : (
        <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: 6 }}>
          <div
            style={{
              padding: '8px 12px',
              borderBottom: '1px solid #E5E7EB',
              background: '#F9FAFB',
              display: 'grid',
              gridTemplateColumns: '1fr 70px 100px 110px 120px',
              gap: 12,
              fontSize: 11,
              fontWeight: 600,
              color: '#6B7280',
            }}
          >
            <div>Rule-ID</div>
            <div>Status</div>
            <div>Gefeuert</div>
            <div>Held</div>
            <div>Overridden</div>
          </div>
          {sorted.map(([rid, s]) => {
            const held = heldOf(s);
            const overridden = overriddenOf(s);
            const isLive = (s as RuleStats).live;
            const overrideMeaning = (s as RuleStats).override_meaning;
            return (
              <div
                key={rid}
                style={{
                  padding: 12,
                  borderBottom: '1px solid #F3F4F6',
                  display: 'grid',
                  gridTemplateColumns: '1fr 70px 100px 110px 120px',
                  gap: 12,
                  alignItems: 'center',
                  fontSize: 13,
                }}
              >
                <div style={{ fontFamily: 'monospace', fontWeight: 600 }}>{rid}</div>
                <div>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: 12,
                      fontSize: 11,
                      fontWeight: 600,
                      background: isLive ? '#10B98120' : '#F3F4F6',
                      color: isLive ? '#065F46' : '#6B7280',
                    }}
                  >
                    {isLive ? 'live' : 'shadow'}
                  </span>
                </div>
                <div>{s.fired}×</div>
                <div style={{ color: '#10B981' }}>{held}× ({heldPctOf(s)}%)</div>
                <div
                  style={{ color: '#F59E0B' }}
                  title={overrideMeaning || ''}
                >
                  {overridden}×
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, color: '#6B7280', marginBottom: 2, fontWeight: 600 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '6px 8px',
  border: '1px solid #D1D5DB',
  borderRadius: 4,
  fontFamily: 'inherit',
  fontSize: 13,
};
