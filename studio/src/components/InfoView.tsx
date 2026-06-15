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
  // Welle E v4+12 (Sprint K): Routing-Engine-Card entfernt. Die Rule-
  // Engine wurde komplett ausgebaut, daher kein /api/routing-rules-
  // Endpoint mehr und kein ``rules``-Feld im SystemInfo-Objekt.
  const [info, setInfo] = useState<SystemInfo>({ health: null, factory: null, snapshotCount: null });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [h, f, s] = await Promise.allSettled([
        fetch('/api/health').then(r => r.json()),
        fetch('/api/config/factory').then(r => r.json()),
        fetch('/api/config/snapshots').then(r => r.json()),
      ]);
      if (cancelled) return;
      setInfo({
        health: h.status === 'fulfilled' ? h.value : null,
        factory: f.status === 'fulfilled' ? f.value : null,
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
          Jede Nutzernachricht durchläuft <strong>7 Phasen</strong>. Klassifikation und Pattern-Auswahl laufen strukturiert (LLM-Hint plus deterministische Anker), bevor die finale Antwort generiert wird.
        </p>
        <div className="card" style={{ background: '#f8fafc', padding: 16 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            {[
              { step: '1', label: 'Safety-Check', desc: 'Regex, Moderation, Legal-Classifier prüfen die Nachricht; Crisis/Threat-Marker erzwingen M01/M02', color: '#ef4444' },
              { step: '2', label: 'Klassifikation (LLM)', desc: 'Persona, Intent, Pattern-Hint, Signals, Entities, State, Turn-Type erkennen — classify-overrides.yaml liefert Hard-Override-Anker', color: '#3b82f6' },
              { step: '3', label: 'Policy-Prüfung', desc: 'Tool-Blockaden & Disclaimers anhand von Persona+Intent', color: '#f59e0b' },
              { step: '4', label: 'Pattern-Selection', desc: 'Safety > LLM-Hint > Fallback (M15). Single-Source-of-Truth-Architektur, keine Rule-Engine mehr.', color: '#8b5cf6' },
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
              <td style={tdStyle}>6</td>
              <td style={tdStyle}>Wer spricht? (Lehrkraft, Schüler, Eltern, Presse…)</td>
              <td style={tdStyle}>Anrede (Sie/du), Pattern-Auswahl, Policy-Regeln, Tool-Zugang</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>Intent</strong></td>
              <td style={tdStyle}>8</td>
              <td style={tdStyle}>Was will der Nutzer? (Inhalte abrufen, Fakten, Inhalt erstellen, Material-Bearbeitung, Feedback…)</td>
              <td style={tdStyle}>Pattern-Auswahl, MCP-Tool-Präferenz, spekulative Vorab-Abfragen, Pattern-Routing</td>
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
              <td style={tdStyle}>3</td>
              <td style={tdStyle}>Gesprächszustand: Orientierung → Suche → Kuratierung → Feedback → Material-Erstellung</td>
              <td style={tdStyle}>Pattern-Auswahl, zustandsabhängiges Verhalten</td>
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
          Die Pattern-Engine wählt aus 16 Gesprächsmustern <strong>genau eines</strong> aus. Nur das Gewinner-Pattern wird in den Prompt eingefügt.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <div className="card" style={{ borderTop: '3px solid #ef4444' }}>
            <div style={h3Style}>Phase 1: Klassifikation</div>
            <p style={pStyle}>
              <strong>Einordnung</strong> — Der Input wird in Intent, Persona, State und Entities klassifiziert; der Klassifikator liefert zugleich einen <code style={codeStyle}>pattern_id_hint</code>.
            </p>
            <p style={mutedStyle}>Ergebnis: Klassifikation + Pattern-Vorschlag</p>
          </div>
          <div className="card" style={{ borderTop: '3px solid #f59e0b' }}>
            <div style={h3Style}>Phase 2: Pattern-Wahl</div>
            <p style={pStyle}>
              <strong>Auswahl</strong> — Der <code style={codeStyle}>pattern_id_hint</code> bestimmt das Pattern; <code style={codeStyle}>classify-overrides.yaml</code> dient als deterministischer Hard-Anker.
            </p>
            <p style={mutedStyle}>Ergebnis: gewähltes Pattern</p>
          </div>
          <div className="card" style={{ borderTop: '3px solid #10b981' }}>
            <div style={h3Style}>Phase 3: Modulate</div>
            <p style={pStyle}>
              <strong>Anpassung</strong> — Die Defaults des Gewinners (Ton, Länge, Detail…) werden durch aktive Signale überschrieben. Kürzere Länge gewinnt bei Konflikten.
            </p>
            <p style={mutedStyle}>Ergebnis: die finalen Steuerungsfelder für den Prompt</p>
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

      {/* ═══════════════ HARD-OVERRIDES (classify-overrides.yaml) ═══════════════ */}
      <Section title="Hard-Overrides im Classifier (classify-overrides.yaml)" icon="🎚️">
        <p style={pStyle}>
          <strong>Welle E v4+12 (Sprint K, 2026-05-27):</strong> Die separate Routing-
          Rule-Engine wurde komplett ausgebaut. Eval-355c lieferte den empirischen
          Nachweis: ohne Live-Rules <strong>+3.8 % avg_score</strong> und <strong>+20 % pattern_match=2</strong>{' '}
          gegenüber dem vorherigen Run mit aktiver Rule-Engine.
        </p>
        <p style={pStyle}>
          Was die Rules an Mehrwert hatten — explizite Persona-Self-ID („Ich bin Lehrer",
          „als Redakteurin"), Verb-Disambiguatoren (Such-Verb vs Create-Verb) und
          Phantom-Topic-Erkennung — lebt jetzt in einer einzigen Datei:
          <code style={codeStyle}>01-base/classify-overrides.yaml</code>. Der
          Classifier-System-Prompt rendert sie als Hint-Anker, das LLM bekommt sie als
          deterministische Trigger-Liste mit Erwartungswerten.
        </p>
        <p style={pStyle}>
          Vorteil: <strong>eine</strong> Schicht statt Pre-Route + Post-Route + Lookup-
          Gruppen + Shadow-Logs. Studio-Editor: Im Studio über das „Settings"/
          „Architektur-Configs"-Menü direkt als YAML editierbar — Änderungen wirken
          beim nächsten Turn ohne Backend-Restart (mtime-Cache).
        </p>
      </Section>

      {/* ═══════════════ PATTERN-SELEKTION (Welle E v4) ═══════════════ */}
      <Section title="Pattern-Selektion — wer wählt das Pattern?" icon="🎯">
        <p style={pStyle}>
          Seit <strong>Welle E v4 (2026-05-25)</strong> trifft die Pattern-Wahl primär
          das Klassifikator-LLM via <code style={codeStyle}>pattern_id_hint</code>. Die
          frühere 3-Phasen-Engine (Gate → Score → Modulate) wurde auf Hint-Primary
          reduziert.
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Schritt</th>
              <th style={thStyle}>Quelle</th>
              <th style={thStyle}>Effekt</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={tdStyle}><strong>1. Safety-Override</strong></td>
              <td style={tdStyle}><code style={codeStyle}>safety.enforced_pattern</code></td>
              <td style={tdStyle}>M01 bei Selbstgefährdung, M02 bei Drohungen — gewinnt immer.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>2. LLM-Hint</strong></td>
              <td style={tdStyle}><code style={codeStyle}>classification.pattern_id_hint</code></td>
              <td style={tdStyle}>Primärer Pfad in praktisch 100 % der Turns. Wird von <code>01-base/classify-overrides.yaml</code> über Hint-Anker im System-Prompt geleitet.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>3. Fallback</strong></td>
              <td style={tdStyle}>defensiv hardcoded</td>
              <td style={tdStyle}>M15 (Orientierung), wenn weder Safety noch Hint ein gültiges Pattern liefern.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>4. phase3_modulate</strong></td>
              <td style={tdStyle}>Persona-Modifier + Pattern-Defaults + Signale</td>
              <td style={tdStyle}>Stil/Tonalität/Tool-Liste/Slot-Degradation. Persona greift hier — <em>nicht</em> bei der Pattern-Wahl.</td>
            </tr>
          </tbody>
        </table>
        <p style={{ ...pStyle, marginTop: 12 }}>
          <strong>Was es nicht mehr gibt:</strong>{' '}
          <code style={codeStyle}>gate_personas</code>,{' '}
          <code style={codeStyle}>gate_states</code>,{' '}
          <code style={codeStyle}>gate_intents</code>,{' '}
          <code style={codeStyle}>signal_*_fit</code>,{' '}
          <code style={codeStyle}>page_bonus</code>, Tie-Breaker.
          Pattern-Frontmatter braucht nur noch Antwort-Form, Tools und Inhalt-Regeln.{' '}
          <code style={codeStyle}>precondition_slots</code> bleibt — wirkt aber nur noch
          als Degradation-Flag in <code>phase3_modulate</code> (M09 braucht{' '}
          <code>topic</code>, M10 braucht <code>material_type</code> + <code>topic</code>),
          nicht als Pattern-Eliminator.
        </p>

        <div style={{ ...h3Style, marginTop: 20 }}>Persona-Wirkung — 2 Ebenen (Welle E v4)</div>
        <p style={pStyle}>
          Persona-Entkopplung ist abgeschlossen: die Persona steuert <strong>Stil und
          Anrede</strong>, nicht die Pattern-Wahl.
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Ebene</th>
              <th style={thStyle}>Wo</th>
              <th style={thStyle}>Wirkung</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td style={tdStyle}><strong>1. Tonalitäts-Modulation</strong></td>
              <td style={tdStyle}>Persona-Frontmatter (<code style={codeStyle}>tone</code>, <code>length_bias</code>, <code>formality</code>, <code>card_text_mode</code>, <code>override</code>)</td>
              <td style={tdStyle}>In <code>phase3_modulate</code> nach gewähltem Pattern. P-ENT bekommt <code>formality=siezen</code> + <code>tone=formell</code>, P-LER bekommt <code>formality=duzen</code> + <code>tone=ermutigend</code>. Editor: Personas-Tab.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>2. Selbst-ID-Korrektur</strong></td>
              <td style={tdStyle}>Routing-Rules (<code style={codeStyle}>lookup_persona_self_id__*</code>)</td>
              <td style={tdStyle}>Explizite Selbst-ID-Phrasen („ich bin Lehrkraft …") überstimmen den Klassifikator. Setzt <code>persona_override</code>, nicht Pattern.</td>
            </tr>
          </tbody>
        </table>
        <div style={{ ...mutedStyle, marginTop: 8 }}>
          <strong>Was die Persona für die Pattern-Wahl bewirkt:</strong> nichts direkt.
          Der Klassifikator-LLM bekommt aber die Persona-Beschreibung +{' '}
          <code>typical_intents</code> aus den Persona-MDs als Kontext — das hilft ihm,
          plausiblere Hints zu setzen.
        </div>
      </Section>

      {/* ═══════════════ 6 LAYERS ═══════════════ */}
      <Section title="Die 6 Architektur-Schichten" icon="🏗️">
        <p style={pStyle}>
          Der System-Prompt wird aus mehreren Schichten zusammengesetzt. Jede Schicht hat eine Priorität — bei Token-Knappheit werden niedrig-priorisierte Schichten zuerst entladen. Schicht 5 (Material-Formate) steuert Ausgabe-Formate und wird nur bei Create-/Edit-Intents geladen.
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
              <td style={tdStyle}>Persona-Definition, Guardrails, Safety-Config, Policy-Regeln, Geräte-Config</td>
              <td style={tdStyle}>Wird <strong>nie</strong> entladen. Guardrails stehen immer am Ende.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>2 — Domain & Regeln</strong></td>
              <td style={tdStyle}><span style={{ color: '#f59e0b', fontWeight: 700 }}>900</span></td>
              <td style={tdStyle}>Plattform-Regeln, WLO-Fachwissen</td>
              <td style={tdStyle}>Wird <strong>nie</strong> entladen.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>3 — Patterns</strong></td>
              <td style={tdStyle}><span style={{ color: '#8b5cf6', fontWeight: 700 }}>500-800</span></td>
              <td style={tdStyle}>Das gewählte Gesprächsmuster (nur 1 von 16)</td>
              <td style={tdStyle}>Kann auf M12 (Degradation) zurückfallen.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>4 — Dimensionen</strong></td>
              <td style={tdStyle}><span style={{ color: '#3b82f6', fontWeight: 700 }}>300-600</span></td>
              <td style={tdStyle}>Nur erkannte Persona + aktiver Intent + Signale (nicht alle)</td>
              <td style={tdStyle}>Kann teilweise entladen werden.</td>
            </tr>
            <tr>
              <td style={tdStyle}><strong>5 — Material-Formate</strong></td>
              <td style={tdStyle}><span style={{ color: '#ec4899', fontWeight: 700 }}>200-400</span></td>
              <td style={tdStyle}>Struktur-Vorgabe des gewählten Material-Typs, Alias-Mapping, Edit-/Create-Trigger</td>
              <td style={tdStyle}>Nur bei I05/I06 (Create/Edit) geladen — sonst nicht im Prompt.</td>
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
          <div>├─ Schicht 5: Material-Format-Struktur <span style={{ color: 'var(--text-muted)' }}>← nur bei I05/I06</span></div>
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
            { from: 'Persona', arrows: ['→ Pattern-Auswahl (LLM-Hint)', '→ Policy (Disclaimers, Tool-Sperren)', '→ Anrede (Sie/du/neutral)', '→ Prompt (persona-spezifischer Abschnitt)'] },
            { from: 'Intent', arrows: ['→ Pattern-Auswahl (LLM-Hint)', '→ Spekulative MCP-Vorab-Abfrage', '→ Tool-Präferenz (Collections vs. Content)', '→ Entity-Erwartung (welche Slots?)'] },
            { from: 'Signals', arrows: ['→ Pattern-Hint (Klassifikator)', '→ Modulation (überschreibt Ton, Länge)', '→ Flags (skip_intro, one_option, add_sources)', '→ max_items-Reduktion bei Stress'] },
            { from: 'Entities', arrows: ['→ MCP-Tool-Parameter (Suchbegriffe)', '→ Slot-Prüfung (Rückfrage bei Lücke)', '→ Entity-Memory (über Turns akkumuliert)', '→ Turn-Type steuert Akkumulation'] },
            { from: 'State', arrows: ['→ Pattern-Auswahl (LLM-Hint)', '→ Wird pro Turn vom LLM gesetzt', '→ Zustandsabhängiges Verhalten'] },
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
            { step: 'Klassifikation', result: 'Persona: P-LEH (Lehrkraft) · Intent: I03 (Inhalte abrufen) · Entities: fach=Mathe, stufe=Kl.7, medientyp=Video · Signals: zielgerichtet, erfahren · State: S3', color: '#3b82f6' },
            { step: 'Policy', result: 'Keine Blockaden für Lehrkraft + Material-Suche', color: '#f59e0b' },
            { step: 'Pattern-Selektion', result: 'Klassifikator-Hint: M05 (Material-Suche gefiltert) — Slots vollständig, Filter (Medientyp, Stufe) gesetzt. Rules greifen nicht (kein Slot-fehlt-Case). phase3_modulate: tone=kollegial (Persona-Modifier), length=kurz, skip_intro=true (Signal "zielgerichtet")', color: '#8b5cf6' },
            { step: 'Prompt', result: 'base-persona + domain-rules + P-LEH-Persona + M05 + Signal-Overrides + guardrails', color: '#2B6CB0' },
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

      {/* ═══════════════ Material-Typen (full list) ═══════════════ */}
      <Section title="Material-Typen (alle 18)" icon="📋">
        <p style={pStyle}>
          Schicht 5 (<code style={codeStyle}>05-canvas/material-types.yaml</code>) definiert
          18 Output-Formate. Bei <code style={codeStyle}>I05 Material-Erstellung</code> wählt der
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
          Das Studio kennt zwei Arten von Snapshots — beide enthalten <strong>alle
          Config-Dateien</strong> aus den Layer-Ordnern (Patterns, Personas, Intents,
          States, Signale, Material-Formate, Privacy etc.) und optional die SQLite-DB
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

<!-- Schlanke Einbindung: Debug-Button aus -->
<boerdi-chat
  api-url="https://api.example.de"
  show-debug-button="false">
</boerdi-chat>

<!-- Edu-Sharing-Embed: keine KI-Erzeugung, eigenes Routing für Links -->
<boerdi-chat
  api-url="https://api.example.de"
  intercept-edu-sharing-links="true"
  emit-routing-debug="true">
</boerdi-chat>`}
        </pre>
        <div style={{ ...h3Style, marginTop: 16 }}>Verfügbare Attribute</div>
        <p style={{ ...mutedStyle, marginBottom: 8 }}>
          Alle Boolean-Attribute akzeptieren die Strings <code style={codeStyle}>"true"</code> /
          <code style={codeStyle}>"false"</code> (Custom-Element-Attribute sind immer Strings).
        </p>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thStyle}>Gruppe</th>
              <th style={thStyle}>Attribut</th>
              <th style={thStyle}>Default</th>
              <th style={thStyle}>Beschreibung</th>
            </tr>
          </thead>
          <tbody>
            {([
              ['Basis', 'api-url', '—', 'Backend-Basis-URL (Pflicht)'],
              ['Basis', 'position', 'bottom-right', 'Position des FABs: bottom-right | bottom-left | top-right | top-left'],
              ['Basis', 'initial-state', 'collapsed', 'Anfangszustand: collapsed | expanded'],
              ['Basis', 'primary-color', '#1c4587', 'Hauptfarbe (CSS-Hex)'],
              ['Basis', 'greeting', '—', 'Eigene Begrüßungsnachricht'],
              ['Session', 'persist-session', 'true', 'Session in localStorage/Cookie halten'],
              ['Session', 'session-key', 'boerdi_session_id', 'localStorage-Schlüssel'],
              ['Session', 'session-cookie-domain', '—', 'Wenn gesetzt, Session in Cookie statt localStorage (Cross-Subdomain)'],
              ['Session', 'session-cookie-max-age', '2592000', 'Cookie-Lebensdauer in Sekunden (Default 30 Tage)'],
              ['Session', 'trusted-domains', '—', 'Komma-Liste von vertrauenswürdigen iframe-Origins für postMessage'],
              ['Kontext', 'auto-context', 'true', 'Seitenkontext automatisch erfassen'],
              ['Kontext', 'page-context', '—', 'JSON-Objekt mit zusätzlichem Kontext'],
              ['Header-UI', 'show-debug-button', 'true', '🔍 Debug-Toggle in Header anzeigen'],
              ['Header-UI', 'show-language-buttons', 'true', '🔊 TTS und 🎤 Mic-Buttons anzeigen'],
              ['Integration', 'intercept-edu-sharing-links', 'false', 'Bei "true": Link-Klicks emitten (linkClicked)-Event statt zu navigieren'],
              ['Integration', 'emit-guide-suggestion', 'false', 'Bei "true": Bot-Turns mit Lotsen-Treffer feuern badboerdi:guide-suggestion CustomEvent'],
              ['Integration', 'emit-routing-debug', 'false', 'Bei "true": Pro Bot-Turn ein badboerdi:routing-debug CustomEvent mit Pattern/Intent/State/Tools'],
            ] as [string, string, string, string][]).map(([group, attr, def, desc], idx, arr) => {
              const groupStart = idx === 0 || arr[idx - 1][0] !== group;
              return (
                <tr key={attr} style={groupStart ? { borderTop: '2px solid #E5E7EB' } : undefined}>
                  <td style={{ ...tdStyle, fontWeight: groupStart ? 600 : 400, color: groupStart ? '#374151' : 'transparent', fontSize: 11 }}>
                    {groupStart ? group : ''}
                  </td>
                  <td style={tdStyle}><code style={codeStyle}>{attr}</code></td>
                  <td style={tdStyle}><code style={codeStyle}>{def}</code></td>
                  <td style={tdStyle}>{desc}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div style={{ ...h3Style, marginTop: 16 }}>Events (Outputs)</div>
        <p style={{ ...pStyle, marginBottom: 8 }}>
          Das Widget feuert CustomEvents auf <code style={codeStyle}>window</code> und Angular-Outputs
          (bei programmatischer Nutzung), die Host-Seiten z.B. für SPA-Navigation oder Analytics
          verwenden können:
        </p>
        <ul style={{ fontSize: 12, lineHeight: 1.8, marginLeft: 16, marginBottom: 0 }}>
          <li><code style={codeStyle}>badboerdi:page-action</code> — <strong>immer aktiv</strong>. Backend-page_actions: <code>navigate</code>, <code>show_results</code>. Payload: <code>{`{action, payload}`}</code>.</li>
          <li><code style={codeStyle}>badboerdi:guide-suggestion</code> — nur wenn <code>emit-guide-suggestion="true"</code>. Feuert pro Bot-Turn mit Lotsen-eligible Cards. Payload: <code>{`{url, title, node_id, node_type, query, alternatives[]}`}</code>.</li>
          <li><code style={codeStyle}>badboerdi:routing-debug</code> — nur wenn <code>emit-routing-debug="true"</code>. Routing-Telemetrie pro Bot-Turn. Payload: <code>{`{pattern, intent, state, persona, tools_called[], sources[], modifier{}}`}</code>.</li>
          <li><code style={codeStyle}>badboerdi:query-meta</code> — <strong>immer aktiv</strong>. MCP-Suchanfragen-Metadaten. Payload: <code>{`{queries[]{tool_name, search_term, criteria[], pagination, search_url}}`}</code>.</li>
        </ul>
        <p style={{ fontSize: 12, lineHeight: 1.6, marginTop: 6, marginBottom: 0 }}>
          Angular-Outputs: <code style={codeStyle}>(pageAction)</code>, <code style={codeStyle}>(guideSuggestion)</code>, <code style={codeStyle}>(routingDebug)</code>, <code style={codeStyle}>(queryMeta)</code>, <code style={codeStyle}>(linkClicked)</code> (nur bei <code>intercept-edu-sharing-links="true"</code>).
        </p>
        <div style={{ ...mutedStyle, marginTop: 8 }}>
          Detailliertes Payload-Schema:  <code style={codeStyle}>docs/05-widget-javascript-api.md</code>.
        </div>
      </Section>

      {/* ═══════════════ Material & Datenschutz (operational additions) ═══════════════ */}
      <Section title="Material-Erstellung & Datenschutz" icon="🎨">
        <p style={pStyle}>
          Zwei operative Ergänzungen zur Kern-Pipeline:
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="card" style={{ borderTop: '3px solid #ec4899' }}>
            <div style={h3Style}>Material-Intents & -Formate</div>
            <p style={pStyle}>
              Schicht 5 definiert <strong>18 Material-Typen</strong> (13 didaktisch + 5 analytisch:
              Bericht/Factsheet/Steckbrief/Pressemitteilung/Vergleich).
            </p>
            <div style={{ fontSize: 12 }}>
              <div><strong>I05 Material-Erstellung</strong> → M10 erzeugt das Material als InlineDocument-Box im Chat-Verlauf</div>
              <div style={{ marginTop: 4 }}><strong>I06 Material-Bearbeitung</strong> → direkter Handler, verfeinert <code style={codeStyle}>_canvas_last_markdown</code> bei „mach es einfacher" / „Lösungen hinzu"</div>
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
