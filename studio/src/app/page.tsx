'use client';

import { useState, useEffect, useCallback, type ReactNode } from 'react';
import PatternEditor from '@/components/PatternEditor';
import ElementEditor from '@/components/ElementEditor';
import KnowledgeManager from '@/components/KnowledgeManager';
import { SessionsView } from '@/components/SessionsView';
import SafetyLogsView from '@/components/SafetyLogsView';
import ConfigTextEditor from '@/components/ConfigTextEditor';
import HomeOverview from '@/components/HomeOverview';
import SecurityLevelPicker from '@/components/SecurityLevelPicker';
import QualityView from '@/components/QualityView';
import EvaluationView from '@/components/EvaluationView';
import InfoView from '@/components/InfoView';
import PrivacyView from '@/components/PrivacyView';
import CanvasFormatsEditor from '@/components/CanvasFormatsEditor';
import DisplayRulesView from '@/components/DisplayRulesView';
import { SnapshotsModal } from '@/components/SnapshotsModal';

// ── Types ────────────────────────────────────────────────────────────
type Layer = 'home' | 'identity' | 'domain' | 'patterns' | 'dimensions' | 'canvas' | 'knowledge' | 'sessions' | 'safety_logs' | 'quality' | 'evaluation' | 'privacy' | 'info' | 'display';

export interface Elements {
  patterns: PatternData[];
  personas: PersonaData[];
  intents: IntentData[];
  states: StateData[];
  signals: SignalData[];
  entities: EntityData[];
  device: DeviceConfig;
  base_files: BaseFile[];
}

export interface PatternData {
  id: string;
  label: string;
  short_purpose?: string;
  priority?: number;
  // Welle E v4 (2026-05-25): gate_*, signal_*, page_bonus entfernt —
  // Pattern wird vom LLM-Hint gewählt, deterministische Filterung /
  // Scoring sind aus der Engine raus. Alte MDs mit diesen Feldern
  // werden vom config_loader still ignoriert.
  precondition_slots?: string[];
  default_tone?: string;
  default_length?: string;
  default_detail?: string;
  response_type?: string;
  sources?: string[];
  rag_areas?: string[];
  format_primary?: string;
  format_follow_up?: string;
  card_text_mode?: string;
  tools?: string[];
  output_mode?: string;
  // Welle E v3 (2026-05-25): strukturierte Frontmatter-Felder
  core_rule?: string;
  forbidden_phrases?: string[];
  anti_patterns?: string[];
  // Welle E v4+7 (2026-05-26): strukturierte Pattern-Auswahl-Regeln
  when_to_use?: string[];
  when_not_to_use?: string[];
  trigger_phrases?: string[];
  discriminators?: PatternDiscriminator[];
  body_md?: string;
  file?: string;
  [key: string]: any;
}

export interface PatternDiscriminator {
  vs: string;        // Other pattern ID, e.g. "M04"
  rule: string;      // Disambiguator-Regel
  example?: string;  // Konkretes Beispiel
}

// Welle E v2 (2026-05-25): Personas haben jetzt strukturierte
// Frontmatter-Felder analog zu Intents/States/Entities. Body wird zur
// Persönlichkeits-Prosa (personality_text).
export interface PersonaAntiMarker {
  phrase: string;
  redirect_to?: string;
  rationale?: string;
}

export interface PersonaDiscriminator {
  vs: string;
  rule: string;
  example_a?: string;
  example_b?: string;
}

export interface PersonaData {
  id: string;
  label: string;
  file?: string;
  description?: string;
  // Tonalitäts-Modifier
  tone?: string;
  length_bias?: number;
  formality?: string;
  card_text_mode?: string;
  override?: boolean;
  // Klassifikations-Felder (Welle E v2)
  positive_markers?: string[];
  anti_markers?: PersonaAntiMarker[];
  discriminators?: PersonaDiscriminator[];
  goals?: string[];
  rules?: string[];
  typical_intents?: string[];
  personality_text?: string;
  // Backward-Compat-Alias
  hints?: string[];
  anti_hints?: string[];
}

// Welle E (2026-05-25): erweitertes Intent-Schema. Trigger/Negativ-Trigger/
// Diskriminatoren werden im Klassifizier-Prompt zu strukturierten
// Regel-Blöcken gerendert. Studio zeigt sie aktuell read-only —
// Bearbeitung über den YAML-Editor pro Datei.
export interface IntentNegativeTrigger {
  phrase: string;
  redirect_to?: string;
  rationale?: string;
  when?: string;
}
export interface IntentDiscriminator {
  vs: string;
  rule: string;
  example_a?: string;
  example_b?: string;
}
export interface IntentData {
  id: string;
  label: string;
  description?: string;
  file?: string;
  examples?: string[];
  trigger_verbs?: string[];
  negative_triggers?: IntentNegativeTrigger[];
  discriminators?: IntentDiscriminator[];
}

export interface StateData {
  id: string;
  label: string;
  description?: string;
  cluster?: string;
  file?: string;
  // Welle E
  role?: string;
  bot_directive?: string;
  next_likely?: string[];
  selection_criteria?: string[];
}

export interface SignalData {
  id: string;
  dimension?: string;
  modulations?: Record<string, any>;
  file?: string;
}

// Welle E (2026-05-25)
export interface EntityPositiveExample {
  text: string;
  value?: string;
}
export interface EntityNegativeExample {
  text: string;
  rationale?: string;
}
export interface EntityDiscriminator {
  vs: string;
  rule: string;
  example_a?: string;
  example_b?: string;
}
export interface EntityData {
  id: string;
  label?: string;
  type?: string;
  description?: string;
  examples?: string[];
  positive_examples?: EntityPositiveExample[];
  negative_examples?: EntityNegativeExample[];
  discriminators?: EntityDiscriminator[];
  file?: string;
}

export interface DeviceConfig {
  device_max_items?: Record<string, number>;
  persona_formality?: Record<string, string>;
}

export interface BaseFile {
  name: string;
  path: string;
  type: string;
}

// ── Navigation (datengetrieben) ──────────────────────────────────────
// Sektionen nach Zweck statt nummerierter „Schichten". Die Reihenfolge der
// Konfig-Einträge entspricht weiterhin der Prompt-Assemblierung (ohne
// sichtbare Nummern). Interne Layer-IDs bleiben unverändert (View-Switch).
const navSvg = (paths: ReactNode): ReactNode => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {paths}
  </svg>
);

const NAV_ICONS: Record<string, ReactNode> = {
  home:        navSvg(<><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></>),
  identity:    navSvg(<path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6l7-3z" />),
  domain:      navSvg(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.6 2.7 2.6 15.3 0 18M12 3c-2.6 2.7-2.6 15.3 0 18" /></>),
  patterns:    navSvg(<><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>),
  dimensions:  navSvg(<><path d="M4 7h8M18 7h2" /><circle cx="15" cy="7" r="2" /><path d="M4 17h2M10 17h10" /><circle cx="7" cy="17" r="2" /></>),
  canvas:      navSvg(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>),
  knowledge:   navSvg(<path d="M5 4h13v16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM18 4v16" />),
  display:     navSvg(<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></>),
  sessions:    navSvg(<path d="M4 5h16v11H8l-4 4V5z" />),
  quality:     navSvg(<><path d="M4 20V4" /><rect x="7" y="11" width="3" height="7" /><rect x="12" y="7" width="3" height="11" /><rect x="17" y="14" width="3" height="4" /></>),
  evaluation:  navSvg(<><rect x="5" y="4" width="14" height="17" rx="2" /><path d="M9 4h6v3H9zM9 14l2 2 4-4" /></>),
  safety_logs: navSvg(<><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6l7-3z" /><path d="M12 9v3M12 16h.01" /></>),
  privacy:     navSvg(<><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>),
  info:        navSvg(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>),
};

const NAV_SECTIONS: { title?: string; items: { id: Layer; label: string; desc?: string }[] }[] = [
  { items: [{ id: 'home', label: 'Übersicht', desc: 'Start, Architektur & Status' }] },
  {
    title: 'Konfiguration',
    items: [
      { id: 'identity',   label: 'Identität & Schutz', desc: 'Persona, Guardrails, Safety, Geräte' },
      { id: 'domain',     label: 'Domain-Wissen',      desc: 'Plattform-Wissen, Policy, Web-Tour' },
      { id: 'patterns',   label: 'Patterns',           desc: 'Gesprächsmuster' },
      { id: 'dimensions', label: 'Dimensionen',        desc: 'Personas, Intents, States, Entities' },
      { id: 'canvas',     label: 'Material-Formate',   desc: 'Material-Typen, Aliase, Trigger' },
      { id: 'knowledge',  label: 'Wissen',             desc: 'RAG-Bereiche & MCP-Tools' },
    ],
  },
  {
    title: 'Auswertung',
    items: [
      { id: 'sessions',    label: 'Sessions',    desc: 'Gesprächsverläufe' },
      { id: 'quality',     label: 'Analyse',     desc: 'Pattern-/Intent-Verteilung, Diagnose' },
      { id: 'evaluation',  label: 'Evaluation',  desc: 'Persona-Dialoge automatisch testen' },
      { id: 'safety_logs', label: 'Safety-Logs', desc: 'Risiko-Events & Rate-Limits' },
    ],
  },
  {
    title: 'System',
    items: [
      { id: 'display',  label: 'Anzeige',     desc: 'Boxen, Schriftgrößen, Geräte-Limits' },
      { id: 'privacy',  label: 'Datenschutz', desc: 'Logging & Purge' },
    ],
  },
];

// ── Main Studio Page ─────────────────────────────────────────────────
export default function StudioPage() {
  const [layer, setLayer] = useState<Layer>('home');
  const [elements, setElements] = useState<Elements | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);

  const loadElements = useCallback(async () => {
    try {
      const res = await fetch('/api/config/elements');
      if (res.ok) {
        const data = await res.json();
        setElements(data);
        setBackendOnline(true);
      } else {
        setBackendOnline(false);
      }
    } catch {
      setBackendOnline(false);
    }
  }, []);

  useEffect(() => { loadElements(); }, [loadElements]);

  const saveFile = useCallback(async (path: string, content: string): Promise<boolean> => {
    try {
      const fileType = path.endsWith('.yaml') || path.endsWith('.yml') ? 'yaml' : 'markdown';
      const res = await fetch('/api/config/file', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path, content, file_type: fileType }),
      });
      if (res.ok) {
        await loadElements();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [loadElements]);

  const loadFile = useCallback(async (path: string): Promise<string> => {
    try {
      const res = await fetch(`/api/config/file?path=${encodeURIComponent(path)}`);
      if (res.ok) {
        const data = await res.json();
        return data.content || '';
      }
      return '';
    } catch {
      return '';
    }
  }, []);

  const createFile = useCallback(async (path: string, content: string): Promise<boolean> => {
    const ok = await saveFile(path, content);
    if (ok) await loadElements();
    return ok;
  }, [saveFile, loadElements]);

  const appendToYaml = useCallback(async (path: string, yamlSnippet: string): Promise<boolean> => {
    try {
      const existing = await loadFile(path);
      const newContent = existing.trimEnd() + '\n\n' + yamlSnippet + '\n';
      return await saveFile(path, newContent);
    } catch {
      return false;
    }
  }, [loadFile, saveFile]);

  // Server-side snapshots (quick save/restore without down-/upload)
  const [snapshotsOpen, setSnapshotsOpen] = useState(false);
  // Übersicht: Tab zwischen Dashboard und Architektur-Referenz (Info gemerged).
  const [homeTab, setHomeTab] = useState<'overview' | 'info'>('overview');

  return (
    <div className="studio-layout">
      {/* Header */}
      <header className="studio-header">
        <h1 onClick={() => setLayer('home')} style={{ cursor: 'pointer' }}>Chatbot Konfiguration</h1>
        <div className="header-right">
          <button
            className="btn btn-header btn-sm"
            title="Server-Snapshots: schnelles Sichern/Zurückspielen ohne Up-/Download"
            onClick={() => setSnapshotsOpen(true)}
          >📸 Snapshots</button>
          <button
            className="btn btn-header btn-sm"
            title="Konfiguration + Datenbank als ZIP herunterladen"
            onClick={() => { window.location.href = '/api/config/backup?include_db=true'; }}
          >Backup</button>
          <button
            className="btn btn-header btn-sm"
            title="Konfiguration (+ optional Datenbank) aus ZIP wiederherstellen"
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.accept = '.zip';
              input.onchange = async (e: any) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const wipe = confirm(
                  'Vorhandene Konfiguration vorher LÖSCHEN?\n\n' +
                  'OK = wipe + restore (empfohlen bei Foreign-Snapshots)\n' +
                  'Abbrechen = nur mergen',
                );
                const includeDb = confirm(
                  'Datenbank-Anteil wiederherstellen (falls im ZIP enthalten)?\n\n' +
                  '⚠️ Ersetzt die aktuelle DB komplett: Sessions, Messages,\n' +
                  'Memory, Quality/Safety-Logs, RAG-Chunks.\n\n' +
                  'OK = DB mitrestoren   Abbrechen = nur Config',
                );
                const fd = new FormData();
                fd.append('file', file);
                const params = new URLSearchParams();
                params.set('wipe', wipe ? 'true' : 'false');
                params.set('include_db', includeDb ? 'true' : 'false');
                const resp = await fetch(`/api/config/restore?${params}`, {
                  method: 'POST',
                  body: fd,
                });
                if (resp.ok) {
                  const data = await resp.json();
                  alert(
                    `Restore OK:\n` +
                    `  ${data.config_files ?? 0} Config-Dateien\n` +
                    `  Datenbank: ${data.db_restored ? 'wiederhergestellt' : (data.db_in_archive ? 'vorhanden, aber übersprungen' : 'nicht im Archiv')}`,
                  );
                  await loadElements();
                } else {
                  alert(`Restore fehlgeschlagen: ${resp.status}`);
                }
              };
              input.click();
            }}
          >Restore</button>
          <div className="header-status">
            <span className={`status-dot ${backendOnline ? 'online' : 'offline'}`} />
            {backendOnline ? 'Verbunden' : 'Offline'}
          </div>
        </div>
      </header>

      {/* Sidebar: zweckorientierte Navigation (datengetrieben) */}
      <aside className="studio-sidebar">
        <nav className="layer-nav">
          {NAV_SECTIONS.map((section, si) => (
            <div className="nav-section" key={section.title ?? `s${si}`}>
              {section.title && <div className="nav-section-label">{section.title}</div>}
              {section.items.map(item => (
                <button
                  key={item.id}
                  className={`layer-item ${layer === item.id ? 'active' : ''}`}
                  onClick={() => setLayer(item.id)}
                >
                  <span className="layer-badge">{NAV_ICONS[item.id]}</span>
                  <div>
                    <div className="layer-label">{item.label}</div>
                    {item.desc && <div className="layer-desc">{item.desc}</div>}
                  </div>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      {/* Main Content */}
      <main className="studio-main">
        {layer === 'home' && (
          <div>
            <div className="tabs" style={{ marginBottom: 16 }}>
              <button
                className={`tab ${homeTab === 'overview' ? 'active' : ''}`}
                onClick={() => setHomeTab('overview')}
              >Übersicht</button>
              <button
                className={`tab ${homeTab === 'info' ? 'active' : ''}`}
                onClick={() => setHomeTab('info')}
              >Architektur & Referenz</button>
            </div>
            {homeTab === 'overview' ? (
              <HomeOverview
                elements={elements}
                backendOnline={backendOnline}
                onNavigate={(id) => setLayer(id as Layer)}
                onOpenSnapshots={() => setSnapshotsOpen(true)}
              />
            ) : (
              <InfoView />
            )}
          </div>
        )}

        {layer !== 'home' && !backendOnline && (
          <div className="empty-state">
            <div className="empty-state-icon">{'\u26A0\uFE0F'}</div>
            <div className="empty-state-text">Backend nicht erreichbar</div>
            <div className="empty-state-hint">Stelle sicher, dass der Backend-Server auf Port 8000 läuft.</div>
          </div>
        )}

        {backendOnline && layer === 'identity' && (
          <>
          <SecurityLevelPicker />
          <ConfigTextEditor
            title="Identität & Schutz"
            subtitle="Schicht 1: Wer ist BOERDi und was tut er NIE? Diese Ebene gilt unbedingt und kann von keiner anderen Schicht überschrieben werden — sowohl als Anweisung im System-Prompt (Guardrails) als auch als Code-Gate vor jedem LLM-Call (Safety)."
            files={[
              { label: 'BOERDi Persona', desc: 'Persönlichkeit, Stimme, Verhalten', path: '01-base/base-persona.md' },
              { label: 'Guardrails (Prompt-Ebene)', desc: 'Unveränderliche Regeln R-01..R-10, gehen in jeden System-Prompt', path: '01-base/guardrails.md' },
              { label: 'Safety-Konfiguration (Code-Ebene)', desc: 'Risiko-Gating vor dem LLM: Crisis-Erkennung, blockierte Tools, Confidence-Anpassung', path: '01-base/safety-config.yaml' },
            ]}
            loadFile={loadFile}
            saveFile={saveFile}
          />
          </>
        )}

        {backendOnline && layer === 'domain' && (
          <ConfigTextEditor
            title="Domain-Wissen"
            subtitle="Schicht 2: Plattformwissen und konditionale Regeln für den WLO-Kontext. Im Gegensatz zu Schicht 1 wirken diese nur unter passenden Bedingungen (Persona/Intent/Page/Device)."
            files={[
              { label: 'Domain-Regeln', desc: 'Such-Strategie, Persona-Routing, Tool-Priorisierung', path: '02-domain/domain-rules.md' },
              { label: 'Plattform-Wissen', desc: 'WLO-Fakten, Statistiken, Geschichte, FAQ', path: '02-domain/wlo-plattform-wissen.md' },
              { label: 'Policy-Regeln', desc: 'Konditionale Compliance-Regeln (Match/Effect): Tool-Sperren, Disclaimer pro Persona/Intent', path: '02-domain/policy.yaml' },
              { label: 'Webseiten-Tour', desc: 'Geführte Besucher-Tour: Begrüßung, Schritt-Texte, Ziel-URLs, die 7 Besucher-Gruppen & das Gruppe→Angebot-Mapping. Verhalten/State-Machine liegt im Code (tour_service.py)', path: '01-base/website-tour.yaml' },
            ]}
            loadFile={loadFile}
            saveFile={saveFile}
          />
        )}

        {backendOnline && layer === 'canvas' && (
          <>
            {/* GUI editor for the 18 material types — typed CRUD via dedicated endpoint. */}
            <CanvasFormatsEditor />
            {/* Trigger / alias / persona-priority files keep the raw-YAML editor since
                they're shorter, less structured and edited rarely. */}
            <div style={{ marginTop: 24 }}>
              <ConfigTextEditor
                title="Trigger, Aliase & Priorisierung (Roh-YAML)"
                subtitle="Diese vier Dateien sind kurz und werden seltener angepasst — bleiben deshalb im Roh-Editor. Material-Typen oben haben ihren eigenen GUI-Editor."
                files={[
                  { label: 'Typ-Aliase & LRT-Mapping', desc: 'Welches Wort triggert welchen Typ + edu-sharing-LRT → Canvas-Typ für Remix', path: '05-canvas/type-aliases.yaml' },
                  { label: 'Create-Trigger-Verben', desc: 'Phrasen, die "Erstelle neues Material" signalisieren (inkl. indikativ: "brauche", "hätte gern") + Search-Gegenliste', path: '05-canvas/create-triggers.yaml' },
                  { label: 'Edit-Trigger-Verben', desc: 'Phrasen, die im Canvas-State als Refinement interpretiert werden ("mach es einfacher", "füge Lösungen hinzu") + "neues X"-Overrides', path: '05-canvas/edit-triggers.yaml' },
                  { label: 'Persona-Priorisierung', desc: 'Welche Personas sehen analytische Typen (Bericht/Factsheet/…) zuerst in der Canvas-Auswahl', path: '05-canvas/persona-priorities.yaml' },
                ]}
                loadFile={loadFile}
                saveFile={saveFile}
              />
            </div>
          </>
        )}

        {backendOnline && layer === 'patterns' && elements && (
          <PatternEditor
            elements={elements}
            loadFile={loadFile}
            saveFile={saveFile}
            onReload={loadElements}
            createFile={createFile}
          />
        )}

        {backendOnline && layer === 'dimensions' && elements && (
          <ElementEditor
            elements={elements}
            loadFile={loadFile}
            saveFile={saveFile}
            onReload={loadElements}
            createFile={createFile}
            appendToYaml={appendToYaml}
          />
        )}

        {backendOnline && layer === 'knowledge' && (
          <KnowledgeManager />
        )}

        {backendOnline && layer === 'sessions' && (
          <SessionsView />
        )}

        {backendOnline && layer === 'safety_logs' && (
          <SafetyLogsView />
        )}

        {backendOnline && layer === 'quality' && (
          <QualityView />
        )}

        {backendOnline && layer === 'evaluation' && (
          <EvaluationView />
        )}

        {backendOnline && layer === 'display' && (
          <>
            <DisplayRulesView loadFile={loadFile} saveFile={saveFile} />
            <div style={{ marginTop: 24 }}>
              <ConfigTextEditor
                title="Geräte-Konfiguration"
                subtitle="Max. angezeigte Ergebnisse pro Gerätetyp (Desktop/Tablet/Mobile) sowie der Anrede-Fallback pro Persona."
                files={[
                  { label: 'Geräte-Konfiguration', desc: 'Max Items pro Gerät, Formalität pro Persona', path: '01-base/device-config.yaml' },
                ]}
                loadFile={loadFile}
                saveFile={saveFile}
              />
            </div>
          </>
        )}

        {backendOnline && layer === 'privacy' && (
          <PrivacyView />
        )}

      </main>

      <SnapshotsModal
        open={snapshotsOpen}
        onClose={() => setSnapshotsOpen(false)}
        onAfterRestore={() => { setSnapshotsOpen(false); loadElements(); }}
      />
    </div>
  );
}
