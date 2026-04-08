'use client';

import type { Elements } from '@/app/page';

interface Props {
  elements: Elements | null;
  backendOnline: boolean;
  onNavigate: (layer: string) => void;
}

export default function HomeOverview({ elements, backendOnline, onNavigate }: Props) {
  const patternCount = elements?.patterns?.length ?? 0;
  const personaCount = elements?.personas?.length ?? 0;
  const intentCount = elements?.intents?.length ?? 0;
  const stateCount = elements?.states?.length ?? 0;
  const entityCount = elements?.entities?.length ?? 0;
  const signalCount = elements?.signals?.length ?? 0;

  const layers = [
    {
      num: 1,
      id: 'identity',
      icon: '\u{1F3E0}',
      label: 'Identität',
      desc: 'Wer ist der Chatbot? Grundlegende Persona, unveränderliche Guardrails und Geräte-Konfiguration.',
      stats: ['Persona-Datei', 'Guardrails', 'Geräte-Config'],
      color: '#2B6CB0',
    },
    {
      num: 2,
      id: 'domain',
      icon: '\u{1F310}',
      label: 'Domain',
      desc: 'Plattform-Wissen und domänenspezifische Regeln, die den Kontext des Chatbots definieren.',
      stats: ['Domain-Regeln', 'Plattform-Wissen'],
      color: '#2B6CB0',
    },
    {
      num: 3,
      id: 'patterns',
      icon: '\u{1F9E9}',
      label: 'Patterns',
      desc: '3-Phasen-Engine: Gate (Filterung) → Score (Gewichtung) → Modulate (Ausgabe-Anpassung).',
      stats: [`${patternCount} Patterns`],
      color: '#7C3AED',
    },
    {
      num: 4,
      id: 'dimensions',
      icon: '\u{1F3AD}',
      label: 'Dimensionen',
      desc: '5 Klassifikations-Dimensionen ordnen jeden Nutzer-Input ein und steuern die Pattern-Auswahl.',
      stats: [
        `${personaCount} Personas`,
        `${intentCount} Intents`,
        `${stateCount} States`,
        `${entityCount} Entities`,
        `${signalCount} Signale`,
      ],
      color: '#059669',
    },
    {
      num: 5,
      id: 'knowledge',
      icon: '\u{1F4DA}',
      label: 'Wissen',
      desc: 'RAG-Wissensbereiche füllen den Chatbot mit zusätzlichem Wissen. Always-on oder on-demand.',
      stats: ['RAG-Bereiche'],
      color: '#D97706',
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div className="page-title">BadBoerdi Studio</div>
        <div className="page-subtitle">
          Konfiguriere deinen Chatbot über die 5 Architektur-Schichten. Jede Schicht hat eine klare Verantwortung.
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

      {/* Architecture flow */}
      <div className="home-layers">
        {layers.map((l, idx) => (
          <div key={l.id}>
            <div
              className="home-layer-card"
              onClick={() => onNavigate(l.id)}
            >
              <div className="home-layer-header">
                <div className="home-layer-badge" style={{ background: l.color }}>{l.num}</div>
                <div>
                  <div className="home-layer-title">{l.icon} {l.label}</div>
                  <div className="home-layer-desc">{l.desc}</div>
                </div>
              </div>
              <div className="home-layer-stats">
                {l.stats.map((s, i) => (
                  <span key={i} className="tag tag-gray">{s}</span>
                ))}
              </div>
              <div className="home-layer-arrow">Bearbeiten &rarr;</div>
            </div>
            {idx < layers.length - 1 && (
              <div className="home-flow-connector">
                <svg width="20" height="28" viewBox="0 0 20 28">
                  <path d="M10 0 L10 20 L5 15 M10 20 L15 15" stroke="#CBD5E1" strokeWidth="2" fill="none"/>
                </svg>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Quick info */}
      {backendOnline && elements && (
        <div className="grid-2 mt-4">
          <div className="card">
            <div style={{ fontWeight: 600, fontSize: '.9rem', marginBottom: 8 }}>Verknüpfungen</div>
            <div className="text-sm text-muted" style={{ lineHeight: 1.8 }}>
              <strong>Patterns</strong> referenzieren Personas, Intents, States und Signale über Gates und Scoring-Regeln.
              Ändere die Verknüpfungen direkt im Pattern-Editor unter Schicht 3.<br/>
              <strong>Signale</strong> modulieren die Ausgabe (Ton, Länge, Detail) unabhängig vom gewählten Pattern.
            </div>
          </div>
          <div className="card">
            <div style={{ fontWeight: 600, fontSize: '.9rem', marginBottom: 8 }}>3-Phasen-Engine</div>
            <div className="text-sm text-muted" style={{ lineHeight: 1.8 }}>
              <strong>1. Gate:</strong> Filtert Patterns nach Persona, Intent und State.<br/>
              <strong>2. Score:</strong> Bewertet verbleibende Patterns anhand von Signalen, Priorität und Slots.<br/>
              <strong>3. Modulate:</strong> Passt Ton, Länge und Format anhand aktiver Signale an.
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
