'use client';

// ── Lasttest-View (2026-06-10) ───────────────────────────────────────
//
// Studio-Selbsttest für Skalierbarkeit: fährt ein Stufen-Profil mit
// gemischten Abfragen gegen die eigene Chat-Pipeline (Backend-Endpoint
// /api/loadtest) und zeigt die Auswertung grafisch — Latenz-Perzentile
// vs. Parallelität, Fehlerrate, CPU-/RAM-Verlauf — plus ein Fazit zur
// stabilen Parallel-Last.
//
// WICHTIG: Ein Run feuert ECHTE LLM-/MCP-Requests (Kosten + Staging-
// Last). Das Formular zeigt die Gesamtzahl vor dem Start an; das
// Backend deckelt zusätzlich hart (max 6 Stufen / 32 parallel / 200
// Requests, ein Run gleichzeitig).

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchJson } from '@/lib/api';

interface MixOption { key: string; label: string; prompt: string }

interface StageResult {
  concurrency: number;
  requests: number;
  ok: number;
  errors: number;
  error_kinds: string[];
  p50_s: number;
  p95_s: number;
  max_s: number;
  mean_s: number;
  duration_s: number;
  rps: number;
  by_kind: Record<string, { n: number; ok: number; p50_s: number; p95_s: number }>;
}

interface ResourceSample { t: number; proc_cpu: number; sys_cpu: number; rss_mb: number }

interface LoadTestRun {
  id: string;
  status: 'running' | 'completed' | 'failed';
  created_at: string;
  finished_at: string | null;
  profile: { stages: number[]; requests_per_stage: number; mix: Record<string, number>; p95_threshold_s: number; total_requests: number };
  stages: StageResult[];
  resource_samples: ResourceSample[];
  summary: {
    stable_concurrency: number | null;
    p95_threshold_s: number;
    peak_rss_mb: number;
    peak_proc_cpu_pct: number;
    total_requests: number;
    total_errors: number;
  } | null;
  error: string | null;
}

interface RunListItem {
  id: string; status: string; created_at: string;
  summary: LoadTestRun['summary']; profile: LoadTestRun['profile']; error: string | null;
}

// ── Kleine SVG-Chart-Helfer (kein Chart-Lib-Zusatz) ──────────────────

function LatencyChart({ stages, threshold }: { stages: StageResult[]; threshold: number }) {
  const W = 560, H = 220, PAD = 44;
  const xs = stages.map(s => s.concurrency);
  const maxY = Math.max(threshold, ...stages.map(s => s.p95_s), 1) * 1.15;
  const x = (i: number) => PAD + (xs.length === 1 ? (W - 2 * PAD) / 2 : (i / (xs.length - 1)) * (W - 2 * PAD));
  const y = (v: number) => H - PAD - (v / maxY) * (H - 2 * PAD);
  const line = (key: 'p50_s' | 'p95_s') =>
    stages.map((s, i) => `${x(i)},${y(s[key])}`).join(' ');
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: W }}>
      {/* Achsen */}
      <line x1={PAD} y1={H - PAD} x2={W - PAD / 2} y2={H - PAD} stroke="#D1D5DB" />
      <line x1={PAD} y1={PAD / 2} x2={PAD} y2={H - PAD} stroke="#D1D5DB" />
      {/* p95-Schwelle */}
      <line x1={PAD} y1={y(threshold)} x2={W - PAD / 2} y2={y(threshold)}
        stroke="#DC2626" strokeDasharray="5 4" />
      <text x={W - PAD / 2} y={y(threshold) - 4} fontSize="10" fill="#DC2626" textAnchor="end">
        p95-Schwelle {threshold}s
      </text>
      {/* Linien */}
      <polyline points={line('p95_s')} fill="none" stroke="#DC8A26" strokeWidth="2" />
      <polyline points={line('p50_s')} fill="none" stroke="#2563EB" strokeWidth="2" />
      {stages.map((s, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(s.p95_s)} r="3.5" fill="#DC8A26" />
          <circle cx={x(i)} cy={y(s.p50_s)} r="3.5" fill="#2563EB" />
          <text x={x(i)} y={y(s.p95_s) - 8} fontSize="10" fill="#92500F" textAnchor="middle">{s.p95_s}s</text>
          <text x={x(i)} y={H - PAD + 14} fontSize="11" fill="#374151" textAnchor="middle">{s.concurrency}</text>
          {s.errors > 0 && (
            <text x={x(i)} y={PAD / 2 + 10} fontSize="10" fill="#DC2626" textAnchor="middle">
              {s.errors} Fehler
            </text>
          )}
        </g>
      ))}
      <text x={W / 2} y={H - 6} fontSize="11" fill="#6B7280" textAnchor="middle">gleichzeitige Nutzer</text>
      <text x={12} y={PAD / 2} fontSize="10" fill="#2563EB">p50</text>
      <text x={36} y={PAD / 2} fontSize="10" fill="#DC8A26">p95</text>
    </svg>
  );
}

function ResourceChart({ samples, field, color, unit, label }: {
  samples: ResourceSample[]; field: 'proc_cpu' | 'rss_mb'; color: string; unit: string; label: string;
}) {
  const W = 560, H = 120, PAD = 44;
  if (!samples.length) return null;
  const maxT = Math.max(...samples.map(s => s.t), 1);
  const maxV = Math.max(...samples.map(s => s[field]), 1) * 1.1;
  const pts = samples.map(s =>
    `${PAD + (s.t / maxT) * (W - 2 * PAD)},${H - 22 - (s[field] / maxV) * (H - 40)}`
  ).join(' ');
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ maxWidth: W }}>
      <line x1={PAD} y1={H - 22} x2={W - PAD / 2} y2={H - 22} stroke="#D1D5DB" />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.8" />
      <text x={PAD} y={12} fontSize="10" fill="#374151">{label} — Peak {Math.max(...samples.map(s => s[field])).toFixed(0)} {unit}</text>
      <text x={W - PAD / 2} y={H - 8} fontSize="10" fill="#6B7280" textAnchor="end">{maxT.toFixed(0)}s Laufzeit</text>
    </svg>
  );
}

// ── Hauptkomponente ──────────────────────────────────────────────────

export default function LoadTestView() {
  const [mixOptions, setMixOptions] = useState<MixOption[]>([]);
  const [runs, setRuns] = useState<RunListItem[]>([]);
  const [run, setRun] = useState<LoadTestRun | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);

  // Formular
  const [stagesCsv, setStagesCsv] = useState('1, 2, 4, 8');
  const [reqPerStage, setReqPerStage] = useState(8);
  const [mix, setMix] = useState<Record<string, number>>({ wissen: 2, suche: 2, orientierung: 1, lernpfad: 0 });
  const [threshold, setThreshold] = useState(20);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadRuns = useCallback(async () => {
    try {
      const d = await fetchJson<{ runs: RunListItem[] }>('/api/loadtest/runs');
      setRuns(d.runs);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    fetchJson<{ options: MixOption[] }>('/api/loadtest/mix-options')
      .then(d => setMixOptions(d.options))
      .catch(e => setError(String(e)));
    loadRuns();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [loadRuns]);

  const openRun = useCallback(async (id: string) => {
    try {
      const d = await fetchJson<LoadTestRun>(`/api/loadtest/runs/${id}`);
      setRun(d);
      if (pollRef.current) clearInterval(pollRef.current);
      if (d.status === 'running') {
        pollRef.current = setInterval(async () => {
          try {
            const u = await fetchJson<LoadTestRun>(`/api/loadtest/runs/${id}`);
            setRun(u);
            if (u.status !== 'running' && pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
              loadRuns();
            }
          } catch { /* poll weiter */ }
        }, 2000);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [loadRuns]);

  const parsedStages = stagesCsv.split(',').map(s => parseInt(s.trim(), 10)).filter(n => n > 0);
  const totalRequests = parsedStages.length * reqPerStage;
  const mixSum = Object.values(mix).reduce((a, b) => a + b, 0);

  const startRun = async () => {
    setError('');
    setStarting(true);
    try {
      const d = await fetchJson<{ id: string }>('/api/loadtest/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stages: parsedStages,
          requests_per_stage: reqPerStage,
          mix: Object.fromEntries(Object.entries(mix).filter(([, v]) => v > 0)),
          p95_threshold_s: threshold,
        }),
      });
      await loadRuns();
      await openRun(d.id);
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  };

  const removeRun = async (id: string) => {
    if (!confirm(`Lasttest-Run ${id} löschen?`)) return;
    try {
      await fetchJson(`/api/loadtest/runs/${id}`, { method: 'DELETE' });
      if (run?.id === id) setRun(null);
      await loadRuns();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Lasttest</div>
        <div className="page-subtitle">
          Skalierbarkeits-Selbsttest: gemischte Abfragen mit steigender Parallelität
          gegen die eigene Pipeline — Latenz, Fehler und Ressourcen pro Stufe.
        </div>
      </div>

      {error && (
        <div style={{ background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 6,
          padding: 10, marginBottom: 12, fontSize: 12, color: '#7F1D1D' }}>{error}</div>
      )}

      {/* ── Profil-Formular ── */}
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>Stufen (Parallelität, kommagetrennt)</label>
            <input className="form-input form-input-sm" value={stagesCsv}
              onChange={e => setStagesCsv(e.target.value)} placeholder="1, 2, 4, 8" />
            <div className="form-hint" style={{ fontSize: 11 }}>max. 6 Stufen, je ≤ 32 parallel</div>
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>Requests pro Stufe</label>
            <input className="form-input form-input-sm" type="number" min={1} max={60}
              value={reqPerStage} onChange={e => setReqPerStage(parseInt(e.target.value || '1', 10))} />
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 12 }}>p95-Schwelle „stabil" (Sekunden)</label>
            <input className="form-input form-input-sm" type="number" min={1} max={120}
              value={threshold} onChange={e => setThreshold(parseFloat(e.target.value || '20'))} />
          </div>
        </div>

        <div style={{ marginTop: 12 }}>
          <label className="form-label" style={{ fontSize: 12 }}>Abfrage-Mix (Gewichte 0–10)</label>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 8 }}>
            {mixOptions.map(o => (
              <div key={o.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input className="form-input form-input-sm" type="number" min={0} max={10}
                  style={{ width: 64 }}
                  value={mix[o.key] ?? 0}
                  onChange={e => setMix({ ...mix, [o.key]: parseInt(e.target.value || '0', 10) })} />
                <span style={{ fontSize: 12, color: '#374151' }}>{o.label}</span>
              </div>
            ))}
          </div>
        </div>

        <div style={{
          marginTop: 12, padding: '8px 10px', borderRadius: 6, fontSize: 12,
          background: '#FEF3C7', border: '1px solid #F59E0B', color: '#78350F',
        }}>
          <strong>Achtung Kosten/Last:</strong> Dieser Test feuert <strong>{totalRequests} echte
          Chat-Requests</strong> (LLM + MCP) — Stufen {parsedStages.join(' → ') || '–'} ×
          {' '}{reqPerStage}/Stufe. Lernpfad-Anteile sind am teuersten. Es läuft maximal ein Run gleichzeitig.
        </div>

        <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn btn-primary" onClick={startRun}
            disabled={starting || !parsedStages.length || mixSum === 0 || run?.status === 'running'}>
            {starting ? 'Startet…' : 'Lasttest starten'}
          </button>
          {run?.status === 'running' && (
            <span style={{ fontSize: 12, color: '#92500F' }}>
              Run läuft — Stufe {run.stages.length}/{run.profile.stages.length} abgeschlossen…
            </span>
          )}
        </div>
      </div>

      {/* ── Vergangene Runs ── */}
      <div className="card" style={{ padding: 12, marginBottom: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Runs</div>
        {runs.length === 0 && <div style={{ fontSize: 12, color: '#9CA3AF' }}>Noch keine Lasttests.</div>}
        {runs.map(r => (
          <div key={r.id} style={{ display: 'flex', gap: 10, alignItems: 'center',
            padding: '6px 4px', borderBottom: '1px solid #F3F4F6', fontSize: 12 }}>
            <button className="btn btn-sm" onClick={() => openRun(r.id)}>{r.id}</button>
            <span style={{
              padding: '1px 8px', borderRadius: 10, fontSize: 11,
              background: r.status === 'completed' ? '#D1FAE5' : r.status === 'running' ? '#FEF3C7' : '#FEE2E2',
              color: r.status === 'completed' ? '#065F46' : r.status === 'running' ? '#92500F' : '#7F1D1D',
            }}>{r.status}</span>
            <span style={{ color: '#6B7280' }}>{(r.created_at || '').slice(0, 19).replace('T', ' ')}</span>
            {r.summary && (
              <span style={{ color: '#374151' }}>
                stabil bis <strong>{r.summary.stable_concurrency ?? '–'}</strong> parallel ·{' '}
                {r.summary.total_errors} Fehler · Peak {r.summary.peak_rss_mb.toFixed(0)} MB
              </span>
            )}
            <button className="btn btn-danger btn-sm btn-icon" title="Löschen"
              style={{ marginLeft: 'auto', padding: '2px 6px', fontSize: '.7rem' }}
              onClick={() => removeRun(r.id)}>✕</button>
          </div>
        ))}
      </div>

      {/* ── Auswertung ── */}
      {run && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>Auswertung {run.id}</div>
            <span style={{ fontSize: 12, color: '#6B7280' }}>{run.status}</span>
          </div>

          {run.error && (
            <div style={{ background: '#FEE2E2', border: '1px solid #DC2626', borderRadius: 6,
              padding: 8, marginBottom: 10, fontSize: 12, color: '#7F1D1D' }}>{run.error}</div>
          )}

          {/* Fazit */}
          {run.summary && (
            <div style={{
              background: run.summary.stable_concurrency ? '#ECFDF5' : '#FEF3C7',
              border: `1px solid ${run.summary.stable_concurrency ? '#10B981' : '#F59E0B'}`,
              borderRadius: 6, padding: 10, marginBottom: 14, fontSize: 13,
              color: run.summary.stable_concurrency ? '#065F46' : '#78350F',
            }}>
              {run.summary.stable_concurrency ? (
                <>
                  <strong>Stabil bis {run.summary.stable_concurrency} gleichzeitige Nutzer</strong>{' '}
                  (0 Fehler, p95 ≤ {run.summary.p95_threshold_s}s).{' '}
                </>
              ) : (
                <><strong>Schon die erste Stufe verfehlte die Schwelle</strong> — Profil oder Schwelle prüfen. </>
              )}
              Ressourcen-Peak: {run.summary.peak_rss_mb.toFixed(0)} MB RSS,{' '}
              {run.summary.peak_proc_cpu_pct.toFixed(0)} % Prozess-CPU ·{' '}
              {run.summary.total_requests} Requests, {run.summary.total_errors} Fehler.
              {' '}Hinweis: Die Latenz wird i. d. R. von LLM-/MCP-Antwortzeiten dominiert, nicht von
              lokaler CPU — bleibt die CPU-Kurve flach, während p95 steigt, limitiert das Upstream.
            </div>
          )}

          {/* Latenz-Kurve */}
          {run.stages.length > 0 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 2 }}>
                Antwortlatenz vs. Parallelität
              </div>
              <LatencyChart stages={run.stages} threshold={run.profile.p95_threshold_s} />
            </>
          )}

          {/* Stufen-Tabelle */}
          {run.stages.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 8, marginBottom: 14 }}>
              <table style={{ fontSize: 12 }}>
                <thead>
                  <tr>
                    <th>parallel</th><th>Requests</th><th>OK</th><th>Fehler</th>
                    <th>p50</th><th>p95</th><th>max</th><th>RPS</th><th>Mix-Detail (p95)</th>
                  </tr>
                </thead>
                <tbody>
                  {run.stages.map((s, i) => (
                    <tr key={i}>
                      <td><strong>{s.concurrency}</strong></td>
                      <td>{s.requests}</td>
                      <td>{s.ok}</td>
                      <td style={{ color: s.errors ? '#DC2626' : undefined }}>
                        {s.errors}{s.error_kinds.length ? ` (${s.error_kinds.join(', ')})` : ''}
                      </td>
                      <td>{s.p50_s}s</td>
                      <td>{s.p95_s}s</td>
                      <td>{s.max_s}s</td>
                      <td>{s.rps}</td>
                      <td style={{ color: '#6B7280' }}>
                        {Object.entries(s.by_kind).map(([k, v]) => `${k} ${v.p95_s}s`).join(' · ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Ressourcen-Verlauf */}
          {run.resource_samples.length > 1 && (
            <>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#374151' }}>
                Ressourcen während des Runs (Backend-Prozess)
              </div>
              <ResourceChart samples={run.resource_samples} field="proc_cpu"
                color="#7C3AED" unit="%" label="Prozess-CPU" />
              <ResourceChart samples={run.resource_samples} field="rss_mb"
                color="#0D9488" unit="MB" label="RAM (RSS)" />
            </>
          )}
        </div>
      )}
    </div>
  );
}
