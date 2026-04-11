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

// ── Types ────────────────────────────────────────────────────────────
type Layer = 'home' | 'identity' | 'domain' | 'patterns' | 'dimensions' | 'knowledge' | 'sessions' | 'safety_logs';

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
  { id: 'knowledge',  num: 5, icon: '📚', label: 'Wissen',             desc: 'RAG-Wissensbereiche' },
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

  const exportAll = async () => {
    try {
      const resp = await fetch('/api/config/export');
      if (!resp.ok) return;
      const data = await resp.json();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'badboerdi-config-export.json'; a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
  };

  const importAll = () => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = '.json';
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const text = await file.text();
      const data = JSON.parse(text);
      await fetch('/api/config/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ files: data }),
      });
      await loadElements();
    };
    input.click();
  };

  return (
    <div className="studio-layout">
      {/* Header */}
      <header className="studio-header">
        <h1 onClick={() => setLayer('home')} style={{ cursor: 'pointer' }}>BadBoerdi Studio</h1>
        <div className="header-right">
          <button className="btn btn-header btn-sm" onClick={importAll}>Import</button>
          <button className="btn btn-header btn-sm" onClick={exportAll}>Export</button>
          <button
            className="btn btn-header btn-sm"
            title="Komplette Konfiguration als ZIP herunterladen"
            onClick={() => { window.location.href = '/api/config/backup'; }}
          >Backup</button>
          <button
            className="btn btn-header btn-sm"
            title="Konfiguration aus ZIP wiederherstellen"
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.accept = '.zip';
              input.onchange = async (e: any) => {
                const file = e.target.files?.[0];
                if (!file) return;
                const wipe = confirm('Vorhandene Konfiguration vorher LÖSCHEN?\n\nOK = wipe + restore\nAbbrechen = nur mergen');
                const fd = new FormData();
                fd.append('file', file);
                const resp = await fetch(`/api/config/restore?wipe=${wipe ? 'true' : 'false'}`, {
                  method: 'POST',
                  body: fd,
                });
                if (resp.ok) {
                  const data = await resp.json();
                  alert(`Restore OK: ${data.files_extracted} Dateien wiederhergestellt.`);
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
      </main>
    </div>
  );
}
