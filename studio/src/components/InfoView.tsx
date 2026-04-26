'use client';

import { useState, useEffect } from 'react';

/* ── Styling helpers ───────────────────────────────────────────────── */
const sectionStyle: React.CSSProperties = { marginBottom: 28 };
const h3Style: React.CSSProperties = { fontSize: 16, fontWeight: 700, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8 };
const pStyle: React.CSSProperties = { fontSize: 13, lineHeight: 1.7, color: 'var(--text)', marginBottom: 8 };
const mutedStyle: React.CSSProperties = { fontSize: 12, color: 'var(--text-muted)' };
const tableStyle: React.CSSProperties = { width: '100%', fontSize: 12, borderCollapse: 'collapse' };
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '6px 10px', background: '#f3f4f6', fontWeight: 600, borderBottom: '1px solid var(--border)' };
const tdStyle: React.CSSProperties = { padding: '6px 10px', borderBottom: '1px solid var(--border)', verticalAlign: 'top' };
const codeStyle: React.CSSProperties = { fontFamily: 'var(--font-mono, monospace)', fontSize: 11, background: '#f3f4f6', padding: '2px 6px', borderRadius: 4 };
const arrowBox: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20, color: 'var(--text-muted)', padding: '4px 0' };

/* ── Mini flow arrow ───────────────────────────────────────────────── */
function FlowArrow() {
  return <div style={arrowBox}>↓</div>;
}

/* ── Collapsible section ───────────────────────────────────────────── */
function Section({ title, icon, children, defaultOpen = false }: { title: string; icon: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="card" style={{ marginBottom: 12 }}>
      <button
        onClick={() => setOpen(!open)}
        style={{ all: 'unset', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '4px 0' }}
      >
        <span style={{ fontSize: 18 }}>{icon}</span>
        <span style={{ fontSize: 15, fontWeight: 600, flex: 1 }}>{title}</span>
        <span style={{ fontSize: 14, color: 'var(--text-muted)', transition: 'transform .2s', transform: open ? 'rotate(180deg)' : 'rotate(0)' }}>▼</span>
      </button>
      {open && <div style={{ marginTop: 12 }}>{children}</div>}
    </div>
  );
}

/* ── Live system info card ─────────────────────────────────────────── */
interface SystemInfo {
  health: { status?: string; provider?: string; chat_model?: string; embed_model?: string } | null;
  factory: { exists: boolean; size?: number; mtime?: number; has_db?: boolean; config_files?: number } | null;
  rules: { rule_count: number; live_count: number; shadow_count: number } | null;
  snapshotCount: number | null;
}

function fmtBytes(n: number | undefined): string {
  if (!n) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function fmtRel(mtimeSec: number | undefined): string {
  if (!mtimeSec) return '—';
  const ageSec = Date.now() / 1000 - mtimeSec;
  if (ageSec < 60) return 'gerade eben';
  if (ageSec < 3600) return `vor ${Math.floor(ageSec / 60)} Min`;
  if (ageSec < 86400) return `vor ${Math.floor(ageSec / 3600)} h`;
  if (ageSec < 86400 * 30) return `vor ${Math.floor(ageSec / 86400)} Tagen`;
  return `vor ${Math.floor(ageSec / 86400 / 30)} Mon`;
}

function SystemStatus() {
  const [info, setInfo] = useState<SystemInfo>({ health: null, factory: null, rules: null, snapshotCount: null });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [h, f, r, s] = await Promise.allSettled([
        fetch('/api/health').then(r => r.json()),
        fetch('/api/config/factory').then(r => r.json()),
        fetch('/api/routing-rules').then(r => r.json()),
        fetch('/api/config/snapshots').then(r => r.json()),
      ]);
      if (cancelled) return;
      setInfo({
        health: h.status === 'fulfilled' ? h.value : null,
        factory: f.status === 'fulfilled' ? f.value : null,
        rules: r.status === 'fulfilled' ? {
          rule_count: r.value.total ?? 0,
          live_count: r.value.live_count ?? 0,
          shadow_count: r.value.shadow_count ?? 0,
        } : null,
        snapshotCount: s.status === 'fulfilled' && Array.isArray(s.value) ? s.value.length : null,
      });
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="card" style={{ marginBottom: 16, background: '#F0F9FF', borderColor: '#BAE6FD' }}>
      <div style={{ ...h3Style, marginBottom: 12 }}>📊 System-Stand (live)</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, fontSize: 12 }}>
        <div>
          <div style={{ fontWeight: 700, color: '#0369A1', marginBottom: 4 }}>Backend</div>
          <div style={{ color: 'var(--text-muted)' }}>Status: <strong style={{ color: info.health?.status === 'ok' ? '#10B981' : '#EF4444' }}>{info.health?.status ?? '—'}</strong></div>
          <div style={{ color: 'var(--text-muted)' }}>Provider: <code style={codeStyle}>{info.health?.provider ?? '—'}</code></div>
          <div style={{ color: 'var(--text-muted)' }}>Chat-Modell: <code style={codeStyle}>{info.health?.chat_model ?? '—'}</code></div>
          <div style={{ color: 'var(--text-muted)' }}>Embed-Modell: <code style={codeStyle}>{info.health?.embed_model ?? '—'}</code></div>
        </div>
        <div>
          <div style={{ fontWeight: 700, color: '#0369A1', marginBottom: 4 }}>Werkseinstellungen</div>
          <div style={{ color: 'var(--text-muted)' }}>Vorhanden: <strong>{info.factory?.exists ? 'ja' : 'nein'}</strong></div>
          <div style={{ color: 'var(--text-muted)' }}>Alter: {fmtRel(info.factory?.mtime)}</div>
          <div style={{ color: 'var(--text-muted)' }}>Größe: {fmtBytes(info.factory?.size)}</div>
          <div style={{ color: 'var(--text-muted)' }}>{info.factory?.config_files ?? 0} Configs · {info.factory?.has_db ? 'mit DB' : 'ohne DB'}</div>
        </div>
        <div>
          <div style={{ fontWeight: 700, color: '#0369A1', marginBottom: 4 }}>Routing-Engine</div>
          <div style={{ color: 'var(--text-muted)' }}>Total: <strong>{info.rules?.rule_count ?? '—'}</strong> Regeln</div>
          <div style={{ color: 'var(--text-muted)' }}>Live: <strong style={{ color: '#10B981' }}>{info.rules?.live_count ?? '—'}</strong></div>
          <div style={{ color: 'var(--text-muted)' }}>Shadow: <strong style={{ color: '#94A3B8' }}>{info.rules?.shadow_count ?? '—'}</strong></div>
        </div>
        <div>
          <div style={{ fontWeight: 700, color: '#0369A1', marginBottom: 4 }}>User-Snapshots</div>
          <div style={{ color: 'var(--text-muted)' }}>Anzahl: <strong>{info.snapshotCount ?? '—'}</strong></div>
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            Verwaltung über das 📦-Symbol oben rechts
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main Component ────────────────────────────────────────────────── */
export default function InfoView() {
  return (
    <div>
      <h2 className="card-title" style={{ marginBottom: 4 }}>ℹ️ Architektur-Referenz</h2>
      <p style={{ ...mutedStyle, marginBottom: 20 }}>Wie die Elemente zusammenspielen — vom Nutzer-Input bis zur Bot-Antwort.</p>

      <SystemStatus />

      {/* ═══════════════ PIPELINE OVERVIEW ═══════════════ */}
      <Section title="Die Verarbeitungs-Pipeline" icon="⚡" defaultOpen={true}>
        <p style={pStyle}>
          Jede Nutzernachricht durchläuft <strong>7 Phasen</strong>. Die Architektur ist so aufgebaut, dass deterministische Regeln (Patterns, Gates, Signale) den LLM gezielt steuern — nicht umgekehrt.
        </p>
        <div className="card" style={{ background: '#f8fafc', padding: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {[
              { step: '1', label: 'Safety-Check', desc: 'Regex, Moderation, Legal-Classifier prüfen die Nachricht', color: '#ef4444' },
              { step: '2', label: 'Klassifikation (LLM)', desc: 'Persona, Intent, Signals, Entities, State, Turn-Type erkennen', color: '#3b82f6' },
              { step: '3a', label: 'Pre-Route Engine', desc: 'YAML-Regeln korrigieren Persona/Intent/State (z.B. explizite Self-IDs, low-confidence-Fallback)', color: '#0EA5E9' },
              { step: '3b', label: 'Policy-Prüfung', desc: 'Tool-Blockaden & Disclaimers anhand von Persona+Intent', color: '#f59e0b' },
              { step: '4', label: 'Pattern-Engine (3 Phasen)', desc: 'Gate → Score → Modulate — wählt das beste Gesprächsmuster', color: '#8b5cf6' },
              { step: '4b', label: 'Post-Route Engine', desc: 'YAML-Regeln können Pattern überschreiben (Tiebreaker, intent-spezifische Patterns)', color: '#0EA5E9' },
              { step: '5', label: 'Prompt-Zusammensetzung', desc: '5 Schichten werden zum System-Prompt kombiniert', color: '#2B6CB0' },
              { step: '6', label: 'LLM-Aufruf + MCP-Tools', desc: 'LLM antwortet, ruft bei Bedarf externe Tools auf', color: '#10b981' },
              { step: '7', label: 'Nachbereitung', desc: 'Karten extrahieren, Quality-Log schreiben, State speichern', color: '#6b7280' },
            ].map((phase, i) => (
              <div key={phase.step}>
                {i > 0 && <FlowArrow />}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span style={{ width: 28, height: 28, borderRadius: '50%', background: phase.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, flexShrink: 0 }}>{phase.step}</span>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>{phase.label}</div>
                    <div style={mutedStyle}>{phase.desc}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </Section>

      {/* ═══════════════ INPUT ELEMENTS ═══════════════ */}
      <Section title="Input-Elemente (Klassifikation)" icon="📥">
        <p style={pStyle}>
          In Phase 2 erkennt ein LLM-Call aus der Nutzernachricht 6 Dimensionen. Diese Input-Elemente steuern alles Weitere:
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Element</th>
              <th style={thStyle}>Anzahl</th>
              <th style={thStyle}>Beschreibung</th>
              <th style={thStyle}>Wirkung</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={tdStyle}><strong>Persona</strong></td>
              <td style={tdStyle}>9</td>
              <td style={tdStyle}>Wer spricht? (Lehrkraft, Schüler, Eltern, Presse…)</td>
              <td style={tdStyle}>Anrede (Sie/du), Pattern-Gate, Policy-Regeln, Tool-Zugang</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Intent</strong></td>
              <td style={tdStyle}>14</td>
              <td style={tdStyle}>Was will der Nutzer? (Material suchen, Fakten, Inhalt erstellen, Canvas-Edit, Feedback…)</td>
              <td style={tdStyle}>Pattern-Gate, MCP-Tool-Präferenz, spekulative Vorab-Abfragen, Canvas-Routing</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Signals</strong></td>
              <td style={tdStyle}>17</td>
              <td style={tdStyle}>Emotionale/situative Hinweise in 4 Dimensionen</td>
              <td style={tdStyle}>Modulieren Ton, Länge, skip_intro — überschreiben Pattern-Defaults</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Entities</strong></td>
              <td style={tdStyle}>5 Slots</td>
              <td style={tdStyle}>Extrahierte Parameter: Fach, Stufe, Thema, Medientyp, Lizenz</td>
              <td style={tdStyle}>MCP-Suchparameter, Pattern-Preconditions, Entity-Memory über Turns</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>State</strong></td>
              <td style={tdStyle}>12</td>
              <td style={tdStyle}>Gesprächszustand: Orientierung → Suche → Kuratierung → Feedback → Canvas-Arbeit</td>
              <td style={tdStyle}>Pattern-Gate, zustandsabhängiges Verhalten</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Turn-Type</strong></td>
              <td style={tdStyle}>5</td>
              <td style={tdStyle}>Art des Turns: initial, follow_up, clarification, correction, topic_switch</td>
              <td style={tdStyle}>Entity-Akkumulationsregeln (behalten, ergänzen, überschreiben, zurücksetzen)</td>
            </tr>
          </tbody>
        </table>
      </Section>

      {/* ═══════════════ PATTERN ENGINE ═══════════════ */}
      <Section title="Pattern-Engine (3 Phasen)" icon="🧩">
        <p style={pStyle}>
          Die Pattern-Engine wählt aus 26 Gesprächsmustern <strong>genau eines</strong> aus. Nur das Gewinner-Pattern wird in den Prompt eingefügt.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ borderTop: '3px solid #ef4444' }}>
            <div style={h3Style}>Phase 1: Gate</div>
            <p style={pStyle}>
              <strong>Eliminierung</strong> — Patterns werden entfernt, wenn Persona, Intent oder State nicht zu den <code style={codeStyle}>gate_*</code>-Listen passen. Hard Gate: fehlende <code style={codeStyle}>precondition_slots</code> eliminieren ebenfalls.
            </p>
            <p style={mutedStyle}>Ergebnis: Kandidatenliste (oft 10-16 von 26)</p>
          </div>
          <div className="card" style={{ borderTop: '3px solid #f59e0b' }}>
            <div style={h3Style}>Phase 2: Score</div>
            <p style={pStyle}>
              <strong>Gewichtung</strong> — Verbleibende Patterns werden nach Signal-Fit bewertet: <code style={codeStyle}>high_fit</code> = 1.0, <code style={codeStyle}>medium_fit</code> = 0.5, <code style={codeStyle}>low_fit</code> = 0.2. Dazu: Page-Bonus und Entity-Vollständigkeit.
            </p>
            <p style={mutedStyle}>Ergebnis: Gewinner-Pattern + Score-Gap zum Zweitplatzierten</p>
          </div>
          <div className="card" style={{ borderTop: '3px solid #10b981' }}>
            <div style={h3Style}>Phase 3: Modulate</div>
            <p style={pStyle}>
              <strong>Anpassung</strong> — Die Defaults des Gewinners (Ton, Länge, Detail…) werden durch aktive Signale überschrieben. Kürzere Länge gewinnt bei Konflikten.
            </p>
            <p style={mutedStyle}>Ergebnis: 19 finale Steuerungsfelder für den Prompt</p>
          </div>
        </div>

        <div style={h3Style}>Die 19 Modulations-Felder (Output)</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>Stil & Inhalt</div>
            <table style={tableStyle}>
              <tbody>
                {[
                  ['tone', 'Ton der Antwort (sachlich, empathisch, spielerisch…)'],
                  ['formality', 'Formalitätsgrad'],
                  ['length', 'Antwortlänge (kurz, mittel, lang)'],
                  ['detail_level', 'Detailgrad (standard, ausfuehrlich)'],
                  ['response_type', 'Antworttyp (answer, question, redirect…)'],
                  ['format_primary', 'Primärformat (text, list, cards…)'],
                  ['format_follow_up', 'Follow-up-Format'],
                  ['sources', 'Wissensquellen (mcp, rag, oder leer)'],
                ].map(([field, desc]) => (
                  <tr key={field}>
                    <td style={{ ...tdStyle, width: 140 }}><code style={codeStyle}>{field}</code></td>
                    <td style={tdStyle}>{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>Steuerung & Flags</div>
            <table style={tableStyle}>
              <tbody>
                {[
                  ['max_items', 'Max. Ergebniskarten'],
                  ['card_text_mode', 'Kartentext (minimal, detailed)'],
                  ['tools', 'Erzwungene MCP-Tools'],
                  ['rag_areas', 'RAG-Wissensbereiche'],
                  ['core_rule', 'Kern-Anweisung für den LLM'],
                  ['skip_intro', 'Einleitung weglassen'],
                  ['one_option', 'Nur einen Vorschlag zeigen'],
                  ['add_sources', 'Quellenangaben erzwingen'],
                  ['degradation', 'Degradation aktiv?'],
                  ['missing_slots', 'Fehlende Precondition-Slots'],
                  ['blocked_patterns', 'Eliminierte Pattern-IDs'],
                ].map(([field, desc]) => (
                  <tr key={field}>
                    <td style={{ ...tdStyle, width: 140 }}><code style={codeStyle}>{field}</code></td>
                    <td style={tdStyle}>{desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      {/* ═══════════════ ROUTING-RULES ENGINE ═══════════════ */}
      <Section title="Routing-Rules Engine (deklarativ)" icon="⚙️">
        <p style={pStyle}>
          Über der Pattern-Engine läuft eine zweite, vollständig <strong>YAML-getriebene</strong> Regel-Engine.
          Sie hat zwei Funktionen:
        </p>
        <ol style={{ ...pStyle, paddingLeft: 20 }}>
          <li>
            <strong>Pre-Route</strong> — vor der Pattern-Auswahl: korrigiert Persona, Intent
            oder State des Classifiers (z.B. explizite Self-IDs wie &quot;ich bin Lehrerin&quot;
            oder Confidence-basierte Fallbacks).
          </li>
          <li>
            <strong>Post-Route</strong> — nach der Pattern-Auswahl: kann Tiebreaker bei knappen
            Score-Differenzen anwenden oder intent-spezifische Patterns (PAT-22/23/24)
            durchsetzen, die sonst von Universal-Patterns überstimmt würden.
          </li>
        </ol>
        <p style={pStyle}>
          Eine Regel hat <code style={codeStyle}>when</code> (Bedingungen) und <code style={codeStyle}>then</code> (Effekte).
          Beispiel:
        </p>
        <pre style={{ background: '#0F172A', color: '#E2E8F0', padding: 12, borderRadius: 6, fontSize: 12, overflowX: 'auto' }}>
{`- id: rule_personal_data_request
  description: "Pers. Datenfragen → PAT-03"
  priority: 60
  live: true
  when:
    all:
      - intent: { in: ["INT-W-09", "INT-W-08"] }
      - message: { regex: "\\\\bmein\\\\s+(sohn|tochter|kind)\\\\b" }
  then:
    enforced_pattern_id: "PAT-03"`}
        </pre>
        <p style={pStyle}>
          <strong>Live vs Shadow:</strong> Jede Regel hat ein <code style={codeStyle}>live</code>-Flag.
          <code style={codeStyle}>true</code> = wirkt sofort, <code style={codeStyle}>false</code> = nur in
          Shadow-Log gemessen. Das ermöglicht kontrollierte Rollouts neuer Regeln ohne Risiko.
        </p>
        <p style={pStyle}>
          <strong>Verfügbare Komparatoren:</strong> <code style={codeStyle}>eq, neq, in, not_in, regex,
          not_regex, empty, non_empty, exists, lt, gt, lte, gte</code> + boolesche Kombinatoren <code style={codeStyle}>all, any, not</code>.
        </p>
        <p style={pStyle}>
          Direkter Zugang: <strong>Routing Rules</strong> in der Sidebar. Dort sind alle Regeln auflistbar,
          via Test-Bench ausführbar (kein LLM-Aufruf, sub-millisekunden), und es gibt Statistiken über
          Fire-Counts und Override-Rates pro Regel.
        </p>
      </Section>

      {/* ═══════════════ GATES ═══════════════ */}
      <Section title="Gates — Wer darf was?" icon="🚧">
        <p style={pStyle}>
          Gates sind Filter, die bestimmte Patterns eliminieren, <strong>bevor</strong> das Scoring stattfindet. Es gibt 4 Gate-Typen:
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Gate</th>
              <th style={thStyle}>Feld im Pattern</th>
              <th style={thStyle}>Logik</th>
              <th style={thStyle}>Beispiel</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={tdStyle}><strong>Persona-Gate</strong></td>
              <td style={tdStyle}><code style={codeStyle}>gate_personas</code></td>
              <td style={tdStyle}><code style={codeStyle}>["*"]</code> = alle erlaubt, oder explizite Liste</td>
              <td style={tdStyle}>PAT-09 nur für <code style={codeStyle}>["P-W-RED"]</code> (Redaktion)</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Intent-Gate</strong></td>
              <td style={tdStyle}><code style={codeStyle}>gate_intents</code></td>
              <td style={tdStyle}><code style={codeStyle}>["*"]</code> = alle, oder explizite Liste</td>
              <td style={tdStyle}>PAT-21 nur für <code style={codeStyle}>["INT-W-11"]</code> (Canvas-Create); PAT-15 für <code style={codeStyle}>["INT-W-01","INT-W-06","INT-W-09"]</code> (Analyse)</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>State-Gate</strong></td>
              <td style={tdStyle}><code style={codeStyle}>gate_states</code></td>
              <td style={tdStyle}><code style={codeStyle}>["*"]</code> = alle, oder explizite Liste</td>
              <td style={tdStyle}>PAT-07 nur in <code style={codeStyle}>["state-5", "state-6"]</code></td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Slot-Gate (Hard)</strong></td>
              <td style={tdStyle}><code style={codeStyle}>precondition_slots</code></td>
              <td style={tdStyle}>Alle Slots müssen gefüllt sein, sonst eliminiert</td>
              <td style={tdStyle}>PAT-19 braucht <code style={codeStyle}>["fach", "stufe", "thema"]</code></td>
            </tr>
          </tbody>
        </table>
        <p style={{ ...pStyle, marginTop: 12 }}>
          <strong>Wichtig:</strong> Gates eliminieren — sie reduzieren nicht den Score. Ein Pattern, das am Gate scheitert, kann nicht gewinnen, egal wie gut die Signale passen.
        </p>
      </Section>

      {/* ═══════════════ 6 LAYERS ═══════════════ */}
      <Section title="Die 6 Architektur-Schichten" icon="🏗️">
        <p style={pStyle}>
          Der System-Prompt wird aus mehreren Schichten zusammengesetzt. Jede Schicht hat eine Priorität — bei Token-Knappheit werden niedrig-priorisierte Schichten zuerst entladen. Schicht 5 (Canvas-Formate) steuert Ausgabe-Formate und wird nur bei Create-/Edit-Intents geladen.
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Schicht</th>
              <th style={thStyle}>Priorität</th>
              <th style={thStyle}>Inhalt</th>
              <th style={thStyle}>Token-Verhalten</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={tdStyle}><strong>1 — Identität & Schutz</strong></td>
              <td style={tdStyle}><span style={{ color: '#ef4444', fontWeight: 700 }}>1000</span></td>
              <td style={tdStyle}>Persona-Definition, Guardrails, Safety-Config, Geräte-Config</td>
              <td style={tdStyle}>Wird <strong>nie</strong> entladen. Guardrails stehen immer am Ende.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>2 — Domain & Regeln</strong></td>
              <td style={tdStyle}><span style={{ color: '#f59e0b', fontWeight: 700 }}>900</span></td>
              <td style={tdStyle}>Plattform-Regeln, Policy, WLO-Fachwissen</td>
              <td style={tdStyle}>Wird <strong>nie</strong> entladen.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>3 — Patterns</strong></td>
              <td style={tdStyle}><span style={{ color: '#8b5cf6', fontWeight: 700 }}>500-800</span></td>
              <td style={tdStyle}>Das gewählte Gesprächsmuster (nur 1 von 26)</td>
              <td style={tdStyle}>Kann auf PAT-06 (Degradation) zurückfallen.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>4 — Dimensionen</strong></td>
              <td style={tdStyle}><span style={{ color: '#3b82f6', fontWeight: 700 }}>300-600</span></td>
              <td style={tdStyle}>Nur erkannte Persona + aktiver Intent + Signale (nicht alle)</td>
              <td style={tdStyle}>Kann teilweise entladen werden.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>5 — Canvas-Formate</strong></td>
              <td style={tdStyle}><span style={{ color: '#ec4899', fontWeight: 700 }}>200-400</span></td>
              <td style={tdStyle}>Struktur-Vorgabe des gewählten Material-Typs, Alias-Mapping, Edit-/Create-Trigger</td>
              <td style={tdStyle}>Nur bei INT-W-11/12 (Create/Edit) geladen — sonst nicht im Prompt.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>6 — Wissen</strong></td>
              <td style={tdStyle}><span style={{ color: '#10b981', fontWeight: 700 }}>100-200</span></td>
              <td style={tdStyle}>RAG-Kontext (always-on + on-demand), MCP-Tools</td>
              <td style={tdStyle}>Wird als <strong>erstes</strong> entladen.</td>
            </tr>
          </tbody>
        </table>

        <div className="card" style={{ background: '#f8fafc', marginTop: 16, padding: 16, fontSize: 12, fontFamily: 'var(--font-mono, monospace)', lineHeight: 1.8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, fontFamily: 'inherit' }}>Prompt-Aufbau zur Laufzeit:</div>
          <div>┌─ Schicht 1: base-persona.md <span style={{ color: 'var(--text-muted)' }}>← immer</span></div>
          <div>├─ Schicht 2: domain-rules.md + Plattform-Wissen <span style={{ color: 'var(--text-muted)' }}>← immer</span></div>
          <div>├─ Schicht 4: Persona-Prompt + Intent + Signale <span style={{ color: 'var(--text-muted)' }}>← nur erkannte</span></div>
          <div>├─ Schicht 3: Pattern-Block <span style={{ color: 'var(--text-muted)' }}>← nur der Gewinner</span></div>
          <div>├─ Schicht 5: Canvas-Material-Struktur <span style={{ color: 'var(--text-muted)' }}>← nur bei INT-W-11/12</span></div>
          <div>├─ Schicht 6: RAG-Kontext <span style={{ color: 'var(--text-muted)' }}>← always-on Areas</span></div>
          <div>├─ Aktuelle Themenseite <span style={{ color: 'var(--text-muted)' }}>← wenn node_id auflösbar (page_context_service)</span></div>
          <div>└─ Schicht 1: guardrails.md <span style={{ color: 'var(--text-muted)' }}>← immer am Ende!</span></div>
        </div>
      </Section>

      {/* ═══════════════ INTERACTIONS ═══════════════ */}
      <Section title="Wechselwirkungen" icon="🔗">
        <p style={pStyle}>
          Die Elemente arbeiten nicht isoliert — sie beeinflussen sich gegenseitig in einer klaren Kette:
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[
            { from: 'Persona', arrows: ['→ Pattern-Gate (filtert)', '→ Policy (Disclaimers, Tool-Sperren)', '→ Anrede (Sie/du/neutral)', '→ Prompt (persona-spezifischer Abschnitt)'] },
            { from: 'Intent', arrows: ['→ Pattern-Gate (filtert)', '→ Spekulative MCP-Vorab-Abfrage', '→ Tool-Präferenz (Collections vs. Content)', '→ Entity-Erwartung (welche Slots?)'] },
            { from: 'Signals', arrows: ['→ Pattern-Scoring (high/medium/low fit)', '→ Modulation (überschreibt Ton, Länge)', '→ Flags (skip_intro, one_option, add_sources)', '→ max_items-Reduktion bei Stress'] },
            { from: 'Entities', arrows: ['→ MCP-Tool-Parameter (Suchbegriffe)', '→ Precondition-Gate (Hard Gate)', '→ Entity-Memory (über Turns akkumuliert)', '→ Turn-Type steuert Akkumulation'] },
            { from: 'State', arrows: ['→ Pattern-Gate (filtert)', '→ Wird pro Turn vom LLM gesetzt', '→ Zustandsabhängiges Verhalten'] },
            { from: 'Pattern', arrows: ['→ Antwortstruktur (Ton, Länge, Detail)', '→ Tool-Zugang (sources + tools)', '→ Wird von Signalen moduliert', '→ Core-Rule als LLM-Anweisung'] },
          ].map(item => (
            <div key={item.from} className="card" style={{ padding: 12 }}>
              <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 6, color: 'var(--primary)' }}>{item.from}</div>
              {item.arrows.map((a, i) => (
                <div key={i} style={{ fontSize: 12, color: 'var(--text)', padding: '2px 0' }}>{a}</div>
              ))}
            </div>
          ))}
        </div>
      </Section>

      {/* ═══════════════ SIGNAL DIMENSIONS ═══════════════ */}
      <Section title="Signal-Dimensionen im Detail" icon="📡">
        <p style={pStyle}>
          17 Signale in 4 Dimensionen erkennen die emotionale/situative Lage des Nutzers. Mehrere Signale können gleichzeitig aktiv sein.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[
            { dim: 'D1 — Zeit & Druck', color: '#ef4444', signals: ['zeitdruck → kurz, sachlich, skip_intro', 'ungeduldig → kurz, sachlich, max_items halbiert', 'gestresst → kurz, beruhigend, max_items halbiert', 'effizient → mittel, sachlich'] },
            { dim: 'D2 — Sicherheit', color: '#3b82f6', signals: ['unsicher → mittel, empathisch, one_option', 'ueberfordert → kurz, empathisch, one_option', 'unerfahren → mittel, niedrigschwellig, one_option', 'erfahren → kurz, sachlich', 'entscheidungsbereit → kurz, sachlich'] },
            { dim: 'D3 — Haltung', color: '#8b5cf6', signals: ['neugierig → mittel, spielerisch', 'zielgerichtet → sachlich, skip_intro', 'skeptisch → mittel, transparent, add_sources', 'vertrauend → (keine Overrides)'] },
            { dim: 'D4 — Kontext', color: '#10b981', signals: ['orientierungssuchend → mittel, orientierend', 'vergleichend → mittel, sachlich', 'validierend → mittel, belegend, add_sources', 'delegierend → kurz, sachlich'] },
          ].map(d => (
            <div key={d.dim} className="card" style={{ borderTop: `3px solid ${d.color}` }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>{d.dim}</div>
              {d.signals.map((s, i) => {
                const [name, ...effects] = s.split(' → ');
                return (
                  <div key={i} style={{ fontSize: 12, padding: '3px 0', display: 'flex', gap: 8 }}>
                    <code style={{ ...codeStyle, minWidth: 130 }}>{name}</code>
                    <span style={{ color: 'var(--text-muted)' }}>{effects.join(' → ') || '–'}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <p style={{ ...pStyle, marginTop: 12 }}>
          <strong>Konfliktregeln:</strong> Bei widersprüchlichen Signalen gewinnt die kürzere Länge und das restriktivere Verhalten. Signale überschreiben Pattern-Defaults — nicht umgekehrt.
        </p>
      </Section>

      {/* ═══════════════ EXAMPLE ═══════════════ */}
      <Section title="Beispiel: Kompletter Ablauf" icon="🎯">
        <p style={pStyle}>
          <strong>Nutzernachricht:</strong> <em>"Mathe Klasse 7 Videos"</em> — von einer Lehrkraft auf der Startseite
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {[
            { step: 'Safety', result: 'risk = low, keine Blockaden', color: '#ef4444' },
            { step: 'Klassifikation', result: 'Persona: P-W-LK (Lehrkraft) · Intent: INT-W-03b (Material suchen) · Entities: fach=Mathe, stufe=Kl.7, medientyp=Video · Signals: zielgerichtet, erfahren · State: state-5', color: '#3b82f6' },
            { step: 'Policy', result: 'Keine Blockaden für Lehrkraft + Material-Suche', color: '#f59e0b' },
            { step: 'Pattern-Engine', result: 'Gate: 12 von 20 passieren · Score: PAT-05 (Profi-Filter) gewinnt — erfahren + zielgerichtet in signal_high_fit · Modulate: tone=sachlich, length=kurz, skip_intro=true', color: '#8b5cf6' },
            { step: 'Prompt', result: 'base-persona + domain-rules + LK-Persona + PAT-05 + Signal-Overrides + guardrails', color: '#2B6CB0' },
            { step: 'LLM + MCP', result: 'search_wlo_content(query="Mathematik", stufe="Klasse 7", medientyp="Video") → 8 Treffer', color: '#10b981' },
            { step: 'Antwort', result: 'Knappe, sachliche Auflistung von Mathe-Videos — keine Einleitung, Quellenkarten', color: '#6b7280' },
          ].map((phase, i) => (
            <div key={phase.step}>
              {i > 0 && <FlowArrow />}
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
                <span style={{ width: 120, fontSize: 12, fontWeight: 700, color: phase.color, flexShrink: 0, paddingTop: 2 }}>{phase.step}</span>
                <span style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.6 }}>{phase.result}</span>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* ═══════════════ WISSENSQUELLEN ═══════════════ */}
      <Section title="Wissensquellen: RAG vs. MCP" icon="📚">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="card" style={{ borderTop: '3px solid #2B6CB0' }}>
            <div style={h3Style}>RAG (eigenes Wissen)</div>
            <p style={pStyle}>Dokumente werden in Chunks zerlegt, als Vektoren in SQLite-Vec gespeichert und per Ähnlichkeitssuche abgerufen.</p>
            <div style={{ fontSize: 12 }}>
              <div><strong>Always-On:</strong> Wird bei jeder Nachricht als Kontext eingefügt (z.B. WLO-Webseite-Info)</div>
              <div style={{ marginTop: 4 }}><strong>On-Demand:</strong> Nur wenn Pattern <code style={codeStyle}>sources: ["rag"]</code> hat und LLM <code style={codeStyle}>query_knowledge</code> aufruft</div>
              <div style={{ marginTop: 4 }}><strong>Upload:</strong> Über Studio (Datei, URL oder Freitext)</div>
            </div>
          </div>
          <div className="card" style={{ borderTop: '3px solid #10b981' }}>
            <div style={h3Style}>MCP (externe Tools)</div>
            <p style={pStyle}>Externer Server (WLO edu-sharing) stellt 10 Tools bereit, die der LLM bei Bedarf aufruft.</p>
            <div style={{ fontSize: 12 }}>
              <div><strong>Zugang:</strong> Nur wenn Pattern <code style={codeStyle}>sources: ["mcp"]</code> hat</div>
              <div style={{ marginTop: 4 }}><strong>Blockierbar:</strong> Safety oder Policy können einzelne Tools sperren</div>
              <div style={{ marginTop: 4 }}><strong>Spekulativ:</strong> Bei bestimmten Intents wird die Suche parallel zur LLM-Antwort gestartet</div>
            </div>
          </div>
          <div className="card" style={{ borderTop: '3px solid #b45309', gridColumn: '1 / -1' }}>
            <div style={h3Style}>Themenseiten-Resolver (ergänzt Layer 6)</div>
            <p style={pStyle}>
              Wenn das Widget auf einer WLO-Themenseite / Sammlung / edu-sharing-Render eingebettet ist,
              löst <code style={codeStyle}>page_context_service</code> die URL beim ersten Turn via MCP
              (<code style={codeStyle}>get_node_details</code>, <code style={codeStyle}>search_wlo_topic_pages</code>)
              zu einem semantischen Block auf (Titel · Fächer · Bildungsstufen · Keywords · Material-Typen).
            </p>
            <div style={{ fontSize: 12 }}>
              <div><strong>TTL:</strong> 30 Min bei Erfolg · 2 Min bei MCP-Fehler (schneller Recovery)</div>
              <div style={{ marginTop: 4 }}><strong>Erkannte URL-Muster:</strong> <code style={codeStyle}>/themenseite/&lt;slug&gt;</code>, <code style={codeStyle}>/fachportal/&lt;fach&gt;/&lt;slug&gt;</code>, <code style={codeStyle}>/components/render/&lt;uuid&gt;</code>, <code style={codeStyle}>?node=</code>, <code style={codeStyle}>?collection=</code></div>
              <div style={{ marginTop: 4 }}><strong>Wirkung:</strong> Bot kann „Worum geht's hier?" oder „Quiz dazu" ohne Rückfrage beantworten — Seitentitel wird als Default-Thema genutzt</div>
            </div>
          </div>
        </div>
      </Section>

      {/* ═══════════════ Canvas Material-Typen (full list) ═══════════════ */}
      <Section title="Canvas-Material-Typen (alle 18)" icon="📋">
        <p style={pStyle}>
          Schicht 5 (<code style={codeStyle}>05-canvas/material-types.yaml</code>) definiert
          18 Output-Formate. Bei <code style={codeStyle}>INT-W-11 Canvas-Create</code> wählt der
          Classifier einen Typ; bei <code style={codeStyle}>auto</code> entscheidet der LLM
          anhand des Kontexts.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="card" style={{ borderTop: '3px solid #10b981' }}>
            <div style={h3Style}>Didaktisch (13)</div>
            <p style={{ ...mutedStyle, marginBottom: 8 }}>Für Lehrkräfte, Schüler:innen und Eltern.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {[
                ['auto', '🤖 Automatisch'],
                ['arbeitsblatt', '📝 Arbeitsblatt'],
                ['infoblatt', '📄 Infoblatt'],
                ['praesentation', '🖼️ Präsentation'],
                ['quiz', '❓ Quiz/Test'],
                ['checkliste', '☑️ Checkliste'],
                ['glossar', '📖 Glossar'],
                ['struktur', '🗂️ Strukturübersicht'],
                ['uebung', '✏️ Übungsaufgaben'],
                ['lerngeschichte', '📚 Lerngeschichte'],
                ['versuch', '🧪 Versuchsanleitung'],
                ['diskussion', '💬 Diskussionskarten'],
                ['rollenspiel', '🎭 Rollenspielkarten'],
              ].map(([id, label]) => (
                <span key={id} className="tag tag-gray" style={{ fontSize: 11 }} title={id}>{label}</span>
              ))}
            </div>
          </div>
          <div className="card" style={{ borderTop: '3px solid #2B6CB0' }}>
            <div style={h3Style}>Analytisch (5)</div>
            <p style={{ ...mutedStyle, marginBottom: 8 }}>Für Redaktion, Presse, Politik, Beratung, Verwaltung.</p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {[
                ['bericht', '📊 Bericht'],
                ['factsheet', '📑 Factsheet'],
                ['steckbrief', '🪪 Projektsteckbrief'],
                ['pressemitteilung', '📰 Pressemitteilung'],
                ['vergleich', '⚖️ Vergleichs-Analyse'],
              ].map(([id, label]) => (
                <span key={id} className="tag tag-gray" style={{ fontSize: 11 }} title={id}>{label}</span>
              ))}
            </div>
          </div>
        </div>
        <p style={{ ...pStyle, marginTop: 12 }}>
          Aliase (z.B. „Lernblatt" → <code style={codeStyle}>arbeitsblatt</code>) werden in
          <code style={codeStyle}> 05-canvas/create-triggers.yaml</code> gepflegt. Edit-Trigger
          („mach es kürzer", „Lösungen hinzu") in
          <code style={codeStyle}> 05-canvas/edit-triggers.yaml</code>.
        </p>
      </Section>

      {/* ═══════════════ Snapshots & Werkseinstellungen ═══════════════ */}
      <Section title="Snapshots & Werkseinstellungen" icon="💾">
        <p style={pStyle}>
          Das Studio kennt zwei Arten von Snapshots — beide enthalten <strong>alle 58
          Config-Dateien</strong> aus den 13 Layer-Ordnern (Patterns, Rules, Personas, Intents,
          States, Signale, Canvas-Formate, Privacy etc.) und optional die SQLite-DB
          (RAG-Embeddings + Sessions + Eval-Historie).
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="card" style={{ borderTop: '3px solid #6B7280' }}>
            <div style={h3Style}>User-Snapshots</div>
            <p style={{ ...mutedStyle, marginBottom: 8 }}>
              <code style={codeStyle}>backend/snapshots/snap-*.zip</code>
            </p>
            <ul style={{ ...pStyle, paddingLeft: 18 }}>
              <li>Anlegen: 📦-Symbol oben rechts → „Neuer Snapshot"</li>
              <li>Können beliebig viele angelegt und einzeln zurückgespielt werden</li>
              <li>Optional ohne DB (nur Configs, ~85 KB) für schnelle Rule-Rollbacks</li>
              <li>Können als „Werkseinstellung" promoted werden („Als Factory")</li>
            </ul>
          </div>
          <div className="card" style={{ borderTop: '3px solid #F59E0B' }}>
            <div style={h3Style}>Werkseinstellungs-Snapshot</div>
            <p style={{ ...mutedStyle, marginBottom: 8 }}>
              <code style={codeStyle}>backend/knowledge/factory-snapshot.zip</code>
            </p>
            <ul style={{ ...pStyle, paddingLeft: 18 }}>
              <li>Genau einer pro Installation — überschreibt sich beim Promoten</li>
              <li>Wird auf <strong>frischen Installationen automatisch entpackt</strong>, sobald die DB leer startet</li>
              <li>Versions-Marker (<code style={codeStyle}>factory_version</code>) verhindert wiederholtes Anwenden bei späteren Restarts</li>
              <li>„Werkseinstellungen zurücksetzen" (gelber Block im Modal) stellt diesen Stand wieder her</li>
            </ul>
          </div>
        </div>
        <div className="card" style={{ background: '#FFFBEB', borderColor: '#FDE68A', marginTop: 12, padding: 12 }}>
          <strong>⚠️ Hinweis:</strong> <span style={pStyle}>Wird ein User-Snapshot <em>ohne DB</em> als
          Factory promotet, hat anschließend auch die Werkseinstellung keine DB. Bei einem späteren
          „Werkseinstellungen zurücksetzen" werden dann nur die Configs überschrieben, die DB bleibt
          unberührt. Für eine vollständige Wiederherstellung muss der Quell-Snapshot mit
          <code style={codeStyle}>include_db=true</code> erstellt sein.</span>
        </div>
      </Section>

      {/* ═══════════════ Widget-Einbettung ═══════════════ */}
      <Section title="Widget-Einbettung (Web-Component)" icon="🔌">
        <p style={pStyle}>
          Der Chat lässt sich als Custom Element <code style={codeStyle}>&lt;boerdi-chat&gt;</code>
          auf jeder Webseite einbinden. Das Single-File-Bundle wird über
          <code style={codeStyle}> npm run build:widget</code> erzeugt
          (<code style={codeStyle}>frontend/dist/widget/</code>).
        </p>
        <pre style={{ background: '#0F172A', color: '#E2E8F0', padding: 12, borderRadius: 6, fontSize: 12, overflowX: 'auto' }}>
{`<script src="/widget/boerdi-widget.js" defer></script>

<!-- Minimal-Einbindung (alle Defaults) -->
<boerdi-chat api-url="https://api.example.de"></boerdi-chat>

<!-- Für Embedding ohne Debug- und Sprachbuttons -->
<boerdi-chat
  api-url="https://api.example.de"
  position="bottom-right"
  primary-color="#1c4587"
  show-debug-button="false"
  show-language-buttons="false">
</boerdi-chat>`}
        </pre>
        <div style={{ ...h3Style, marginTop: 16 }}>Verfügbare Attribute</div>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Attribut</th>
              <th style={thStyle}>Default</th>
              <th style={thStyle}>Beschreibung</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['api-url', '—', 'Backend-Basis-URL (Pflicht)'],
              ['position', 'bottom-right', 'Position des FABs: bottom-right | bottom-left | top-right | top-left'],
              ['initial-state', 'collapsed', 'Anfangszustand: collapsed | expanded'],
              ['primary-color', '#1c4587', 'Hauptfarbe (CSS-Hex)'],
              ['greeting', '—', 'Eigene Begrüßungsnachricht'],
              ['persist-session', 'true', 'Session in localStorage halten (true/false)'],
              ['session-key', 'boerdi_session_id', 'localStorage-Schlüssel'],
              ['auto-context', 'true', 'Seitenkontext automatisch erfassen'],
              ['page-context', '—', 'JSON-Objekt mit zusätzlichem Kontext'],
              ['show-debug-button', 'true', '🔍 Debug-Toggle in Header anzeigen (false zum Ausblenden)'],
              ['show-language-buttons', 'true', '🔊 TTS und 🎤 Mic-Buttons anzeigen (false = ohne Sprachfunktion)'],
            ].map(([attr, def, desc]) => (
              <tr key={attr}>
                <td style={tdStyle}><code style={codeStyle}>{attr}</code></td>
                <td style={tdStyle}><code style={codeStyle}>{def}</code></td>
                <td style={tdStyle}>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* ═══════════════ Canvas & Privacy (operational additions) ═══════════════ */}
      <Section title="Canvas-Arbeitsfläche & Datenschutz" icon="🎨">
        <p style={pStyle}>
          Zwei operative Ergänzungen zur Kern-Pipeline:
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="card" style={{ borderTop: '3px solid #ec4899' }}>
            <div style={h3Style}>Canvas-Intents & -Formate</div>
            <p style={pStyle}>
              Schicht 5 definiert <strong>18 Material-Typen</strong> (13 didaktisch + 5 analytisch:
              Bericht/Factsheet/Steckbrief/Pressemitteilung/Vergleich).
            </p>
            <div style={{ fontSize: 12 }}>
              <div><strong>INT-W-11 Canvas-Create</strong> → PAT-21 erzeugt Markdown + <code style={codeStyle}>page_action: canvas_open</code></div>
              <div style={{ marginTop: 4 }}><strong>INT-W-12 Canvas-Edit</strong> → direkter Handler, verfeinert <code style={codeStyle}>_canvas_last_markdown</code> bei „mach es einfacher" / „Lösungen hinzu"</div>
              <div style={{ marginTop: 4 }}><strong>Type-/Topic-Priorität:</strong> aktueller Turn &gt; Classifier &gt; sticky Session (verhindert Stale-Wins bei Chip-Klicks)</div>
            </div>
          </div>
          <div className="card" style={{ borderTop: '3px solid #059669' }}>
            <div style={h3Style}>Privacy-Gates</div>
            <p style={pStyle}>
              Logging kann in <code style={codeStyle}>01-base/privacy-config.yaml</code> tiergranular
              deaktiviert werden (Studio-Panel „Datenschutz"):
            </p>
            <div style={{ fontSize: 12 }}>
              <div><code style={codeStyle}>logging.messages</code> — Chatverläufe</div>
              <div><code style={codeStyle}>logging.memory</code> — Session-Key/Value</div>
              <div><code style={codeStyle}>logging.quality</code> — Quality-Analytics</div>
              <div><code style={codeStyle}>logging.safety</code> — <strong>immer an</strong> (Audit-Pflicht)</div>
            </div>
            <p style={{ ...pStyle, marginTop: 6 }}>
              Zusätzlich: <strong>Purge-Endpoints</strong> löschen bestehende Daten und
              <strong> Snapshots</strong> (<code style={codeStyle}>/api/config/snapshots</code>)
              sichern Config + DB ohne Up-/Download.
            </p>
          </div>
        </div>
      </Section>

    </div>
  );
}
