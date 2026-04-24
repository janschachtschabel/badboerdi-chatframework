'use client';

import { useState, useEffect, useCallback } from 'react';
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
import { SnapshotsModal } from '@/components/SnapshotsModal';

// ── Types ────────────────────────────────────────────────────────────
type Layer = 'home' | 'identity' | 'domain' | 'patterns' | 'dimensions' | 'canvas' | 'knowledge' | 'sessions' | 'safety_logs' | 'quality' | 'evaluation' | 'privacy' | 'info';

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
  priority?: number;
  gate_personas?: string[];
  gate_states?: string[];
  gate_intents?: string[];
  signal_high_fit?: string[];
  signal_medium_fit?: string[];
  signal_low_fit?: string[];
  page_bonus?: string[];
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
  core_rule?: string;
  file?: string;
  [key: string]: any;
}

export interface PersonaData {
  id: string;
  label: string;
  file?: string;
  description?: string;
  hints?: string[];
}

export interface IntentData {
  id: string;
  label: string;
  description?: string;
  file?: string;
}

export interface StateData {
  id: string;
  label: string;
  description?: string;
  cluster?: string;
  file?: string;
}

export interface SignalData {
  id: string;
  dimension?: string;
  modulations?: Record<string, any>;
  file?: string;
}

export interface EntityData {
  id: string;
  label?: string;
  type?: string;
  examples?: string[];
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

// ── Layer definitions ────────────────────────────────────────────────
const LAYERS: { id: Layer; num: number; icon: string; label: string; desc: string }[] = [
  { id: 'identity',   num: 1, icon: '🛡️', label: 'Identität & Schutz', desc: 'Persona, Guardrails, Safety, Geräte' },
  { id: 'domain',     num: 2, icon: '🌐', label: 'Domain & Regeln',    desc: 'Plattform-Wissen, Policy, Kontexte' },
  { id: 'patterns',   num: 3, icon: '🧩', label: 'Patterns',           desc: 'Gesprächsmuster' },
  { id: 'dimensions', num: 4, icon: '🎭', label: 'Dimensionen',        desc: 'Personas, Intents, States…' },
  { id: 'canvas',     num: 5, icon: '🎨', label: 'Canvas-Formate',     desc: 'Material-Typen, Aliase, Persona-Priorität' },
  { id: 'knowledge',  num: 6, icon: '📚', label: 'Wissen',             desc: 'MCP-Tools & RAG-Wissensbereiche' },
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

  return (
    <div className="studio-layout">
      {/* Header */}
      <header className="studio-header">
        <h1 onClick={() => setLayer('home')} style={{ cursor: 'pointer' }}>BadBoerdi Studio</h1>
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

      {/* Sidebar: 5-Layer Navigation */}
      <aside className="studio-sidebar">
        <div className="layer-nav">
          <button
            className={`layer-item home-nav-item ${layer === 'home' ? 'active' : ''}`}
            onClick={() => setLayer('home')}
          >
            <span className="layer-badge" style={{ background: '#6B7280', color: '#fff' }}>{'\u2302'}</span>
            <div>
              <div className="layer-label">Übersicht</div>
              <div className="layer-desc">Start & Architektur</div>
            </div>
          </button>
          <div className="nav-divider" />
          <div className="nav-section-label">Architektur-Schichten</div>
          {LAYERS.map(l => (
            <button
              key={l.id}
              className={`layer-item ${layer === l.id ? 'active' : ''}`}
              onClick={() => setLayer(l.id)}
            >
              <span className="layer-badge">{l.num}</span>
              <div>
                <div className="layer-label">{l.icon} {l.label}</div>
                <div className="layer-desc">{l.desc}</div>
              </div>
            </button>
          ))}
          <div className="nav-divider" />
          <button
            className={`layer-item ${layer === 'sessions' ? 'active' : ''}`}
            onClick={() => setLayer('sessions')}
          >
            <span className="layer-badge" style={{ background: '#6B7280', color: '#fff' }}>S</span>
            <div>
              <div className="layer-label">Sessions</div>
              <div className="layer-desc">Gesprächsverläufe</div>
            </div>
          </button>
          <button
            className={`layer-item ${layer === 'safety_logs' ? 'active' : ''}`}
            onClick={() => setLayer('safety_logs')}
          >
            <span className="layer-badge" style={{ background: '#ef4444', color: '#fff' }}>🛡</span>
            <div>
              <div className="layer-label">Safety-Logs</div>
              <div className="layer-desc">Risiko-Events & Rate Limits</div>
            </div>
          </button>
          <button
            className={`layer-item ${layer === 'quality' ? 'active' : ''}`}
            onClick={() => setLayer('quality')}
          >
            <span className="layer-badge" style={{ background: '#8B5CF6', color: '#fff' }}>📊</span>
            <div>
              <div className="layer-label">Quality</div>
              <div className="layer-desc">Pattern-Scoring & Analytics</div>
            </div>
          </button>
          <button
            className={`layer-item ${layer === 'evaluation' ? 'active' : ''}`}
            onClick={() => setLayer('evaluation')}
          >
            <span className="layer-badge" style={{ background: '#EC4899', color: '#fff' }}>🧪</span>
            <div>
              <div className="layer-label">Evaluation</div>
              <div className="layer-desc">Persona-Dialoge automatisch testen</div>
            </div>
          </button>
          <button
            className={`layer-item ${layer === 'privacy' ? 'active' : ''}`}
            onClick={() => setLayer('privacy')}
          >
            <span className="layer-badge" style={{ background: '#059669', color: '#fff' }}>🔒</span>
            <div>
              <div className="layer-label">Datenschutz</div>
              <div className="layer-desc">Logging-Optionen & Purge</div>
            </div>
          </button>
          <div className="nav-divider" />
          <button
            className={`layer-item ${layer === 'info' ? 'active' : ''}`}
            onClick={() => setLayer('info')}
          >
            <span className="layer-badge" style={{ background: '#6B7280', color: '#fff' }}>ℹ️</span>
            <div>
              <div className="layer-label">Info</div>
              <div className="layer-desc">Architektur-Referenz</div>
            </div>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="studio-main">
        {layer === 'home' && (
          <HomeOverview
            elements={elements}
            backendOnline={backendOnline}
            onNavigate={(id) => setLayer(id as Layer)}
          />
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
              { label: 'Geräte-Konfiguration', desc: 'Max Items pro Gerät, Formalität pro Persona', path: '01-base/device-config.yaml' },
            ]}
            loadFile={loadFile}
            saveFile={saveFile}
          />
          </>
        )}

        {backendOnline && layer === 'domain' && (
          <ConfigTextEditor
            title="Domain & Regeln"
            subtitle="Schicht 2: Plattformwissen und konditionale Regeln für den WLO-Kontext. Im Gegensatz zu Schicht 1 wirken diese Regeln nur unter passenden Bedingungen (Persona/Intent/Page/Device)."
            files={[
              { label: 'Domain-Regeln', desc: 'Such-Strategie, Persona-Routing, Tool-Priorisierung', path: '02-domain/domain-rules.md' },
              { label: 'Plattform-Wissen', desc: 'WLO-Fakten, Statistiken, Geschichte, FAQ', path: '02-domain/wlo-plattform-wissen.md' },
              { label: 'Policy-Regeln', desc: 'Konditionale Compliance-Regeln (Match/Effect): Tool-Sperren, Disclaimer pro Persona/Intent', path: '02-domain/policy.yaml' },
              { label: 'Kontexte', desc: 'Benannte Konversations-Kontexte (Page/Device-Trigger) für Pattern-Fit & UI-Filterung', path: '04-contexts/contexts.yaml' },
            ]}
            loadFile={loadFile}
            saveFile={saveFile}
          />
        )}

        {backendOnline && layer === 'canvas' && (
          <ConfigTextEditor
            title="Canvas-Formate"
            subtitle="Die Material-Typen, die BOERDi im Canvas-Bereich rechts vom Chat erzeugen kann — inklusive Aliase, Create-Trigger-Verben und Persona-Priorisierung. Änderungen wirken live, ohne Backend-Restart."
            files={[
              { label: 'Material-Typen', desc: '18 Canvas-Output-Formate (Arbeitsblatt, Quiz, Bericht, …) mit Struktur-Vorgabe und Kategorie (didaktisch/analytisch)', path: '05-canvas/material-types.yaml' },
              { label: 'Typ-Aliase & LRT-Mapping', desc: 'Welches Wort triggert welchen Typ + edu-sharing-LRT → Canvas-Typ für Remix', path: '05-canvas/type-aliases.yaml' },
              { label: 'Create-Trigger-Verben', desc: 'Phrasen, die "Erstelle neues Material" signalisieren (inkl. indikativ: "brauche", "hätte gern") + Search-Gegenliste', path: '05-canvas/create-triggers.yaml' },
              { label: 'Edit-Trigger-Verben', desc: 'Phrasen, die im Canvas-State als Refinement interpretiert werden ("mach es einfacher", "füge Lösungen hinzu") + "neues X"-Overrides, die trotz Canvas-State zurück auf Create gehen', path: '05-canvas/edit-triggers.yaml' },
              { label: 'Persona-Priorisierung', desc: 'Welche Personas sehen analytische Typen (Bericht/Factsheet/…) zuerst in der Canvas-Auswahl', path: '05-canvas/persona-priorities.yaml' },
            ]}
            loadFile={loadFile}
            saveFile={saveFile}
          />
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

        {backendOnline && layer === 'privacy' && (
          <PrivacyView />
        )}

        {layer === 'info' && (
          <InfoView />
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
