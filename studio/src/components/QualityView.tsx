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
  const [tightRaces, setTightRaces] = useState<TightRaces | null>(null);
  const [degradations, setDegradations] = useState<Degradations | null>(null);
  const [emptyEntities, setEmptyEntities] = useState<EmptyEntities | null>(null);
  const [lowConfidence, setLowConfidence] = useState<LowConfidence | null>(null);
  const [openDetail, setOpenDetail] = useState<'tight' | 'degradation' | 'entities' | 'confidence' | null>('tight');
  const [selected, setSelected] = useState<QualityLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<'overview' | 'logs'>('overview');
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
      const [logsRes, statsRes, tightRes, degRes, entRes, confRes] = await Promise.all([
        fetch(`/api/quality/logs?${params}`),
        fetch(`/api/quality/stats?scope=${scope}`),
        fetch(`/api/quality/tight-races?scope=${scope}&limit=30`),
        fetch(`/api/quality/degradations?scope=${scope}&limit=30`),
        fetch(`/api/quality/empty-entities?scope=${scope}&limit=30`),
        fetch(`/api/quality/low-confidence?scope=${scope}&limit=30`),
      ]);
      if (logsRes.ok) {
        const data = await logsRes.json();
        setLogs(data.logs || []);
      }
      if (statsRes.ok) setStats(await statsRes.json());
      setTightRaces(tightRes.ok ? await tightRes.json() : null);
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
  const tightRaceLogs = logs.filter(l => l.phase2_score_gap < 0.02 && l.phase2_score_gap >= 0);
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
                  <div>• {stats.tight_races} Tight Races — siehe Diagnose unten</div>
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

            {/* 1. Tight Races */}
            {tightRaces && tightRaces.pairs.length > 0 && (
              <DetailAccordion
                title="Tight Races — welche Pattern konkurrieren?"
                emoji="⚖️"
                summary={`${tightRaces.total_tight} knappe Entscheidungen · ${tightRaces.pairs.length} eindeutige Paare`}
                open={openDetail === 'tight'}
                onToggle={() => setOpenDetail(openDetail === 'tight' ? null : 'tight')}
                explanation={
                  <>
                    Ein <em>Tight Race</em> ist ein Turn, bei dem das gewinnende Pattern nur knapp
                    (Score-Gap &lt; {tightRaces.threshold}) vor dem Zweitplatzierten lag — die
                    Pattern-Auswahl war also fast zufällig. Gruppen nach <code>(Gewinner, Verlierer)</code>
                    zeigen, welche <strong>Pattern-Paare</strong> strukturell kollidieren. Hohe
                    Kollisions-Counts sind Kandidaten dafür, die <code>signal_high_fit</code>,
                    <code>gate_intents</code> oder <code>priority</code>-Felder dieser Patterns zu schärfen.
                  </>
                }>
                {tightRaces.pairs.slice(0, 15).map((p, i) => (
                  <div key={`${p.winner}-${p.runner_up}-${i}`}
                       style={{ padding: 10, background: '#FFFBEB', borderRadius: 4, borderLeft: '3px solid #F59E0B', marginBottom: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
                      <div style={{ fontSize: 13 }}>
                        <strong>{p.winner || '(leer)'}</strong> vs. <strong>{p.runner_up || '(leer)'}</strong>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 10 }}>
                        <span><strong>{p.count}×</strong> kollidiert</span>
                        <span>Ø Abstand: <strong>{p.avg_gap.toFixed(4)}</strong></span>
                      </div>
                    </div>
                    {p.example_message && (
                      <div style={{ fontSize: 12, color: '#78350F', fontStyle: 'italic', marginTop: 4 }}>
                        „{p.example_message}"
                      </div>
                    )}
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {p.example_persona && <span>Persona: <code>{p.example_persona}</code></span>}
                      {p.example_intent && <span>Intent: <code>{p.example_intent}</code></span>}
                      {p.example_state && <span>State: <code>{p.example_state}</code></span>}
                      <button
                        onClick={() => { setFilterPattern(p.winner); setTab('logs'); }}
                        style={{ marginLeft: 'auto', background: 'none', border: 0, color: 'var(--primary)', cursor: 'pointer', fontSize: 11, padding: 0 }}>
                        Alle Turns mit {p.winner} →
                      </button>
                    </div>
                  </div>
                ))}
              </DetailAccordion>
            )}

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
                    nicht gefüllt waren. Beispiel: PAT-21 Canvas-Create braucht <code>thema</code> und
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
            {!(tightRaces?.pairs.length) && !(degradations?.groups.length) &&
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

      {/* ════════════════════ LOGS TAB ════════════════════ */}
      {tab === 'logs' && (
        <>
          {/* Filters */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            <input
              className="input"
              placeholder="Pattern-ID (z.B. PAT-10)"
              value={filterPattern}
              onChange={e => setFilterPattern(e.target.value)}
              style={{ padding: '6px 10px', width: 170 }}
            />
            <input
              className="input"
              placeholder="Intent-ID (z.B. INT-W-06)"
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
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                      Session: {selected.session_id.slice(0, 8)}…
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
