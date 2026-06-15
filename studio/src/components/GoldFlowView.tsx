'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchJson } from '@/lib/api';

/* ════════════════════════════════════════════════════════════════════
   Gold-Flow View — deterministische, geprüfte Multi-Turn-Abläufe.

   Drei Tabs:
     • Flows      — Katalog der Soll-Abläufe + Lauf starten
     • Läufe      — Golden-Runs + deterministische Scorecard je Lauf
     • Vergleich  — Lauf A vs B (Modell-/Config-Regression auf einen Blick)

   Anders als die generative Evaluation sind die Eingaben fix → ein Lauf
   ist reproduzierbar und A/B-vergleichbar.
   ════════════════════════════════════════════════════════════════════ */

/* ── Types ─────────────────────────────────────────────────────────── */
interface GoldExpect {
  persona?: string; intent?: string; register?: string;
  structure?: string | null; must_offer?: string;
}
interface GoldTurnSpec { message: string; expect: GoldExpect; }
interface GoldFlow {
  id: string; persona: string; title?: string;
  intents?: string[]; turns: GoldTurnSpec[];
}

type Check = boolean | null | undefined;
interface GoldChecks {
  persona?: Check; intent?: Check; register?: Check;
  structure?: Check; qr?: Check; host?: Check;
}
interface GoldObserved {
  persona?: string; intent?: string; pattern?: string; register?: string;
  sie?: number; du?: number; cards?: number; idocs?: number; qr?: number;
  content_len?: number;
}
interface GoldPerTurn {
  flow: string; title?: string; turn: number; message: string;
  expected: GoldExpect; observed: GoldObserved; checks: GoldChecks;
  judge_total?: number | null;
}
interface GoldMetrics {
  categories: string[];
  totals: Record<string, number>;
  passed: Record<string, number>;
  rates: Record<string, number | null>;
  overall_pass_rate: number;
  hard_passed: number; hard_total: number;
  judge_avg?: number | null; judged_turns?: number;
  flows: number; turns: number;
  per_turn: GoldPerTurn[];
}
interface GoldRun {
  id: string; created_at: string; completed_at: string | null;
  status: 'running' | 'done' | 'failed'; mode: string;
  total_turns: number; avg_score: number; config_slug?: string;
  current_activity?: string; target_turns?: number; error_message?: string;
}
interface GoldConvTurn { user?: string; bot?: string }
interface GoldConv { flow_id?: string; persona_id?: string; turns?: GoldConvTurn[] }
interface GoldRunDetail extends GoldRun {
  summary?: { golden_metrics?: GoldMetrics; current_activity?: string; target_turns?: number };
  conversations?: GoldConv[];
}

/* ── Helpers ───────────────────────────────────────────────────────── */
const CAT_LABEL: Record<string, string> = {
  persona: 'Persona', intent: 'Intent', register: 'Tonalität',
  structure: 'Struktur', qr: 'Quick-Replies', host: 'Link-Host',
};
const pct = (v: number | null | undefined): string =>
  v == null ? '–' : `${Math.round(v * 100)}%`;
const rateColor = (v: number | null | undefined): string =>
  v == null ? '#9ca3af' : v >= 0.9 ? '#16a34a' : v >= 0.7 ? '#d97706' : '#dc2626';
const fmtDate = (s: string): string => {
  try { return new Date(s).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }); }
  catch { return s; }
};
const markGlyph = (v: Check): { t: string; c: string } =>
  v === true ? { t: '✓', c: '#16a34a' }
  : v === false ? { t: '✗', c: '#dc2626' }
  : { t: '–', c: '#cbd5e1' };

function CheckCell({ v }: { v: Check }) {
  const m = markGlyph(v);
  return <span style={{ color: m.c, fontWeight: 700 }}>{m.t}</span>;
}

// Per-Flow-Aggregat (für die „GS-x Gesamt"-Zwischenzeile in der Turn-Tabelle).
const HARD5 = ['persona', 'intent', 'register', 'structure', 'qr'] as const;
function flowAgg(turns: GoldPerTurn[]) {
  const agg: Record<string, { ok: number; total: number }> = {
    persona: { ok: 0, total: 0 }, intent: { ok: 0, total: 0 },
    register: { ok: 0, total: 0 }, structure: { ok: 0, total: 0 }, qr: { ok: 0, total: 0 },
  };
  for (const t of turns) {
    for (const c of HARD5) {
      const v = t.checks[c];
      if (v === null || v === undefined) continue;
      agg[c].total++; if (v) agg[c].ok++;
    }
  }
  const ok = HARD5.reduce((a, c) => a + agg[c].ok, 0);
  const total = HARD5.reduce((a, c) => a + agg[c].total, 0);
  return { agg, ok, total, rate: total ? ok / total : null };
}
function Frac({ o }: { o: { ok: number; total: number } }) {
  if (!o.total) return <span style={{ color: '#cbd5e1' }}>–</span>;
  return <span style={{ color: rateColor(o.ok / o.total), fontWeight: 700 }}>{o.ok}/{o.total}</span>;
}

const card: React.CSSProperties = {
  border: '1px solid #e5e7eb', borderRadius: 10, background: '#fff', padding: 16,
};
const th: React.CSSProperties = {
  textAlign: 'left', padding: '6px 8px', fontSize: 12, color: '#6b7280',
  borderBottom: '1px solid #e5e7eb', fontWeight: 600, whiteSpace: 'nowrap',
};
const td: React.CSSProperties = {
  padding: '6px 8px', fontSize: 13, borderBottom: '1px solid #f1f5f9', verticalAlign: 'top',
};

/* ════════════════════════════════════════════════════════════════════ */
export default function GoldFlowView() {
  const [tab, setTab] = useState<'flows' | 'runs' | 'compare'>('flows');
  const [flows, setFlows] = useState<GoldFlow[]>([]);
  const [runs, setRuns] = useState<GoldRun[]>([]);
  const [err, setErr] = useState<string>('');

  // Fix 2026-06-10: fetchJson statt r.json() ohne ok-Check — ein 500er
  // lieferte vorher ein Parse-Chaos statt einer klaren Fehlermeldung.
  const loadFlows = useCallback(async () => {
    try {
      const d = await fetchJson<{ flows?: GoldFlow[] }>('/api/eval/gold-flows');
      setFlows(Array.isArray(d.flows) ? d.flows : []);
    } catch (e) { setErr(String(e)); }
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const d = await fetchJson<{ runs?: GoldRun[] }>('/api/eval/runs?limit=200');
      const all: GoldRun[] = Array.isArray(d.runs) ? d.runs : [];
      setRuns(all.filter(x => x.mode === 'golden'));
    } catch (e) { setErr(String(e)); }
  }, []);

  useEffect(() => { loadFlows(); loadRuns(); }, [loadFlows, loadRuns]);

  // Poll while any golden run is still running.
  useEffect(() => {
    const anyRunning = runs.some(r => r.status === 'running');
    if (!anyRunning) return;
    const id = setInterval(loadRuns, 3000);
    return () => clearInterval(id);
  }, [runs, loadRuns]);

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 20 }}>Gold-Flows</h2>
        <p style={{ margin: 0, color: '#6b7280', fontSize: 13, maxWidth: 760 }}>
          Geprüfte Multi-Turn-Abläufe für die wichtigsten Intents je Persona.
          Feste Eingaben → reproduzierbar &amp; A/B-vergleichbar. Harte Checks
          (Persona/Intent/Tonalität/Struktur/Quick-Replies) laufen
          programmatisch; der optionale Judge bewertet die weiche Qualität.
        </p>
      </div>

      {err && (
        <div style={{ ...card, borderColor: '#fecaca', background: '#fef2f2', color: '#b91c1c', marginBottom: 12 }}>
          {err}
        </div>
      )}

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 16, borderBottom: '1px solid #e5e7eb' }}>
        {([['flows', `Flows (${flows.length})`], ['runs', `Läufe (${runs.length})`], ['compare', 'Vergleich']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            style={{
              padding: '8px 14px', fontSize: 13, fontWeight: 600, cursor: 'pointer',
              background: 'none', border: 'none', borderBottom: tab === k ? '2px solid #2563eb' : '2px solid transparent',
              color: tab === k ? '#2563eb' : '#6b7280',
            }}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'flows' && <FlowsTab flows={flows} onStarted={() => { loadRuns(); setTab('runs'); }} />}
      {tab === 'runs' && <RunsTab runs={runs} onChanged={loadRuns} />}
      {tab === 'compare' && <CompareTab runs={runs.filter(r => r.status === 'done')} />}
    </div>
  );
}

/* ── Flows-Tab: Katalog + Lauf starten ─────────────────────────────── */
function FlowsTab({ flows, onStarted }: { flows: GoldFlow[]; onStarted: () => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [judge, setJudge] = useState(true);
  const [starting, setStarting] = useState(false);
  const [expanded, setExpanded] = useState<string>('');
  const [msg, setMsg] = useState('');

  // default: all selected once flows arrive
  useEffect(() => { setSelected(new Set(flows.map(f => f.id))); }, [flows]);

  const toggle = (id: string) => setSelected(s => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });

  const start = async () => {
    setStarting(true); setMsg('');
    try {
      const flow_ids = selected.size === flows.length ? [] : Array.from(selected);
      const r = await fetch('/api/eval/runs/golden', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ flow_ids, judge }),
      });
      const d = await r.json();
      if (!r.ok) { setMsg(d.detail || 'Start fehlgeschlagen'); setStarting(false); return; }
      setMsg(`Lauf ${d.run_id} gestartet (${d.turns_total} Turns).`);
      setTimeout(() => { setStarting(false); onStarted(); }, 600);
    } catch (e) { setMsg(String(e)); setStarting(false); }
  };

  const nTurns = flows.filter(f => selected.has(f.id)).reduce((a, f) => a + (f.turns?.length || 0), 0);

  return (
    <div>
      <div style={{ ...card, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <button onClick={start} disabled={starting || selected.size === 0}
          style={{
            padding: '9px 18px', fontSize: 14, fontWeight: 600, borderRadius: 8, border: 'none',
            background: selected.size === 0 ? '#cbd5e1' : '#2563eb', color: '#fff',
            cursor: selected.size === 0 ? 'default' : 'pointer',
          }}>
          {starting ? 'Starte …' : `Gold-Flow-Lauf starten (${selected.size} Flows · ${nTurns} Turns)`}
        </button>
        <label style={{ fontSize: 13, color: '#374151', display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={judge} onChange={e => setJudge(e.target.checked)} />
          LLM-Judge (weiche Qualität: Tonalität, Angebote)
        </label>
        <div style={{ display: 'flex', gap: 8, marginLeft: 'auto' }}>
          <button onClick={() => setSelected(new Set(flows.map(f => f.id)))}
            style={linkBtn}>Alle</button>
          <button onClick={() => setSelected(new Set())} style={linkBtn}>Keine</button>
        </div>
        {msg && <div style={{ flexBasis: '100%', fontSize: 13, color: '#2563eb' }}>{msg}</div>}
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse', ...card, padding: 0 }}>
        <thead><tr>
          <th style={th}></th>
          <th style={th}>Flow</th>
          <th style={th}>Persona</th>
          <th style={th}>Titel</th>
          <th style={th}>Intents</th>
          <th style={th}>Turns</th>
        </tr></thead>
        <tbody>
          {flows.map(f => (
            <FlowRow key={f.id} flow={f} checked={selected.has(f.id)}
              onToggle={() => toggle(f.id)}
              expanded={expanded === f.id}
              onExpand={() => setExpanded(expanded === f.id ? '' : f.id)} />
          ))}
          {flows.length === 0 && (
            <tr><td style={td} colSpan={6}>Keine Gold-Flows konfiguriert (eval/gold-flows.yaml).</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function FlowRow({ flow, checked, onToggle, expanded, onExpand }: {
  flow: GoldFlow; checked: boolean; onToggle: () => void; expanded: boolean; onExpand: () => void;
}) {
  return (
    <>
      <tr style={{ cursor: 'pointer' }}>
        <td style={td}><input type="checkbox" checked={checked} onChange={onToggle} /></td>
        <td style={{ ...td, fontWeight: 600 }} onClick={onExpand}>{flow.id}</td>
        <td style={td} onClick={onExpand}><Pill text={flow.persona} /></td>
        <td style={td} onClick={onExpand}>{flow.title}</td>
        <td style={td} onClick={onExpand}>{(flow.intents || []).join(', ')}</td>
        <td style={td} onClick={onExpand}>{flow.turns?.length || 0} {expanded ? '▾' : '▸'}</td>
      </tr>
      {expanded && (
        <tr><td style={{ ...td, background: '#f8fafc' }} colSpan={6}>
          <ol style={{ margin: '4px 0', paddingLeft: 20 }}>
            {flow.turns.map((t, i) => (
              <li key={i} style={{ marginBottom: 6, fontSize: 13 }}>
                <span style={{ color: '#111' }}>«{t.message}»</span>
                <div style={{ color: '#6b7280', fontSize: 12, marginTop: 2 }}>
                  Soll: {t.expect.persona} / {t.expect.intent}
                  {t.expect.register && t.expect.register !== 'any' ? ` · ${t.expect.register === 'sie' ? 'Sie' : 'du'}` : ''}
                  {t.expect.structure ? ` · ${t.expect.structure}` : ''}
                  {t.expect.must_offer ? ` — ${t.expect.must_offer}` : ''}
                </div>
              </li>
            ))}
          </ol>
        </td></tr>
      )}
    </>
  );
}

/* ── Läufe-Tab: Runs + Scorecard ───────────────────────────────────── */
function RunsTab({ runs, onChanged }: { runs: GoldRun[]; onChanged: () => void }) {
  const [sel, setSel] = useState<string>('');
  const [detail, setDetail] = useState<GoldRunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    setLoading(true);
    fetch(`/api/eval/runs/${sel}`).then(r => r.json())
      .then(d => setDetail(d)).catch(() => setDetail(null)).finally(() => setLoading(false));
  }, [sel]);

  const del = async (id: string) => {
    await fetch(`/api/eval/runs/${id}`, { method: 'DELETE' });
    if (sel === id) { setSel(''); setDetail(null); }
    onChanged();
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 16, alignItems: 'start' }}>
      <div style={{ ...card, padding: 0, maxHeight: 560, overflow: 'auto' }}>
        {runs.length === 0 && <div style={{ padding: 16, color: '#6b7280', fontSize: 13 }}>Noch keine Gold-Flow-Läufe.</div>}
        {runs.map(r => {
          const gm = r.avg_score;
          const running = r.status === 'running';
          const prog = r.target_turns ? Math.round(100 * (r.total_turns || 0) / r.target_turns) : 0;
          return (
            <div key={r.id} onClick={() => setSel(r.id)}
              style={{
                padding: 12, borderBottom: '1px solid #f1f5f9', cursor: 'pointer',
                background: sel === r.id ? '#eff6ff' : 'transparent',
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{r.id.replace('eval-', '')}</span>
                <StatusBadge status={r.status} />
              </div>
              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{fmtDate(r.created_at)}</div>
              {running ? (
                <div style={{ marginTop: 6 }}>
                  <div style={{ height: 4, background: '#e5e7eb', borderRadius: 2 }}>
                    <div style={{ height: 4, width: `${prog}%`, background: '#2563eb', borderRadius: 2 }} />
                  </div>
                  <div style={{ fontSize: 11, color: '#6b7280', marginTop: 3 }}>{r.current_activity || `${r.total_turns}/${r.target_turns}`}</div>
                </div>
              ) : (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: rateColor(gm) }} title="Harte Bestehensquote (deterministisch) — identisch zur Scorecard-Gesamtzahl.">
                    {pct(gm)}<span style={{ fontSize: 10, fontWeight: 400, color: '#9ca3af' }}>&nbsp;hart</span>
                  </span>
                  <span style={{ fontSize: 11, color: '#9ca3af' }}>{r.total_turns} Turns</span>
                  <button onClick={e => { e.stopPropagation(); del(r.id); }} style={{ ...linkBtn, color: '#dc2626' }}>Löschen</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div>
        {loading && <div style={{ ...card, color: '#6b7280' }}>Lade …</div>}
        {!loading && !detail && <div style={{ ...card, color: '#6b7280' }}>Lauf links auswählen.</div>}
        {!loading && detail && <RunScorecard detail={detail} />}
      </div>
    </div>
  );
}

function RunScorecard({ detail }: { detail: GoldRunDetail }) {
  const [expandedKey, setExpandedKey] = useState<string>('');
  const gm = detail.summary?.golden_metrics;
  if (!gm) {
    return <div style={{ ...card, color: '#6b7280' }}>
      {detail.status === 'running' ? (detail.summary?.current_activity || 'Läuft …') : 'Keine Gold-Metriken in diesem Lauf.'}
    </div>;
  }
  // Bot-Antwort je Turn (für die ausklappbare Detailzeile) aus den
  // gespeicherten Konversationen indexieren: flow_id + 1-basierter Turn.
  const botByKey = new Map<string, string>();
  for (const c of detail.conversations ?? []) {
    const fid = c.flow_id ?? c.persona_id ?? '?';
    (c.turns ?? []).forEach((t, i) => botByKey.set(`${fid}__${i + 1}`, t.bot ?? ''));
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Aggregate cards */}
      <div style={{ ...card }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Trefferquoten</h3>
          <span style={{ fontSize: 13, color: '#6b7280' }}>
            {gm.flows} Flows · {gm.turns} Turns · Gesamt&nbsp;
            <b style={{ color: rateColor(gm.overall_pass_rate) }} title="Anteil bestandener harter Checks (deterministisch) — identisch zur Zahl in der Lauf-Liste links.">{pct(gm.overall_pass_rate)}</b>
            <span style={{ color: '#9ca3af' }}> (hart)</span>
            {gm.judge_avg != null && (
              <span title="Schnitt der weichen LLM-Judge-Bewertung über die bewerteten Turns. Separate Metrik, fließt NICHT in die Headline-Quote ein.">
                {' · '}Judge&nbsp;<b style={{ color: rateColor(gm.judge_avg) }}>{pct(gm.judge_avg)}</b>
                <span style={{ color: '#9ca3af' }}>&nbsp;({gm.judged_turns ?? gm.turns})</span>
              </span>
            )}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
          {gm.categories.map(c => (
            <div key={c} style={{ border: '1px solid #f1f5f9', borderRadius: 8, padding: '10px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: rateColor(gm.rates[c]) }}>{pct(gm.rates[c])}</div>
              <div style={{ fontSize: 12, color: '#6b7280' }}>{CAT_LABEL[c] || c}</div>
              <div style={{ fontSize: 11, color: '#9ca3af' }}>{gm.passed[c]}/{gm.totals[c]}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Per-turn table */}
      <div style={{ ...card, padding: 0, overflow: 'auto' }}>
        <div style={{ padding: '8px 12px', fontSize: 12, color: '#94a3b8', borderBottom: '1px solid #f1f5f9' }}>
          Zeile anklicken für die vollständige Bot-Antwort.
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead><tr>
            <th style={th}>Flow·T</th><th style={th}>Soll P/I</th>
            <th style={th}>Ist P/I/Pattern</th><th style={th}>Pers</th><th style={th}>Int</th>
            <th style={th}>Ton</th><th style={th}>Struk</th><th style={th}>QR</th>
            <th style={th}>Nachricht</th>
          </tr></thead>
          <tbody>
            {(() => {
              // Turns nach Flow gruppieren (Reihenfolge erhalten) und nach
              // jeder Flow-Gruppe eine „GS-x Gesamt"-Zwischenzeile einfügen.
              const order: string[] = [];
              const groups: Record<string, GoldPerTurn[]> = {};
              for (const t of gm.per_turn) {
                if (!groups[t.flow]) { groups[t.flow] = []; order.push(t.flow); }
                groups[t.flow].push(t);
              }
              const out: React.ReactNode[] = [];
              for (const fid of order) {
                const turns = groups[fid];
                turns.forEach((t, i) => {
                  const k = `${t.flow}__${t.turn}`;
                  const open = expandedKey === k;
                  out.push(
                    <tr key={`${fid}-t${t.turn}-${i}`} onClick={() => setExpandedKey(open ? '' : k)}
                      style={{ cursor: 'pointer', background: open ? '#f8fafc' : 'transparent' }}>
                      <td style={{ ...td, whiteSpace: 'nowrap', fontWeight: 600 }}>{open ? '▾' : '▸'} {t.flow}·{t.turn}</td>
                      <td style={{ ...td, whiteSpace: 'nowrap', color: '#6b7280' }}>{t.expected.persona}/{t.expected.intent}</td>
                      <td style={{ ...td, whiteSpace: 'nowrap' }}>{t.observed.persona}/{t.observed.intent}/<b>{t.observed.pattern}</b></td>
                      <td style={td}><CheckCell v={t.checks.persona} /></td>
                      <td style={td}><CheckCell v={t.checks.intent} /></td>
                      <td style={td}><CheckCell v={t.checks.register} /></td>
                      <td style={td}><CheckCell v={t.checks.structure} /></td>
                      <td style={td}><CheckCell v={t.checks.qr} /></td>
                      <td style={{ ...td, maxWidth: 280, color: '#6b7280' }}>{t.message}</td>
                    </tr>
                  );
                  if (open) {
                    out.push(
                      <tr key={`${fid}-d${t.turn}-${i}`}>
                        <td colSpan={9} style={{ background: '#f8fafc', padding: '10px 14px', borderBottom: '1px solid #e5e7eb' }}>
                          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 6 }}>
                            <b>Ideal:</b> {t.expected.must_offer || '—'}
                            <span style={{ marginLeft: 12 }}>
                              beobachtet: Sie={t.observed.sie ?? 0} · du={t.observed.du ?? 0} · Karten {t.observed.cards ?? 0} · idocs {t.observed.idocs ?? 0} · QR {t.observed.qr ?? 0}
                            </span>
                          </div>
                          <div style={{ whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.5, maxHeight: 320, overflow: 'auto', background: '#fff', border: '1px solid #eef2f7', borderRadius: 6, padding: '8px 10px' }}>
                            {botByKey.get(k) || '(kein Antworttext gespeichert)'}
                          </div>
                        </td>
                      </tr>
                    );
                  }
                });
                const a = flowAgg(turns);
                out.push(
                  <tr key={`${fid}-sum`} style={{ background: '#eef2f7', borderTop: '2px solid #dbe2ea' }}>
                    <td style={{ ...td, fontWeight: 700 }}>{fid} Gesamt</td>
                    <td style={td}></td>
                    <td style={{ ...td, textAlign: 'right', color: '#94a3b8', fontSize: 11 }}>Σ Checks →</td>
                    <td style={td}><Frac o={a.agg.persona} /></td>
                    <td style={td}><Frac o={a.agg.intent} /></td>
                    <td style={td}><Frac o={a.agg.register} /></td>
                    <td style={td}><Frac o={a.agg.structure} /></td>
                    <td style={td}><Frac o={a.agg.qr} /></td>
                    <td style={{ ...td, fontWeight: 700, color: rateColor(a.rate) }}>
                      {a.rate == null ? '–' : `${Math.round(a.rate * 100)}% · ${a.ok}/${a.total} Checks bestanden`}
                    </td>
                  </tr>
                );
              }
              return out;
            })()}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Vergleich-Tab: Lauf A vs B ────────────────────────────────────── */
function CompareTab({ runs }: { runs: GoldRun[] }) {
  const [a, setA] = useState('');
  const [b, setB] = useState('');
  const [da, setDa] = useState<GoldRunDetail | null>(null);
  const [db, setDb] = useState<GoldRunDetail | null>(null);
  const fetched = useRef<Record<string, GoldRunDetail>>({});

  const fetchDetail = useCallback(async (id: string): Promise<GoldRunDetail | null> => {
    if (!id) return null;
    if (fetched.current[id]) return fetched.current[id];
    try {
      const r = await fetch(`/api/eval/runs/${id}`);
      const d = await r.json();
      fetched.current[id] = d;
      return d;
    } catch { return null; }
  }, []);

  useEffect(() => { fetchDetail(a).then(setDa); }, [a, fetchDetail]);
  useEffect(() => { fetchDetail(b).then(setDb); }, [b, fetchDetail]);

  // auto-pick the two most recent done runs
  useEffect(() => {
    if (runs.length >= 2 && !a && !b) { setA(runs[1].id); setB(runs[0].id); }
    else if (runs.length === 1 && !b) { setB(runs[0].id); }
  }, [runs, a, b]);

  const gmA = da?.summary?.golden_metrics;
  const gmB = db?.summary?.golden_metrics;

  const pick = (val: string, set: (v: string) => void, label: string) => (
    <label style={{ fontSize: 13, color: '#374151' }}>
      {label}{' '}
      <select value={val} onChange={e => set(e.target.value)}
        style={{ padding: '6px 8px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13 }}>
        <option value="">— wählen —</option>
        {runs.map(r => (
          <option key={r.id} value={r.id}>
            {r.id.replace('eval-', '')} · {fmtDate(r.created_at)} · {pct(r.avg_score)}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ ...card, display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
        {pick(a, setA, 'A (Basis):')}
        {pick(b, setB, 'B (Vergleich):')}
        {runs.length < 2 && <span style={{ fontSize: 13, color: '#9ca3af' }}>Mindestens 2 abgeschlossene Gold-Läufe nötig.</span>}
      </div>

      {gmA && gmB && (
        <>
          {/* Aggregate deltas */}
          <div style={{ ...card, padding: 0, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead><tr>
                <th style={th}>Kategorie</th><th style={th}>A</th><th style={th}>B</th><th style={th}>Δ (B−A)</th>
              </tr></thead>
              <tbody>
                {['overall', ...gmA.categories].map(c => {
                  const ra = c === 'overall' ? gmA.overall_pass_rate : gmA.rates[c];
                  const rb = c === 'overall' ? gmB.overall_pass_rate : gmB.rates[c];
                  const delta = (ra != null && rb != null) ? rb - ra : null;
                  return (
                    <tr key={c}>
                      <td style={{ ...td, fontWeight: c === 'overall' ? 700 : 400 }}>{c === 'overall' ? 'Gesamt (hart)' : (CAT_LABEL[c] || c)}</td>
                      <td style={{ ...td, color: rateColor(ra) }}>{pct(ra)}</td>
                      <td style={{ ...td, color: rateColor(rb) }}>{pct(rb)}</td>
                      <td style={{ ...td, fontWeight: 600, color: delta == null ? '#9ca3af' : delta > 0 ? '#16a34a' : delta < 0 ? '#dc2626' : '#6b7280' }}>
                        {delta == null ? '–' : `${delta > 0 ? '▲ +' : delta < 0 ? '▼ ' : ''}${Math.round(delta * 100)}pp`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Per-turn diff */}
          <PerTurnDiff gmA={gmA} gmB={gmB} />
        </>
      )}
      {(a && !gmA) && <div style={{ ...card, color: '#6b7280' }}>Lauf A hat keine Gold-Metriken.</div>}
      {(b && !gmB) && <div style={{ ...card, color: '#6b7280' }}>Lauf B hat keine Gold-Metriken.</div>}
    </div>
  );
}

function PerTurnDiff({ gmA, gmB }: { gmA: GoldMetrics; gmB: GoldMetrics }) {
  const key = (t: GoldPerTurn) => `${t.flow}__${t.turn}`;
  const mapA = new Map(gmA.per_turn.map(t => [key(t), t]));
  const mapB = new Map(gmB.per_turn.map(t => [key(t), t]));
  const keys = gmA.per_turn.map(key).filter(k => mapB.has(k)); // common turns, A order

  const cell = (t?: GoldPerTurn) => {
    if (!t) return <td style={{ ...td, color: '#9ca3af' }}>–</td>;
    return (
      <td style={{ ...td, whiteSpace: 'nowrap' }}>
        {t.observed.persona}/{t.observed.intent}/<b>{t.observed.pattern}</b>{' '}
        <CheckCell v={t.checks.persona} /><CheckCell v={t.checks.intent} />
        <CheckCell v={t.checks.register} /><CheckCell v={t.checks.structure} />
      </td>
    );
  };

  return (
    <div style={{ ...card, padding: 0, overflow: 'auto' }}>
      <div style={{ padding: '10px 12px', fontSize: 12, color: '#6b7280', borderBottom: '1px solid #e5e7eb' }}>
        Pro Turn: P/I/Pattern + Checks (Persona·Intent·Ton·Struktur). Gelb = A und B unterscheiden sich.
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead><tr>
          <th style={th}>Flow·T</th><th style={th}>Soll P/I</th>
          <th style={th}>A</th><th style={th}>B</th><th style={th}>Nachricht</th>
        </tr></thead>
        <tbody>
          {keys.map(k => {
            const ta = mapA.get(k); const tb = mapB.get(k);
            const differ = ta && tb && (
              ta.observed.persona !== tb.observed.persona ||
              ta.observed.intent !== tb.observed.intent ||
              ta.observed.pattern !== tb.observed.pattern
            );
            return (
              <tr key={k} style={{ background: differ ? '#fffbeb' : 'transparent' }}>
                <td style={{ ...td, fontWeight: 600, whiteSpace: 'nowrap' }}>{ta?.flow}·{ta?.turn}</td>
                <td style={{ ...td, color: '#6b7280', whiteSpace: 'nowrap' }}>{ta?.expected.persona}/{ta?.expected.intent}</td>
                {cell(ta)}{cell(tb)}
                <td style={{ ...td, maxWidth: 260, color: '#6b7280' }}>{ta?.message}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/* ── small atoms ───────────────────────────────────────────────────── */
const linkBtn: React.CSSProperties = {
  background: 'none', border: 'none', color: '#2563eb', fontSize: 12,
  cursor: 'pointer', padding: '2px 4px', fontWeight: 600,
};
function Pill({ text }: { text: string }) {
  return <span style={{ fontSize: 12, padding: '1px 7px', borderRadius: 999, background: '#f1f5f9', color: '#334155', fontWeight: 600 }}>{text}</span>;
}
function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { c: string; bg: string; t: string }> = {
    done: { c: '#166534', bg: '#dcfce7', t: 'fertig' },
    running: { c: '#1e40af', bg: '#dbeafe', t: 'läuft' },
    failed: { c: '#b91c1c', bg: '#fee2e2', t: 'Fehler' },
  };
  const s = map[status] || { c: '#374151', bg: '#f1f5f9', t: status };
  return <span style={{ fontSize: 11, fontWeight: 600, color: s.c, background: s.bg, padding: '1px 7px', borderRadius: 999 }}>{s.t}</span>;
}
