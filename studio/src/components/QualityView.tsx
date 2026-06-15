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
  scope?: string;
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

type QualityScope = 'all' | 'production' | 'eval';

interface TightRacePair {
  winner: string;
  runner_up: string;
  count: number;
  avg_gap: number;
  example_message?: string;
  example_intent?: string;
  example_persona?: string;
  example_state?: string;
}

interface TightRaces {
  pairs: TightRacePair[];
  total_tight: number;
  threshold: number;
  scope: string;
}

interface DegradationGroup {
  pattern_id: string;
  missing_slots: string[];
  count: number;
  example_message?: string;
  example_intent?: string;
  example_persona?: string;
  example_state?: string;
}
interface Degradations { groups: DegradationGroup[]; total: number; scope: string; }

interface EmptyEntitiesGroup {
  intent_id: string;
  pattern_id: string;
  count: number;
  example_message?: string;
  example_persona?: string;
  example_state?: string;
}
interface EmptyEntities { groups: EmptyEntitiesGroup[]; total: number; scope: string; }

interface LowConfidenceTurn {
  id: number;
  message: string;
  intent_id: string;
  pattern_id: string;
  persona_id: string;
  final_confidence: number;
  phase2_winner_score: number;
  phase2_score_gap: number;
  state_id: string;
  created_at: string;
}
interface LowConfidence {
  turns: LowConfidenceTurn[];
  total: number;
  scope: string;
  max_confidence: number;
}

interface RoutingMatrixCell {
  persona_id: string;
  intent_id: string;
  top_pattern: string;
  top_pattern_count: number;
  total_count: number;
  share: number;
  alternatives: { pattern_id: string; count: number }[];
}
interface RoutingMatrix {
  scope: string;
  total_turns: number;
  cells: RoutingMatrixCell[];
}

interface StateTransition {
  prev: string;
  next: string;
  count: number;
}
interface StateTransitionsPayload {
  scope: string;
  days: number;
  total_turns: number;
  total_transitions: number;
  state_distribution: Record<string, number>;
  transitions: StateTransition[];
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

/* ── Conversation-Flow sub-component (Welle C Sprint 6) ────────────────
 * Visualisiert die State-Übergänge der letzten N Tage als sortierte
 * Tabelle "prev → next: count" plus eine State-Häufigkeits-Verteilung.
 * Bewusst keine Sankey-Library als Dependency — eine HTML-Tabelle mit
 * proportionalen Balken erfüllt den gleichen Zweck ohne Build-Bloat.
 *
 * Lese-Werte:
 * - State-Distribution: wie oft welcher State im Zeitraum aktiv war
 * - Top-Übergänge: häufigste (prev → next) Paare, sortiert nach count
 * - Self-Loops (prev == next) sind farblich abgegrenzt — typisch in
 *   S2 (mehrere Slot-Runden) und S3 (mehrere Canvas-Edits)
 */
function ConversationFlowView({
  flow, loading, days, setDays, minCount, setMinCount, onReload,
}: {
  flow: StateTransitionsPayload | null;
  loading: boolean;
  days: number;
  setDays: (n: number) => void;
  minCount: number;
  setMinCount: (n: number) => void;
  onReload: () => void;
}) {
  const dist = flow?.state_distribution ?? {};
  const transitions = flow?.transitions ?? [];
  const distMax = Math.max(...Object.values(dist), 1);
  const transMax = Math.max(...transitions.map(t => t.count), 1);

  // Self-loops zuerst absondern (state-X → state-X)
  const selfLoops = transitions.filter(t => t.prev === t.next);
  const properTrans = transitions.filter(t => t.prev !== t.next);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {flow
            ? <>
                <strong>{flow.total_turns}</strong> Turns mit State, <strong>{flow.total_transitions}</strong> Übergänge ({flow.scope}, letzte {flow.days} Tage).
              </>
            : 'Lade Conversation-Flow …'}
        </div>
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          Zeitraum (Tage):
          <input
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={e => setDays(Math.max(1, parseInt(e.target.value) || 30))}
            style={{ width: 56, padding: '2px 6px', border: '1px solid #D1D5DB', borderRadius: 4 }}
          />
        </label>
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          Min-Count:
          <input
            type="number"
            min={1}
            max={1000}
            value={minCount}
            onChange={e => setMinCount(Math.max(1, parseInt(e.target.value) || 1))}
            style={{ width: 56, padding: '2px 6px', border: '1px solid #D1D5DB', borderRadius: 4 }}
          />
        </label>
        <button className="btn btn-sm" onClick={onReload} disabled={loading}>
          {loading ? '…' : '↻ Neu laden'}
        </button>
      </div>

      {loading && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Lade Conversation-Flow …
        </div>
      )}

      {!loading && flow && flow.total_turns === 0 && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Keine State-Daten im Zeitraum. Starte einen Chat, um Übergänge zu sammeln.
        </div>
      )}

      {!loading && flow && flow.total_turns > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Linke Spalte: State-Häufigkeits-Verteilung */}
          <div className="card" style={{ padding: 14 }}>
            <h4 style={{ marginTop: 0, marginBottom: 8, fontSize: 14 }}>📊 State-Häufigkeit</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {Object.entries(dist)
                .sort((a, b) => b[1] - a[1])
                .map(([state, count]) => (
                  <div key={state} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                    <span style={{ width: 200, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace', fontSize: 11, color: '#1F2937', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {state}
                    </span>
                    <div style={{ flex: 1, background: '#f3f4f6', borderRadius: 4, height: 16, position: 'relative' }}>
                      <div style={{
                        width: `${(count / distMax) * 100}%`,
                        background: '#3B82F6',
                        borderRadius: 4,
                        height: '100%',
                        minWidth: 2,
                      }} />
                    </div>
                    <span style={{ width: 36, textAlign: 'right', fontWeight: 600, fontSize: 11 }}>{count}</span>
                  </div>
                ))}
            </div>
          </div>

          {/* Rechte Spalte: Top-Übergänge */}
          <div className="card" style={{ padding: 14 }}>
            <h4 style={{ marginTop: 0, marginBottom: 8, fontSize: 14 }}>🔀 Top-Übergänge (prev → next)</h4>
            {properTrans.length === 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', fontStyle: 'italic' }}>
                Keine Mehrturn-Übergänge im Zeitraum.
              </div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {properTrans.slice(0, 20).map((t, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                  <span style={{
                    flex: 1, fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                    fontSize: 11, color: '#1F2937', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {t.prev} <span style={{ color: '#6B7280' }}>→</span> {t.next}
                  </span>
                  <div style={{ width: 80, background: '#f3f4f6', borderRadius: 4, height: 14, position: 'relative' }}>
                    <div style={{
                      width: `${(t.count / transMax) * 100}%`,
                      background: '#059669',
                      borderRadius: 4,
                      height: '100%',
                      minWidth: 2,
                    }} />
                  </div>
                  <span style={{ width: 28, textAlign: 'right', fontWeight: 600, fontSize: 11 }}>{t.count}</span>
                </div>
              ))}
            </div>

            {selfLoops.length > 0 && (
              <>
                <h4 style={{ marginTop: 14, marginBottom: 6, fontSize: 13, color: '#6B7280' }}>
                  🔁 Self-Loops (innerhalb derselben Phase)
                </h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {selfLoops.map((t, i) => (
                    <div key={i} style={{ fontSize: 11, color: '#6B7280', display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace' }}>
                        {t.prev} ↻
                      </span>
                      <span style={{ fontWeight: 600 }}>{t.count}×</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Volle Breite: Erläuterungs-Box */}
          <div style={{
            gridColumn: '1 / -1',
            fontSize: 11,
            color: '#6B7280',
            background: '#FAFAFA',
            border: '1px solid #E5E7EB',
            borderRadius: 6,
            padding: 10,
            lineHeight: 1.5,
          }}>
            <strong>Lesart:</strong> States sind Verlaufs-Phasen — der Bot wechselt von einer Phase
            (z.B. <code style={{ background: '#fff', padding: '0 4px', borderRadius: 3 }}>S3 Suche</code>)
            in eine plausible Folge-Phase (z.B. <code style={{ background: '#fff', padding: '0 4px', borderRadius: 3 }}>S3 Ergebnis-Kuratierung</code>).
            Häufige Übergänge zeigen den typischen Gesprächs-Flow.
            Self-Loops (z.B. <code style={{ background: '#fff', padding: '0 4px', borderRadius: 3 }}>S2 ↻</code>)
            bedeuten mehrere Iterationen in derselben Phase — meist Slot-Erfassung („Welche Stufe?" → User antwortet → noch ein Slot fehlt).
            Implausible Übergänge (siehe Debug-Panel im Chat-Widget) werden separat als Warnung markiert.
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Routing-Matrix sub-component ──────────────────────────────────────
 * Renders a Persona × Intent heatmap of the top-winning Pattern per cell.
 * Color intensity = share (how dominant the top pattern is). Click a cell
 * to drill into the matching quality logs.
 *
 * The matrix is intentionally sparse: only cells with ≥ minCount samples
 * appear. Empty cells (no traffic) are shown as gray placeholders so
 * coverage gaps stay visible.
 */
function RoutingMatrixView({
  matrix, loading, minCount, setMinCount, onReload, onCellClick,
}: {
  matrix: RoutingMatrix | null;
  loading: boolean;
  minCount: number;
  setMinCount: (n: number) => void;
  onReload: () => void;
  onCellClick: (personaId: string, intentId: string) => void;
}) {
  const cells = matrix?.cells ?? [];

  // Derive row/col axes from the observed data + a stable sort. Persona
  // and Intent IDs are already short codes — alphabetical sort is fine.
  const personas = Array.from(new Set(cells.map(c => c.persona_id))).sort();
  const intents = Array.from(new Set(cells.map(c => c.intent_id))).sort();

  // Index cells by (persona, intent) for O(1) lookup in the render loop.
  const cellIndex = new Map<string, RoutingMatrixCell>();
  for (const c of cells) cellIndex.set(`${c.persona_id}|${c.intent_id}`, c);

  // Stable pastel palette keyed by pattern_id — same color = same pattern
  // across cells, so the eye can spot "M15 catches everything" trivially.
  const colorForPattern = (pid: string): string => {
    // Simple hash → hue
    let h = 0;
    for (let i = 0; i < pid.length; i++) h = (h * 31 + pid.charCodeAt(i)) >>> 0;
    return `hsl(${h % 360}, 55%, 78%)`;
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {matrix
            ? <>Aggregiert aus <strong>{matrix.total_turns}</strong> Turns ({matrix.scope}).</>
            : 'Lade Matrix-Daten …'}
        </div>
        <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          Min-Samples pro Zelle:
          <input
            type="number"
            min={1}
            max={1000}
            value={minCount}
            onChange={e => setMinCount(Math.max(1, parseInt(e.target.value) || 1))}
            style={{ width: 60, padding: '2px 6px', border: '1px solid #D1D5DB', borderRadius: 4 }}
          />
        </label>
        <button className="btn btn-sm" onClick={onReload} disabled={loading}>
          {loading ? '…' : '↻ Neu laden'}
        </button>
      </div>

      {loading && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Berechne Routing-Matrix …
        </div>
      )}

      {!loading && matrix && cells.length === 0 && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Keine Treffer für die aktuellen Filter (Scope: {matrix.scope}, Min-Samples: {minCount}).
          Starte einen Chat oder reduziere die Min-Samples-Schwelle.
        </div>
      )}

      {!loading && cells.length > 0 && (
        <div style={{ overflowX: 'auto', background: '#fff', borderRadius: 8, border: '1px solid #E5E7EB', padding: 8 }}>
          <table style={{ borderCollapse: 'separate', borderSpacing: 0, fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{
                  position: 'sticky', left: 0, background: '#F9FAFB', zIndex: 2,
                  padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #E5E7EB',
                  color: 'var(--text-muted)', fontWeight: 600, minWidth: 90,
                }}>
                  Persona ↓ / Intent →
                </th>
                {intents.map(iid => (
                  <th key={iid} style={{
                    padding: '8px 6px',
                    borderBottom: '1px solid #E5E7EB',
                    fontWeight: 600,
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                    color: '#1F2937',
                    whiteSpace: 'nowrap',
                    fontSize: 11,
                  }}>
                    {iid}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {personas.map(pid => (
                <tr key={pid}>
                  <th style={{
                    position: 'sticky', left: 0, background: '#F9FAFB', zIndex: 1,
                    padding: '6px 12px', textAlign: 'left',
                    borderBottom: '1px solid #F3F4F6', borderRight: '1px solid #E5E7EB',
                    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#1F2937',
                    whiteSpace: 'nowrap',
                  }}>
                    {pid}
                  </th>
                  {intents.map(iid => {
                    const cell = cellIndex.get(`${pid}|${iid}`);
                    if (!cell) {
                      return (
                        <td key={iid} style={{
                          padding: '6px 6px',
                          borderBottom: '1px solid #F3F4F6',
                          background: '#FAFAFA',
                          color: '#D1D5DB',
                          textAlign: 'center',
                          fontSize: 10,
                          minWidth: 90,
                        }}>—</td>
                      );
                    }
                    const bg = colorForPattern(cell.top_pattern);
                    const sharePct = Math.round(cell.share * 100);
                    const altText = cell.alternatives.length > 0
                      ? '\nAlternativen: ' + cell.alternatives.map(a => `${a.pattern_id} (${a.count})`).join(', ')
                      : '';
                    const title = `${cell.persona_id} × ${cell.intent_id}\n→ ${cell.top_pattern} (${cell.top_pattern_count}/${cell.total_count}, ${sharePct}%)${altText}\nKlicken: Logs anzeigen.`;
                    return (
                      <td
                        key={iid}
                        title={title}
                        onClick={() => onCellClick(cell.persona_id, cell.intent_id)}
                        style={{
                          padding: '6px 8px',
                          borderBottom: '1px solid #F3F4F6',
                          background: bg,
                          cursor: 'pointer',
                          textAlign: 'center',
                          minWidth: 90,
                          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                          fontSize: 11,
                          // Subtle opacity gradient by share — high share = vivid,
                          // low share = washed out (signals "ambiguous routing here")
                          opacity: 0.55 + 0.45 * Math.min(cell.share, 1),
                        }}
                      >
                        <div style={{ fontWeight: 700, color: '#111827' }}>{cell.top_pattern}</div>
                        <div style={{ color: '#374151', fontSize: 10 }}>
                          {sharePct}% · {cell.total_count}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            <strong>Legende:</strong> Pro Zelle steht oben das dominanteste Pattern,
            unten dessen Anteil und die Gesamt-Sample-Zahl.
            Volle Farbsättigung = klare Pattern-Wahl (≥ 90 %), gedeckt = mehrere Patterns konkurrieren.
            Hover für Alternativen, Klick öffnet die zugehörigen Logs (Intent-Filter).
            „—" = keine Samples in dieser Persona-Intent-Kombination.
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────── */
export default function QualityView() {
  const [logs, setLogs] = useState<QualityLog[]>([]);
  const [stats, setStats] = useState<QualityStats | null>(null);
  // Welle E v4: tightRaces-State entfernt. Score-Phase läuft nicht mehr,
  // der Endpoint liefert by-design leere Pairs. Disagreement-Analyse
  // läuft jetzt in der Eval-View.
  const [degradations, setDegradations] = useState<Degradations | null>(null);
  const [emptyEntities, setEmptyEntities] = useState<EmptyEntities | null>(null);
  const [lowConfidence, setLowConfidence] = useState<LowConfidence | null>(null);
  const [openDetail, setOpenDetail] = useState<'tight' | 'degradation' | 'entities' | 'confidence' | null>('tight');
  const [selected, setSelected] = useState<QualityLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<'overview' | 'logs' | 'matrix' | 'flow'>('overview');
  // Routing-Matrix state (Block 2 — Sprint 6).
  // We fetch the precomputed (persona × intent → pattern) grid from
  // /api/quality/matrix lazily — only when the tab is opened, so the
  // overview tab keeps loading fast.
  const [matrix, setMatrix] = useState<RoutingMatrix | null>(null);
  const [matrixLoading, setMatrixLoading] = useState(false);
  const [matrixMinCount, setMatrixMinCount] = useState(1);
  // Conversation-Flow state (Welle C Sprint 6).
  // /api/quality/state-transitions liefert (prev → next)-Übergänge und
  // State-Häufigkeiten für die Flow-View (Sankey-Style-Diagram).
  const [flow, setFlow] = useState<StateTransitionsPayload | null>(null);
  const [flowLoading, setFlowLoading] = useState(false);
  const [flowDays, setFlowDays] = useState(30);
  const [flowMinCount, setFlowMinCount] = useState(1);
  const [busy, setBusy] = useState<number | 'bulk' | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [scope, setScope] = useState<QualityScope>('all');

  /* Filters */
  const [filterPattern, setFilterPattern] = useState('');
  const [filterIntent, setFilterIntent] = useState('');
  const [filterSession, setFilterSession] = useState('');

  const showFlash = (msg: string) => {
    setFlash(msg);
    setTimeout(() => setFlash(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200', scope });
      if (filterPattern) params.set('pattern_id', filterPattern);
      if (filterIntent) params.set('intent_id', filterIntent);
      if (filterSession) params.set('session_id', filterSession);
      const [logsRes, statsRes, degRes, entRes, confRes] = await Promise.all([
        fetch(`/api/quality/logs?${params}`),
        fetch(`/api/quality/stats?scope=${scope}`),
        fetch(`/api/quality/degradations?scope=${scope}&limit=30`),
        fetch(`/api/quality/empty-entities?scope=${scope}&limit=30`),
        fetch(`/api/quality/low-confidence?scope=${scope}&limit=30`),
      ]);
      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(data.logs || []);
      }
      if (statsRes.ok) setStats(await statsRes.json());
      setDegradations(degRes.ok ? await degRes.json() : null);
      setEmptyEntities(entRes.ok ? await entRes.json() : null);
      setLowConfidence(confRes.ok ? await confRes.json() : null);
    } catch (e) {
      console.error('Quality load error', e);
    } finally {
      setLoading(false);
    }
  }, [filterPattern, filterIntent, filterSession, scope]);

  useEffect(() => { load(); }, [load]);

  // Lazy-load the routing matrix the first time the tab is opened or
  // when scope / min_count changes while the tab is active.
  const loadMatrix = useCallback(async () => {
    setMatrixLoading(true);
    try {
      const resp = await fetch(
        `/api/quality/matrix?scope=${scope}&min_count=${matrixMinCount}`,
      );
      if (resp.ok) setMatrix(await resp.json());
      else setMatrix(null);
    } catch (e) {
      console.error('Routing-matrix load error', e);
      setMatrix(null);
    } finally {
      setMatrixLoading(false);
    }
  }, [scope, matrixMinCount]);

  useEffect(() => {
    if (tab === 'matrix') loadMatrix();
  }, [tab, loadMatrix]);

  // Lazy-load the conversation-flow data (Welle C Sprint 6).
  const loadFlow = useCallback(async () => {
    setFlowLoading(true);
    try {
      const resp = await fetch(
        `/api/quality/state-transitions?scope=${scope}&days=${flowDays}&min_count=${flowMinCount}`,
      );
      if (resp.ok) setFlow(await resp.json());
      else setFlow(null);
    } catch (e) {
      console.error('State-transitions load error', e);
      setFlow(null);
    } finally {
      setFlowLoading(false);
    }
  }, [scope, flowDays, flowMinCount]);

  useEffect(() => {
    if (tab === 'flow') loadFlow();
  }, [tab, loadFlow]);

  const deleteOne = async (logId: number) => {
    if (!confirm(`Quality-Log #${logId} löschen?`)) return;
    setBusy(logId);
    try {
      const resp = await fetch(`/api/quality/logs/${logId}`, { method: 'DELETE' });
      if (!resp.ok) {
        showFlash(`❌ Löschen fehlgeschlagen: HTTP ${resp.status}`);
        return;
      }
      showFlash(`✅ Log #${logId} gelöscht`);
      if (selected?.id === logId) setSelected(null);
      await load();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  const clearFiltered = async () => {
    const hasFilter = !!(filterPattern || filterIntent || filterSession);
    const count = logs.length;
    const desc = hasFilter
      ? `${count} gefilterte Quality-Logs löschen?\n\nFilter:` +
        (filterPattern ? `\n  • Pattern: ${filterPattern}*` : '') +
        (filterIntent ? `\n  • Intent: ${filterIntent}*` : '') +
        (filterSession ? `\n  • Session: ${filterSession}` : '')
      : `ALLE Quality-Logs löschen?\n\nDas betrifft ${stats?.total_turns ?? '?'} Einträge — sicher?`;
    if (!confirm(desc)) return;

    setBusy('bulk');
    try {
      const params = new URLSearchParams();
      if (filterPattern) params.set('pattern_id', filterPattern);
      if (filterIntent) params.set('intent_id', filterIntent);
      if (filterSession) params.set('session_id', filterSession);
      if (!hasFilter) params.set('confirm', 'true');
      const resp = await fetch(`/api/quality/logs/clear?${params}`, { method: 'POST' });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
        showFlash(`❌ Löschen fehlgeschlagen: ${err.detail || resp.status}`);
        return;
      }
      const data = await resp.json();
      showFlash(`✅ ${data.deleted} Logs gelöscht`);
      setSelected(null);
      await load();
    } catch (e) {
      showFlash(`❌ Fehler: ${e}`);
    } finally {
      setBusy(null);
    }
  };

  /* ── Derived metrics ─────────────────────────────────────────────── */
  // Aufräumung 2026-06-10: tightRaceLogs entfernt — basierte auf der
  // längst entfernten Score-Phase (phase2_score_gap) und hatte keine
  // Verwendung mehr in der View.
  const degradedLogs = logs.filter(l => l.degradation);

  return (
    <div>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, gap: 8, flexWrap: 'wrap' }}>
        <h2 className="card-title">📊 Quality-Analytics</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Scope-Toggle */}
          <div style={{ display: 'inline-flex', border: '1px solid #D1D5DB', borderRadius: 6, overflow: 'hidden', fontSize: 12 }}>
            {(['all', 'production', 'eval'] as QualityScope[]).map(s => (
              <button key={s}
                onClick={() => setScope(s)}
                title={
                  s === 'all' ? 'Alle Turns' :
                  s === 'production' ? 'Nur reale Chat-Sessions' :
                  'Nur simulierte Eval-Turns'
                }
                style={{
                  padding: '6px 10px', border: 0,
                  background: scope === s ? 'var(--primary)' : '#fff',
                  color: scope === s ? '#fff' : '#374151',
                  cursor: 'pointer', borderRight: s !== 'eval' ? '1px solid #D1D5DB' : 0,
                }}>
                {s === 'all' ? 'Alle' : s === 'production' ? 'Produktion' : 'Nur Eval'}
              </button>
            ))}
          </div>
          <button className={`btn btn-sm ${tab === 'overview' ? 'btn-primary' : ''}`} onClick={() => setTab('overview')}>Übersicht</button>
          <button className={`btn btn-sm ${tab === 'matrix' ? 'btn-primary' : ''}`} onClick={() => setTab('matrix')}>Routing-Matrix</button>
          <button className={`btn btn-sm ${tab === 'flow' ? 'btn-primary' : ''}`} onClick={() => setTab('flow')}>Gesprächs-Flow</button>
          <button className={`btn btn-sm ${tab === 'logs' ? 'btn-primary' : ''}`} onClick={() => setTab('logs')}>Logs</button>
          <button className="btn btn-sm" onClick={load} disabled={loading}>
            {loading ? '…' : '↻ Neu laden'}
          </button>
        </div>
      </div>

      {flash && (
        <div className="card" style={{
          marginBottom: 12,
          background: flash.startsWith('❌') ? '#FEE2E2' : '#DCFCE7',
          borderColor: flash.startsWith('❌') ? '#FCA5A5' : '#86EFAC',
          fontSize: 13,
        }}>
          {flash}
        </div>
      )}

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
            <div className="card" title="Welle E v4 (2026-05-25): Pattern-Selection ist Hint-Primary, Phase 1 (Gate) + Phase 2 (Score) wurden aus der Engine entfernt. Tight Races im Score-Sinn gibt es nicht mehr — die echte Pattern-Ambiguität entsteht jetzt bei Engine-Hint-Konflikten oder Klassifikator-Unsicherheit.">
              <div style={{ fontSize: 28, fontWeight: 700, color: '#9CA3AF' }}>
                —
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Tight Races
                <div style={{ fontSize: 10, marginTop: 2, color: '#9CA3AF' }}>
                  (Score-Phase entfernt — siehe Eval-View
                  „LLM-Hint vs Final-Pattern")
                </div>
              </div>
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

          {/* Alerts (Welle E v4: tight_races sind by-design 0, kein Alarm mehr) */}
          {(stats.degradation_rate > 0.05 || stats.empty_entity_rate > 0.3) && (
            <div className="card" style={{ borderLeft: '3px solid var(--warning)', marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8 }}>⚠️ Hinweise</div>
              <div style={{ fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {stats.degradation_rate > 0.05 && (
                  <div>• Degradation-Rate bei {pct(stats.degradation_rate)} — Patterns oder Slots prüfen</div>
                )}
                {stats.empty_entity_rate > 0.3 && (
                  <div>• {pct(stats.empty_entity_rate)} Turns ohne Entities — Entity-Erkennung prüfen</div>
                )}
              </div>
            </div>
          )}

          {/* Diagnose-Sektion — 4 aufklappbare Blöcke mit Details zu den Problem-Metriken */}
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Problem-Diagnose</h3>

            {/* 1. Tight Races — Welle E v4: by-design stillgelegt */}
            <div className="card" style={{ borderLeft: '3px solid #6B7280', marginBottom: 12, fontSize: 13, color: 'var(--text-muted)' }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>⚖️ Tight Races — stillgelegt</div>
              <strong>Welle E v4 (2026-05-25):</strong> Pattern-Wahl ist Hint-Primary,
              Phase 1 (Gate) und Phase 2 (Score) wurden aus der Engine entfernt
              (<code>pattern_engine.py:select_pattern</code>). Damit gibt es keine
              Score-Race mit Runner-Up mehr — die Metrik ist by-design 0.
              <br /><br />
              Echte Pattern-Ambiguität ist jetzt in der <strong>Evaluierungs-View</strong>{' '}
              sichtbar als „LLM-Hint vs Final-Pattern-Disagreement" — wo der Hint vom
              Klassifikator und das Final-Pattern (nach Rule-/Safety-Override)
              auseinanderfallen. Das ist auch die Daseinsberechtigungs-Statistik
              für jede einzelne Routing-Rule.
            </div>

            {/* 2. Degradation */}
            {degradations && degradations.groups.length > 0 && (
              <DetailAccordion
                title="Degradation — fehlende Slots führen zu Rückfallen"
                emoji="⚠️"
                summary={`${degradations.total} degradierte Turns · ${degradations.groups.length} Muster`}
                open={openDetail === 'degradation'}
                onToggle={() => setOpenDetail(openDetail === 'degradation' ? null : 'degradation')}
                explanation={
                  <>
                    <em>Degradation</em> bedeutet: ein Pattern hat seine reguläre Antwort aufgegeben und
                    auf eine einfachere Rückfrage („Zu welchem Thema genau?") degradiert, weil Pflicht-Slots
                    nicht gefüllt waren. Beispiel: M10 Canvas-Create braucht <code>thema</code> und
                    <code>material_typ</code> — fehlt einer, wird degradiert. Gruppen unten zeigen, welche
                    <code>(Pattern × fehlende Slots)</code>-Kombinationen am häufigsten auftreten —
                    dort lohnt es, die Slot-Erkennung im Classifier oder die Fragetechniken des Patterns
                    zu verbessern.
                  </>
                }>
                {degradations.groups.slice(0, 15).map((g, i) => (
                  <div key={`${g.pattern_id}-${i}`}
                       style={{ padding: 10, background: '#FEF3C7', borderRadius: 4, borderLeft: '3px solid #D97706', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                      <div style={{ fontSize: 13 }}>
                        <strong>{g.pattern_id || '(leer)'}</strong>
                        {g.missing_slots.length > 0 && (
                          <span style={{ marginLeft: 8, color: '#78350F' }}>
                            fehlende Slots: {g.missing_slots.map(s => <code key={s} style={{ background: '#fff', padding: '1px 4px', borderRadius: 2, marginRight: 4 }}>{s}</code>)}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        <strong>{g.count}×</strong>
                      </div>
                    </div>
                    {g.example_message && (
                      <div style={{ fontSize: 12, color: '#78350F', fontStyle: 'italic', marginTop: 4 }}>„{g.example_message}"</div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {g.example_persona && <span>Persona: <code>{g.example_persona}</code></span>}
                      {g.example_intent && <span>Intent: <code>{g.example_intent}</code></span>}
                      {g.example_state && <span>State: <code>{g.example_state}</code></span>}
                      <button
                        onClick={() => { setFilterPattern(g.pattern_id); setTab('logs'); }}
                        style={{ marginLeft: 'auto', background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                        Alle Turns mit {g.pattern_id} →
                      </button>
                    </div>
                  </div>
                ))}
              </DetailAccordion>
            )}

            {/* 3. Empty entities */}
            {emptyEntities && emptyEntities.groups.length > 0 && (
              <DetailAccordion
                title="Leere Entities — wo extrahiert der Classifier nichts?"
                emoji="📭"
                summary={`${emptyEntities.total} Turns ohne Entities · ${emptyEntities.groups.length} Intent×Pattern-Kombinationen`}
                open={openDetail === 'entities'}
                onToggle={() => setOpenDetail(openDetail === 'entities' ? null : 'entities')}
                explanation={
                  <>
                    <em>Entities</em> sind strukturierte Parameter, die der Classifier aus der Nachricht
                    zieht — z.B. <code>thema</code>, <code>stufe</code>, <code>material_typ</code>,
                    <code>fach</code>. Leer (<code>{'{}'}</code>) ist normal bei Begrüßungen und Smalltalk,
                    aber bei Such- und Erstell-Intents („Material zu Photosynthese Klasse 6") sollte
                    etwas extrahiert werden. Wenn ein bestimmtes <strong>Intent</strong> konsistent
                    leere Entities hat, schärft man die Entity-Erkennung in <code>04-entities/entities.yaml</code>
                    oder den Classifier-Prompt (<code>04-intents/intents.yaml</code>) für dieses Intent.
                  </>
                }>
                {emptyEntities.groups.slice(0, 15).map((g, i) => (
                  <div key={`${g.intent_id}-${g.pattern_id}-${i}`}
                       style={{ padding: 10, background: '#F3F4F6', borderRadius: 4, borderLeft: '3px solid #6B7280', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                      <div style={{ fontSize: 13 }}>
                        Intent: <strong>{g.intent_id || '(leer)'}</strong>
                        {' '}· Pattern: <code>{g.pattern_id || '(leer)'}</code>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        <strong>{g.count}×</strong>
                      </div>
                    </div>
                    {g.example_message && (
                      <div style={{ fontSize: 12, color: '#1F2937', fontStyle: 'italic', marginTop: 4 }}>„{g.example_message}"</div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {g.example_persona && <span>Persona: <code>{g.example_persona}</code></span>}
                      {g.example_state && <span>State: <code>{g.example_state}</code></span>}
                      <button
                        onClick={() => { setFilterIntent(g.intent_id); setTab('logs'); }}
                        style={{ marginLeft: 'auto', background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                        Alle Turns mit {g.intent_id} →
                      </button>
                    </div>
                  </div>
                ))}
              </DetailAccordion>
            )}

            {/* 4. Low confidence */}
            {lowConfidence && lowConfidence.turns.length > 0 && (
              <DetailAccordion
                title="Niedrige Confidence — wo war der Classifier unsicher?"
                emoji="❓"
                summary={`${lowConfidence.total} Turns unter ${Math.round(lowConfidence.max_confidence * 100)}% Confidence`}
                open={openDetail === 'confidence'}
                onToggle={() => setOpenDetail(openDetail === 'confidence' ? null : 'confidence')}
                explanation={
                  <>
                    <em>Confidence</em> ist die finale Vertrauenszahl des Classifiers für das gewählte
                    Persona/Intent/Pattern nach allen Scorings. Werte &lt; 0.6 bedeuten: der Classifier
                    hat sich nicht entscheiden können, welches Pattern greifen sollte. Das passiert bei
                    mehrdeutigen oder neuartigen Nachrichten. Niedrigste Turns zuerst — so sieht man
                    konkrete <strong>Input-Muster</strong>, die die Klassifikation schwer finden. Konkrete
                    Behebung: Beispiele in <code>04-intents/intents.yaml</code> ergänzen oder
                    Signale schärfen.
                  </>
                }>
                {lowConfidence.turns.map(t => (
                  <div key={t.id}
                       style={{ padding: 10, background: '#EFF6FF', borderRadius: 4, borderLeft: '3px solid #3B82F6', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                      <div style={{ fontSize: 13, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <span>Pattern: <strong>{t.pattern_id || '(leer)'}</strong></span>
                        <span>Intent: <strong>{t.intent_id || '(leer)'}</strong></span>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10 }}>
                        <span>Conf: <strong style={{ color: t.final_confidence < 0.4 ? '#DC2626' : '#D97706' }}>{num(t.final_confidence)}</strong></span>
                        <span>Gap: <strong>{num(t.phase2_score_gap, 4)}</strong></span>
                      </div>
                    </div>
                    {t.message && (
                      <div style={{ fontSize: 12, color: '#1E3A8A', fontStyle: 'italic', marginTop: 4 }}>„{t.message}"</div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {t.persona_id && <span>Persona: <code>{t.persona_id}</code></span>}
                      {t.state_id && <span>State: <code>{t.state_id}</code></span>}
                      <button
                        onClick={() => { setFilterSession(t.id.toString()); setTab('logs'); }}
                        style={{ marginLeft: 'auto', background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                        Details →
                      </button>
                    </div>
                  </div>
                ))}
              </DetailAccordion>
            )}

            {/* Empty state */}
            {!(degradations?.groups.length) &&
             !(emptyEntities?.groups.length) && !(lowConfidence?.turns.length) && (
              <div className="card" style={{ textAlign: 'center', color: 'var(--success)', padding: 16, fontSize: 13 }}>
                ✓ Keine auffälligen Probleme in diesem Scope.
              </div>
            )}
          </div>
        </>
      )}

      {tab === 'overview' && !stats && !loading && (
        <div className="card" style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
          Keine Quality-Daten vorhanden. Starte einen Chat, um Daten zu sammeln.
        </div>
      )}

      {/* ════════════════════ GESPRÄCHS-FLOW TAB ════════════════════ */}
      {tab === 'flow' && (
        <ConversationFlowView
          flow={flow}
          loading={flowLoading}
          days={flowDays}
          setDays={setFlowDays}
          minCount={flowMinCount}
          setMinCount={setFlowMinCount}
          onReload={loadFlow}
        />
      )}

      {/* ════════════════════ ROUTING-MATRIX TAB ════════════════════ */}
      {tab === 'matrix' && (
        <RoutingMatrixView
          matrix={matrix}
          loading={matrixLoading}
          minCount={matrixMinCount}
          setMinCount={setMatrixMinCount}
          onReload={loadMatrix}
          onCellClick={(personaId, intentId) => {
            setFilterPattern('');
            setFilterIntent(intentId);
            setFilterSession('');
            // Persona filter doesn't exist as input → use session-id-free
            // intent filter and let the user see all matching turns. For
            // the Persona dimension we rely on the user scanning the
            // intent-filtered logs (small per-cell volume).
            setTab('logs');
          }}
        />
      )}

      {/* ════════════════════ LOGS TAB ════════════════════ */}
      {tab === 'logs' && (
        <>
          {/* Filters */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              className="input"
              placeholder="Pattern-ID (z.B. M04)"
              value={filterPattern}
              onChange={e => setFilterPattern(e.target.value)}
              style={{ padding: '6px 10px', width: 170 }}
            />
            <input
              className="input"
              placeholder="Intent-ID (z.B. I02)"
              value={filterIntent}
              onChange={e => setFilterIntent(e.target.value)}
              style={{ padding: '6px 10px', width: 170 }}
            />
            <input
              className="input"
              placeholder="Session-ID"
              value={filterSession}
              onChange={e => setFilterSession(e.target.value)}
              style={{ padding: '6px 10px', width: 170 }}
            />
            {(filterPattern || filterIntent || filterSession) && (
              <button className="btn btn-sm" onClick={() => { setFilterPattern(''); setFilterIntent(''); setFilterSession(''); }}>✕ Filter zurücksetzen</button>
            )}
            <button
              className="btn btn-sm"
              onClick={clearFiltered}
              disabled={busy !== null || logs.length === 0}
              style={{ background: '#DC2626', color: '#fff', borderColor: '#DC2626' }}
              title={
                filterPattern || filterIntent || filterSession
                  ? 'Alle Einträge die aktuell den Filter treffen löschen'
                  : 'Alle Quality-Logs löschen (ohne Filter)'
              }
            >
              {busy === 'bulk' ? '…' : `🗑 ${filterPattern || filterIntent || filterSession ? 'Gefilterte' : 'Alle'} löschen`}
            </button>
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, alignItems: 'center', gap: 6 }}>
                      <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{log.pattern_id}</span>
                      <span style={{ color: 'var(--text-muted)', marginLeft: 'auto' }}>
                        {new Date(log.created_at).toLocaleString('de-DE')}
                      </span>
                      <button
                        title="Diesen Log-Eintrag löschen"
                        disabled={busy === log.id}
                        onClick={(e) => { e.stopPropagation(); deleteOne(log.id); }}
                        style={{
                          border: 'none',
                          background: 'transparent',
                          cursor: 'pointer',
                          fontSize: 12,
                          padding: '2px 4px',
                          color: '#DC2626',
                          opacity: busy === log.id ? 0.4 : 0.7,
                        }}
                      >
                        🗑
                      </button>
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
                    <span
                      style={{
                        fontSize: 12,
                        color: 'var(--text-muted)',
                        marginLeft: 'auto',
                        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                        wordBreak: 'break-all',
                      }}
                      title={selected.session_id}
                    >
                      Session: {selected.session_id}
                    </span>
                    <button
                      className="btn btn-sm"
                      disabled={busy === selected.id}
                      onClick={() => deleteOne(selected.id)}
                      title="Diesen Log-Eintrag löschen"
                      style={{ background: '#DC2626', color: '#fff', borderColor: '#DC2626', fontSize: 11 }}
                    >
                      🗑 Löschen
                    </button>
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

/* ── DetailAccordion ─────────────────────────────────────────────────
 * Einheitlicher aufklappbarer Container für Problem-Diagnose-Sektionen.
 * Header mit Titel + Zusammenfassung, aufklappbar zu Erklärung + Beispielen.
 */
function DetailAccordion({
  title, emoji, summary, open, onToggle, explanation, children,
}: {
  title: string;
  emoji: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
  explanation: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="card" style={{ marginBottom: 10, padding: 0, overflow: 'hidden' }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', padding: 12, background: open ? '#F9FAFB' : '#fff',
          border: 0, borderBottom: open ? '1px solid #E5E7EB' : 0,
          cursor: 'pointer', textAlign: 'left', display: 'flex',
          justifyContent: 'space-between', alignItems: 'center', gap: 12,
        }}>
        <span style={{ fontSize: 14, fontWeight: 600 }}>
          {emoji} {title}
        </span>
        <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{summary}</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
        </span>
      </button>
      {open && (
        <div style={{ padding: 12 }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12, lineHeight: 1.5 }}>
            {explanation}
          </div>
          {children}
        </div>
      )}
    </div>
  );
}
