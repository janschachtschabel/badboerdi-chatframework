'use client';

/**
 * RoutingRulesView — Studio page for the generic routing rule engine.
 *
 * Five sub-tabs:
 *   1. Rules — list with priority, when/then, live/shadow status, fire counts
 *   2. Lookup-Tabellen — Welle C.1 lookup groups (compact persona/intent tables)
 *   3. Test-Bench — dry-run engine against a hand-crafted context
 *   4. Stats — agreement rates and disagreement samples (last N days)
 *   5. YAML-Editor — Block 2 (Sprint 6): inline edit of routing-rules.yaml
 *      with hot-reload of the rule engine. Save writes via PUT /api/config/file.
 *
 * Read-only history: Rules/Lookups/Stats remain read-only views of the live
 * state — for editing, go through the YAML-Editor tab.
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

type Tab = 'rules' | 'lookups' | 'test' | 'stats' | 'yaml';

const ROUTING_RULES_PATH = '06-rules/routing-rules.yaml';

/** Welle C.1 (2026-05): Lookup-Gruppe aus routing-rules.yaml.
 *  Eine Lookup-Gruppe wird zur Lade-Zeit zu N einzelnen Rules expandiert
 *  (eine pro ``items``-Eintrag) und im Studio als Tabelle gerendert. */
interface LookupGroup {
  id_prefix: string;
  description?: string;
  priority: number;
  live: boolean;
  when_path: string;
  when_op: string;
  then_field: string;
  when_extra?: Record<string, unknown>;
  then_extra?: Record<string, unknown>;
  items: { key: string; match: string; value: string }[];
}

export default function RoutingRulesView() {
  const [tab, setTab] = useState<Tab>('rules');
  const [rules, setRules] = useState<RuleDef[]>([]);
  const [lookups, setLookups] = useState<LookupGroup[]>([]);
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

  /** Welle C.1: Lädt die Lookup-Gruppen separat (raw YAML-Form,
   *  nicht expandiert). Wird vom 'Lookup-Tabellen'-Tab gerendert. */
  const loadLookups = async () => {
    try {
      const r = await fetch('/api/routing-rules/lookups');
      if (!r.ok) return;
      const data = await r.json();
      setLookups(data.lookups || []);
    } catch {}
  };

  useEffect(() => {
    loadRules();
    loadLookups();
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

  /** Reset all routing-rule stats by deleting the shadow-router log
   *  files that the /stats endpoint reads from. After deletion the
   *  rule-fire counters return to 0 across all tabs.
   *
   *  Accessible from the top-header so users don't have to navigate
   *  to the Stats-tab first to find the reset action.
   */
  const resetStats = async () => {
    if (!confirm(
      'Statistiken zurücksetzen?\n\n' +
      'Damit werden alle Shadow-Router-Log-Dateien gelöscht und ' +
      'die Routing-Rule-Statistiken zeigen wieder 0.\n\n' +
      'Die Routing-Rules selbst bleiben unverändert.',
    )) return;
    setLoading(true);
    try {
      const r = await fetch('/api/routing-rules/stats', { method: 'DELETE' });
      if (!r.ok) {
        alert('Reset fehlgeschlagen: HTTP ' + r.status);
        return;
      }
      const data = await r.json();
      // Direkt UI-State zurücksetzen, damit der User sofort sieht, dass's
      // geklappt hat — ohne Roundtrip-Wartezeit beim nächsten loadStats.
      setStats({});
      setStatsTotalTurns(0);
      await loadStats();  // re-poll für den Fall, dass neue Logs nachgekommen
      alert(`✓ ${data.deleted} Log-Datei(en) gelöscht. Statistiken sind nun auf 0.`);
    } catch (e) {
      alert('Reset fehlgeschlagen: ' + (e instanceof Error ? e.message : String(e)));
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
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={resetStats}
            disabled={loading || statsTotalTurns === 0}
            style={{
              padding: '8px 14px',
              background: '#fff',
              color: '#DC2626',
              border: '1px solid #DC2626',
              borderRadius: 6,
              cursor: loading ? 'wait' : (statsTotalTurns === 0 ? 'not-allowed' : 'pointer'),
              fontSize: 13,
              opacity: statsTotalTurns === 0 ? 0.5 : 1,
            }}
            title={
              statsTotalTurns === 0
                ? 'Keine Statistiken vorhanden — nichts zum Zurücksetzen.'
                : `Stats auf 0 zurücksetzen (löscht alle ${statsTotalTurns} geloggten Turns).`
            }
          >
            🗑 Stats zurücksetzen
          </button>
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
      </div>

      {/* Tab nav */}
      <div style={{ display: 'flex', gap: 4, borderBottom: '1px solid #E5E7EB', marginBottom: 16 }}>
        {([
          { id: 'rules', label: 'Regeln' },
          { id: 'lookups', label: `Lookup-Tabellen${lookups.length ? ` (${lookups.length})` : ''}` },
          { id: 'test', label: 'Test-Bench' },
          { id: 'stats', label: 'Statistiken' },
          { id: 'yaml', label: '📝 YAML-Editor' },
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
      {tab === 'lookups' && <LookupTablesView lookups={lookups} />}
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
      {tab === 'yaml' && (
        <YamlEditor
          onAfterSave={async () => {
            // After saving + backend reload, refresh the rules list so the
            // Studio's other tabs reflect the new YAML state immediately.
            await fetch('/api/routing-rules/reload', { method: 'POST' });
            await loadRules();
            await loadLookups();
          }}
        />
      )}
    </div>
  );
}

/* ── YAML editor sub-component (Block 2 — Sprint 6) ─────────────────
 * Originally the rules editor was read-only by design ("Edits go through
 * Git/YAML"). With this editor the Studio user can now edit the entire
 * routing-rules.yaml in-browser. Saves go via PUT /api/config/file —
 * the same persistence path PatternEditor uses — and then the backend
 * routing-rules engine is reloaded so the changes take effect immediately.
 *
 * No client-side YAML validation: the backend will surface YAML-parse
 * errors on save. Dirty-flag is tracked so accidental tab-switches
 * don't lose unsaved edits.
 */
function YamlEditor({ onAfterSave }: { onAfterSave: () => Promise<void> }) {
  const [content, setContent] = useState('');
  const [originalContent, setOriginalContent] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<'idle' | 'saved' | 'error'>('idle');
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  const dirty = content !== originalContent;

  const load = async () => {
    setLoading(true);
    setErrorDetail(null);
    try {
      const r = await fetch(`/api/config/file?path=${encodeURIComponent(ROUTING_RULES_PATH)}`);
      if (!r.ok) {
        setErrorDetail(`Konnte Datei nicht laden: HTTP ${r.status}`);
        return;
      }
      const data = await r.json();
      setContent(data.content || '');
      setOriginalContent(data.content || '');
    } catch (e: unknown) {
      setErrorDetail(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    setErrorDetail(null);
    setStatus('idle');
    try {
      const r = await fetch('/api/config/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: ROUTING_RULES_PATH, content, file_type: 'yaml' }),
      });
      if (!r.ok) {
        const txt = await r.text();
        setErrorDetail(`Speichern fehlgeschlagen: HTTP ${r.status} — ${txt.slice(0, 200)}`);
        setStatus('error');
        return;
      }
      setOriginalContent(content);
      setStatus('saved');
      await onAfterSave();
      setTimeout(() => setStatus('idle'), 2500);
    } catch (e: unknown) {
      setErrorDetail(e instanceof Error ? e.message : String(e));
      setStatus('error');
    } finally {
      setSaving(false);
    }
  };

  const revert = () => {
    if (!dirty) return;
    if (!confirm('Lokale Änderungen verwerfen und vom Backend neu laden?')) return;
    setContent(originalContent);
    setStatus('idle');
  };

  const lines = content.split('\n').length;

  return (
    <div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 12, gap: 12, flexWrap: 'wrap',
      }}>
        <div style={{ fontSize: 13, color: '#6B7280' }}>
          Datei: <code style={{ background: '#F3F4F6', padding: '2px 6px', borderRadius: 4 }}>{ROUTING_RULES_PATH}</code>
          <span style={{ marginLeft: 12 }}>{lines} Zeilen · {content.length.toLocaleString('de-DE')} Zeichen</span>
          {dirty && <span style={{ marginLeft: 12, color: '#D97706', fontWeight: 600 }}>● ungesicherte Änderungen</span>}
          {status === 'saved' && <span style={{ marginLeft: 12, color: '#059669', fontWeight: 600 }}>✓ gespeichert + Rules neu geladen</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={revert}
            disabled={!dirty || saving}
            style={{
              padding: '8px 14px',
              background: '#fff',
              color: '#6B7280',
              border: '1px solid #D1D5DB',
              borderRadius: 6,
              cursor: dirty && !saving ? 'pointer' : 'not-allowed',
              fontSize: 13,
              opacity: dirty ? 1 : 0.5,
            }}
            title="Lokale Änderungen verwerfen"
          >
            ↺ Verwerfen
          </button>
          <button
            onClick={save}
            disabled={!dirty || saving}
            style={{
              padding: '8px 14px',
              background: dirty ? '#3B82F6' : '#E5E7EB',
              color: dirty ? '#fff' : '#6B7280',
              border: 'none',
              borderRadius: 6,
              cursor: dirty && !saving ? 'pointer' : 'not-allowed',
              fontSize: 13,
              fontWeight: 600,
            }}
            title="YAML speichern und Routing-Rules-Engine neu laden"
          >
            {saving ? 'Speichert …' : '💾 Speichern & Reload'}
          </button>
        </div>
      </div>

      {errorDetail && (
        <div style={{
          background: '#FEE2E2', color: '#991B1B', border: '1px solid #FCA5A5',
          padding: '8px 12px', borderRadius: 6, marginBottom: 12, fontSize: 13,
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        }}>
          ⚠️ {errorDetail}
        </div>
      )}

      {loading ? (
        <div style={{ padding: 20, color: '#6B7280' }}>Lädt YAML …</div>
      ) : (
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          spellCheck={false}
          style={{
            width: '100%',
            minHeight: 580,
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
            fontSize: 12.5,
            lineHeight: 1.55,
            padding: 12,
            border: '1px solid #D1D5DB',
            borderRadius: 6,
            tabSize: 2,
            whiteSpace: 'pre',
            resize: 'vertical',
          }}
          onKeyDown={(e) => {
            // Tab inserts 2 spaces (consistent with YAML convention)
            if (e.key === 'Tab' && !e.shiftKey) {
              e.preventDefault();
              const t = e.currentTarget;
              const s = t.selectionStart, en = t.selectionEnd;
              const next = content.slice(0, s) + '  ' + content.slice(en);
              setContent(next);
              // restore caret one tick later (after state flush)
              requestAnimationFrame(() => {
                t.selectionStart = t.selectionEnd = s + 2;
              });
            }
          }}
        />
      )}

      <div style={{ marginTop: 10, fontSize: 11, color: '#6B7280', lineHeight: 1.55 }}>
        <strong>Hinweis:</strong> Speichern schreibt direkt nach <code>{ROUTING_RULES_PATH}</code> und lädt die
        Routing-Rules-Engine neu — Live-Wirkung. YAML-Syntaxfehler werden vom Backend beim Reload abgefangen
        und in einem Banner angezeigt. Tab-Taste fügt 2 Leerzeichen ein. Größere Strukturänderungen
        bitte vorher per Snapshot sichern.
      </div>
    </div>
  );
}

/** Welle C.1 (2026-05): Lookup-Tabellen-View.
 *  Zeigt die ``lookups:``-Blöcke aus routing-rules.yaml als pflegbare
 *  Tabellen — eine pro Lookup-Group, mit Spalten key | match | value.
 *  Das ersetzt die alte Anzeige von 8-fach fast-identischen Rules
 *  (R-PSI-1…8 etc.) durch eine kompakte Tabellen-Form.
 *
 *  Aktuell read-only (Editor folgt in Welle C.5b — Form-UI für Add/
 *  Update/Delete von Items + persistente Speicherung via PUT).
 */
function LookupTablesView({ lookups }: { lookups: LookupGroup[] }) {
  if (!lookups || lookups.length === 0) {
    return (
      <div style={{ padding: 20, color: '#6B7280', fontStyle: 'italic' }}>
        Keine Lookup-Tabellen in routing-rules.yaml definiert.
        Eine Lookup-Tabelle fasst strukturell identische Rules
        (z.B. Persona-Self-ID-Regexe) zu einer pflegbaren Tabelle zusammen.
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{
        background: '#FEF3C7', border: '1px solid #FCD34D',
        borderRadius: 6, padding: '10px 14px', fontSize: 13, color: '#78350F',
      }}>
        <strong>Hinweis:</strong> Lookup-Tabellen werden beim YAML-Laden
        zu N einzelnen Routing-Rules expandiert (eine pro Item-Zeile).
        Sie verhalten sich semantisch identisch zu manuell geschriebenen
        Rules. Aktuell read-only — Editing folgt in einer späteren Welle.
      </div>
      {lookups.map((g) => (
        <div key={g.id_prefix} style={{
          border: '1px solid #E5E7EB', borderRadius: 8, overflow: 'hidden',
        }}>
          <div style={{
            background: '#F9FAFB', padding: '10px 16px',
            borderBottom: '1px solid #E5E7EB',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <code style={{
                background: '#E0E7FF', color: '#3730A3',
                padding: '2px 8px', borderRadius: 4, fontSize: 13,
              }}>
                {g.id_prefix}
              </code>
              <span style={{
                background: g.live ? '#D1FAE5' : '#FEE2E2',
                color: g.live ? '#065F46' : '#7F1D1D',
                padding: '2px 8px', borderRadius: 4, fontSize: 11,
              }}>
                {g.live ? 'LIVE' : 'SHADOW'}
              </span>
              <span style={{ color: '#6B7280', fontSize: 12 }}>
                Priorität {g.priority} · {g.items.length} Items
              </span>
            </div>
            {g.description && (
              <p style={{ margin: '6px 0 0', fontSize: 13, color: '#4B5563' }}>
                {g.description}
              </p>
            )}
            <div style={{ marginTop: 6, fontSize: 11, color: '#6B7280' }}>
              <code style={{ background: '#F3F4F6', padding: '0 4px', borderRadius: 2 }}>
                {g.when_path}
              </code>
              {' '}
              <code style={{ background: '#F3F4F6', padding: '0 4px', borderRadius: 2 }}>
                {g.when_op}
              </code>
              {' → '}
              <code style={{ background: '#F3F4F6', padding: '0 4px', borderRadius: 2 }}>
                {g.then_field}
              </code>
              {g.when_extra && Object.keys(g.when_extra).length > 0 && (
                <span style={{ marginLeft: 8 }}>
                  +Bedingung:
                  {' '}
                  <code style={{ background: '#F3F4F6', padding: '0 4px', borderRadius: 2 }}>
                    {JSON.stringify(g.when_extra)}
                  </code>
                </span>
              )}
            </div>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#F9FAFB', color: '#6B7280' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #E5E7EB', width: '15%' }}>Key</th>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #E5E7EB', width: '60%' }}>Match ({g.when_op})</th>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #E5E7EB', width: '25%' }}>{g.then_field}</th>
              </tr>
            </thead>
            <tbody>
              {g.items.map((item, idx) => (
                <tr key={item.key || idx} style={{
                  background: idx % 2 ? '#FAFAFA' : '#fff',
                }}>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid #F3F4F6' }}>
                    <code style={{ background: '#F3F4F6', padding: '1px 6px', borderRadius: 3, fontSize: 12 }}>
                      {item.key}
                    </code>
                  </td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid #F3F4F6', fontFamily: 'monospace', fontSize: 11.5, color: '#4B5563', wordBreak: 'break-all' }}>
                    {item.match}
                  </td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid #F3F4F6' }}>
                    <code style={{ background: '#DBEAFE', color: '#1E40AF', padding: '1px 6px', borderRadius: 3, fontSize: 12 }}>
                      {item.value}
                    </code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
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
  const [intent, setIntent] = useState('INT-W-03');
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
