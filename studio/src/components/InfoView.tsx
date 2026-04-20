'use client';

import { useState } from 'react';

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

/* ── Main Component ────────────────────────────────────────────────── */
export default function InfoView() {
  return (
    <div>
      <h2 className="card-title" style={{ marginBottom: 4 }}>ℹ️ Architektur-Referenz</h2>
      <p style={{ ...mutedStyle, marginBottom: 20 }}>Wie die Elemente zusammenspielen — vom Nutzer-Input bis zur Bot-Antwort.</p>

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
              { step: '3', label: 'Policy-Prüfung', desc: 'Tool-Blockaden & Disclaimers anhand von Persona+Intent', color: '#f59e0b' },
              { step: '4', label: 'Pattern-Engine (3 Phasen)', desc: 'Gate → Score → Modulate — wählt das beste Gesprächsmuster', color: '#8b5cf6' },
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
              <td style={tdStyle}>10</td>
              <td style={tdStyle}>Was will der Nutzer? (Material suchen, Fakten, Feedback…)</td>
              <td style={tdStyle}>Pattern-Gate, MCP-Tool-Präferenz, spekulative Vorab-Abfragen</td>
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
              <td style={tdStyle}>11</td>
              <td style={tdStyle}>Gesprächszustand: Orientierung → Suche → Kuratierung → Feedback</td>
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
          Die Pattern-Engine wählt aus 20 Gesprächsmustern <strong>genau eines</strong> aus. Nur das Gewinner-Pattern wird in den Prompt eingefügt.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ borderTop: '3px solid #ef4444' }}>
            <div style={h3Style}>Phase 1: Gate</div>
            <p style={pStyle}>
              <strong>Eliminierung</strong> — Patterns werden entfernt, wenn Persona, Intent oder State nicht zu den <code style={codeStyle}>gate_*</code>-Listen passen. Hard Gate: fehlende <code style={codeStyle}>precondition_slots</code> eliminieren ebenfalls.
            </p>
            <p style={mutedStyle}>Ergebnis: Kandidatenliste (oft 8-12 von 20)</p>
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
              <td style={tdStyle}>PAT-18 nur für <code style={codeStyle}>["INT-W-10"]</code> (Unterrichtsplanung)</td>
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
            <p style={pStyle}>Externer Server (WLO edu-sharing) stellt 11 Tools bereit, die der LLM bei Bedarf aufruft.</p>
            <div style={{ fontSize: 12 }}>
              <div><strong>Zugang:</strong> Nur wenn Pattern <code style={codeStyle}>sources: ["mcp"]</code> hat</div>
              <div style={{ marginTop: 4 }}><strong>Blockierbar:</strong> Safety oder Policy können einzelne Tools sperren</div>
              <div style={{ marginTop: 4 }}><strong>Spekulativ:</strong> Bei bestimmten Intents wird die Suche parallel zur LLM-Antwort gestartet</div>
            </div>
          </div>
        </div>
      </Section>

    </div>
  );
}
