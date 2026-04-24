'use client';

import type { Elements } from '@/app/page';

interface Props {
  elements: Elements | null;
  backendOnline: boolean;
  onNavigate: (layer: string) => void;
}

interface LayerCard {
  num: number;
  id: string;
  icon: string;
  label: string;
  headline: string;        // 1-line key capability (shown on every card, same position)
  primaryCount: string;    // big number/chip under the headline
  tags: string[];          // supplementary stat tags (max 4 for visual balance)
  color: string;
}

interface OpsCard {
  id: string;
  icon: string;
  label: string;
  desc: string;
  color: string;
}

export default function HomeOverview({ elements, backendOnline, onNavigate }: Props) {
  // ── Live counts (fallback to sensible hard-coded numbers if backend
  //     hasn't responded yet — keeps the home view readable on first load). ──
  const patternCount = elements?.patterns?.length ?? 26;
  const personaCount = elements?.personas?.length ?? 9;
  const intentCount = elements?.intents?.length ?? 14;
  const stateCount = elements?.states?.length ?? 12;
  const entityCount = elements?.entities?.length ?? 5;
  const signalCount = elements?.signals?.length ?? 17;

  const layers: LayerCard[] = [
    {
      num: 1, id: 'identity',
      icon: '\u{1F6E1}\uFE0F',
      label: 'Identität & Schutz',
      headline: 'Wer ist der Chatbot? Was darf er nie tun?',
      primaryCount: 'Persona · Guardrails · Safety',
      tags: ['Basis-Persona', 'Guardrails', 'Safety-Preset', 'Geräte-Config'],
      color: '#2B6CB0',
    },
    {
      num: 2, id: 'domain',
      icon: '\u{1F310}',
      label: 'Domain & Regeln',
      headline: 'Was weiß der Chatbot über WLO und seine Umgebung?',
      primaryCount: 'Plattform-Wissen + Policy',
      tags: ['Domain-Rules', 'WLO-Fachwissen', 'Policy-Matrix'],
      color: '#0891B2',
    },
    {
      num: 3, id: 'patterns',
      icon: '\u{1F9E9}',
      label: 'Patterns',
      headline: '3-Phasen-Engine: Gate → Score → Modulate.',
      primaryCount: `${patternCount} Patterns`,
      tags: ['Kern-Patterns', 'Canvas-Create', 'Feedback-Echo', 'Safety-Pattern'],
      color: '#7C3AED',
    },
    {
      num: 4, id: 'dimensions',
      icon: '\u{1F3AD}',
      label: 'Dimensionen',
      headline: 'Wie wird jeder Nutzer-Input klassifiziert?',
      primaryCount: `${personaCount} Personas · ${intentCount} Intents`,
      tags: [
        `${stateCount} States`,
        `${entityCount} Entities`,
        `${signalCount} Signale`,
        '5 Kontexte',
      ],
      color: '#059669',
    },
    {
      num: 5, id: 'canvas',
      icon: '\u{1F3A8}',
      label: 'Canvas-Formate',
      headline: 'Wie sieht KI-generierter Inhalt im Canvas aus?',
      primaryCount: '18 Material-Typen',
      tags: ['13 didaktisch', '5 analytisch', 'Typ-Aliase', 'Edit-/Create-Trigger'],
      color: '#EC4899',
    },
    {
      num: 6, id: 'knowledge',
      icon: '\u{1F4DA}',
      label: 'Wissen',
      headline: 'Welche Quellen liefern Faktenwissen zur Laufzeit?',
      primaryCount: 'RAG + MCP-Tools',
      tags: ['Always-on RAG', 'On-Demand RAG', 'MCP-Server', 'Themenseiten-Resolver'],
      color: '#D97706',
    },
  ];

  const opsCards: OpsCard[] = [
    {
      id: 'sessions',
      icon: '\u{1F4AC}',
      label: 'Sessions',
      desc: 'Chatverläufe durchsuchen, einsehen, gezielt löschen',
      color: '#334155',
    },
    {
      id: 'quality',
      icon: '\u{1F4CA}',
      label: 'Quality',
      desc: 'Pattern-Scoring, Confidence, Degradation-Rate',
      color: '#8B5CF6',
    },
    {
      id: 'safety_logs',
      icon: '\u{1F6E1}\uFE0F',
      label: 'Safety-Logs',
      desc: 'Risiko-Events, Rate-Limit, Legal-Klassifikator',
      color: '#EF4444',
    },
    {
      id: 'privacy',
      icon: '\u{1F512}',
      label: 'Datenschutz',
      desc: 'Logging-Toggles + Chatverlauf-Purge',
      color: '#059669',
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div className="page-title">BadBoerdi Studio</div>
        <div className="page-subtitle">
          Konfiguriere deinen Chatbot über 6 Architektur-Schichten und steuere
          den laufenden Betrieb. Alle Änderungen wirken live — ohne Backend-Restart.
        </div>
      </div>

      {/* Status banner */}
      {!backendOnline && (
        <div className="card mb-4" style={{ background: '#FEF2F2', borderColor: '#FECACA' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '1.2rem' }}>{'\u26A0\uFE0F'}</span>
            <div>
              <div style={{ fontWeight: 600, fontSize: '.88rem' }}>Backend nicht erreichbar</div>
              <div className="text-sm text-muted">Stelle sicher, dass der Backend-Server auf Port 8000 läuft.</div>
            </div>
          </div>
        </div>
      )}

      {/* ═══ Architektur ═══ */}
      <h2 className="home-section-title">Architektur</h2>

      <div className="home-layers">
        {layers.map((l, idx) => (
          <div key={l.id}>
            <button
              type="button"
              className="home-layer-card"
              onClick={() => onNavigate(l.id)}
            >
              <div className="home-layer-badge" style={{ background: l.color }}>{l.num}</div>
              <div className="home-layer-body">
                <div className="home-layer-title-row">
                  <span className="home-layer-title">
                    <span className="home-layer-icon">{l.icon}</span> {l.label}
                  </span>
                  <span className="home-layer-primary" style={{ color: l.color }}>
                    {l.primaryCount}
                  </span>
                </div>
                <div className="home-layer-desc">{l.headline}</div>
                <div className="home-layer-stats">
                  {l.tags.map((t, i) => (
                    <span key={i} className="tag tag-gray">{t}</span>
                  ))}
                </div>
              </div>
              <span className="home-layer-arrow" aria-hidden="true">›</span>
            </button>
            {idx < layers.length - 1 && (
              <div className="home-flow-connector" aria-hidden="true">
                <svg width="14" height="16" viewBox="0 0 14 16">
                  <path d="M7 0 L7 12 M3 8 L7 12 L11 8"
                        stroke="#CBD5E1" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ═══ Betrieb & Datenschutz ═══ */}
      <h2 className="home-section-title home-section-title--ops">
        Betrieb & Datenschutz
      </h2>
      <div className="home-ops-grid">
        {opsCards.map((o) => (
          <button
            key={o.id}
            type="button"
            className="home-ops-card"
            onClick={() => onNavigate(o.id)}
          >
            <span className="home-ops-icon" style={{ color: o.color }}>{o.icon}</span>
            <div className="home-ops-label">{o.label}</div>
            <div className="home-ops-desc">{o.desc}</div>
          </button>
        ))}
      </div>

      {/* ═══ 3-Phasen-Engine Info ═══ */}
      <div className="home-info-row">
        <div className="card home-info-card">
          <div className="home-info-title">🧮 3-Phasen-Engine</div>
          <ol className="home-info-list">
            <li>
              <strong>Gate:</strong> Filtert Patterns nach Persona, Intent und State.
              Preconditions (z.B. <code>thema + material_typ</code>) sind Hard-Gates.
            </li>
            <li>
              <strong>Score:</strong> Bewertet verbleibende Patterns anhand von Signalen,
              Priorität und Slot-Vollständigkeit.
            </li>
            <li>
              <strong>Modulate:</strong> Ton, Länge, Format werden anhand aktiver Signale
              deterministisch nachjustiert.
            </li>
          </ol>
        </div>
        <div className="card home-info-card">
          <div className="home-info-title">🔗 Verknüpfungen</div>
          <ul className="home-info-list">
            <li>
              <strong>Patterns</strong> referenzieren Personas, Intents, States und Signale
              über Gates und Scoring-Regeln — editierbar unter Schicht 3.
            </li>
            <li>
              <strong>Signale</strong> modulieren Ton, Länge und Detail unabhängig vom
              gewählten Pattern.
            </li>
            <li>
              <strong>Canvas-Formate</strong> greifen nur bei den Intents INT-W-11
              (Create) und INT-W-12 (Edit).
            </li>
            <li>
              <strong>Themenseiten-Resolver</strong> löst <code>node_id</code> und
              <code>topic_page_slug</code> aus <code>page_context</code> beim ersten
              Turn über MCP zu Metadaten auf.
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
