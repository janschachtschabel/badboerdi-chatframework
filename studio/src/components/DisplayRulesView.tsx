'use client';

import { useState, useEffect, useCallback } from 'react';

/**
 * DisplayRulesView (Welle E, 2026-05-23) — Studio-Tab für Anzeige-
 * Steuerung. GUI-Editor für die wichtigsten Felder aus
 * 01-base/display-rules.yaml, plus ein YAML-Raw-Editor für Power-User.
 *
 * Backend-API:
 *   GET  /api/config/file?path=01-base/display-rules.yaml  → liefert YAML als Text
 *   POST /api/config/file                                   → speichert
 *
 * Da das Backend mtime-Cache nutzt, greift jede Änderung beim nächsten
 * Chat-Request — kein Neustart nötig.
 */
interface Props {
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
}

const PATH = '01-base/display-rules.yaml';

interface DisplayRulesShape {
  inline_documents: {
    enabled: boolean;
    font_size_percent: number;
    per_pattern: Record<string, boolean>;
  };
  single_content_box: {
    enabled: boolean;
    layout: 'card' | 'list';
  };
  groups: {
    themenseiten_max: number;
    sammlungen_max: number;
    materialien_max: number;
    materialien_max_lernpfad: number;
    webseiten_max: number;
  };
  inline_card_links: {
    limit: number;
    title_max_chars: number;
  };
  quick_replies: {
    max_count: number;
    inline_fallback_enabled: boolean;
  };
  prompt_anzeige_konsistenz: {
    enabled: boolean;
    exclude_patterns: string[];
  };
}

const DEFAULTS: DisplayRulesShape = {
  inline_documents: {
    enabled: true,
    font_size_percent: 85,
    per_pattern: { M09: true, M10: true, M11: true },
  },
  single_content_box: { enabled: true, layout: 'card' },
  groups: {
    themenseiten_max: 3,
    sammlungen_max: 3,
    materialien_max: 3,
    materialien_max_lernpfad: 5,
    webseiten_max: 3,
  },
  inline_card_links: { limit: 3, title_max_chars: 70 },
  quick_replies: { max_count: 4, inline_fallback_enabled: true },
  prompt_anzeige_konsistenz: { enabled: true, exclude_patterns: ['M04', 'M15'] },
};

// Minimal-YAML-Renderer für die wichtigsten Felder. Reicht für unsere
// Struktur — kein JS-YAML-Lib nötig im Studio-Bundle.
function renderYaml(rules: DisplayRulesShape): string {
  const perPat = Object.entries(rules.inline_documents.per_pattern)
    .map(([k, v]) => `      ${k}: ${v}`)
    .join('\n');
  const excl = (rules.prompt_anzeige_konsistenz.exclude_patterns || [])
    .map((p) => `      - ${p}`)
    .join('\n');

  return `# Display-Regeln — Studio-pflegbare Steuerung WAS und WIE im Chat
# angezeigt wird. Diese Datei wird vom Backend bei jedem Chat-Turn neu
# gelesen (mtime-Cache), Änderungen greifen sofort ohne Neustart.

display_rules:
  inline_documents:
    enabled: ${rules.inline_documents.enabled}
    font_size_percent: ${rules.inline_documents.font_size_percent}
    per_pattern:
${perPat}

  single_content_box:
    enabled: ${rules.single_content_box.enabled}
    layout: ${rules.single_content_box.layout}

  groups:
    themenseiten_max: ${rules.groups.themenseiten_max}
    sammlungen_max: ${rules.groups.sammlungen_max}
    materialien_max: ${rules.groups.materialien_max}
    materialien_max_lernpfad: ${rules.groups.materialien_max_lernpfad}
    webseiten_max: ${rules.groups.webseiten_max}

  inline_card_links:
    limit: ${rules.inline_card_links.limit}
    title_max_chars: ${rules.inline_card_links.title_max_chars}

  quick_replies:
    max_count: ${rules.quick_replies.max_count}
    inline_fallback_enabled: ${rules.quick_replies.inline_fallback_enabled}

  prompt_anzeige_konsistenz:
    enabled: ${rules.prompt_anzeige_konsistenz.enabled}
    exclude_patterns:
${excl}
`;
}

// Minimal-YAML-Parser (greift nur unsere bekannten Felder ab). Wir
// verlassen uns auf die Struktur von display-rules.yaml — bei kaputt
// editiertem YAML zeigt der Editor die Defaults und User kann via
// YAML-Tab repariert.
function parseYaml(text: string): DisplayRulesShape {
  const out = JSON.parse(JSON.stringify(DEFAULTS)) as DisplayRulesShape;
  const lines = text.split(/\r?\n/);

  const indentOf = (s: string) => s.length - s.replace(/^\s+/, '').length;
  const trim = (s: string) => s.trim();

  let section = '';
  let subkey = '';
  for (const raw of lines) {
    const line = raw.replace(/#.*$/, '');
    if (!line.trim()) continue;
    const indent = indentOf(raw);
    const t = trim(line);

    if (indent === 2 && t.endsWith(':')) {
      section = t.slice(0, -1);
      subkey = '';
      continue;
    }
    if (indent === 4 && t.endsWith(':') && !t.includes(' ')) {
      subkey = t.slice(0, -1);
      continue;
    }
    const m = t.match(/^([\w_]+):\s*(.*)$/);
    if (m && indent === 4) {
      const key = m[1];
      let val: any = m[2];
      if (val === 'true') val = true;
      else if (val === 'false') val = false;
      else if (/^-?\d+(\.\d+)?$/.test(val)) val = parseFloat(val);
      const sec = (out as any)[section];
      if (sec && key in sec) sec[key] = val;
      continue;
    }
    if (indent === 6 && section === 'inline_documents' && subkey === 'per_pattern') {
      const mm = t.match(/^([A-Z0-9_]+):\s*(true|false)$/);
      if (mm) out.inline_documents.per_pattern[mm[1]] = mm[2] === 'true';
    }
    if (indent === 6 && section === 'prompt_anzeige_konsistenz' && subkey === 'exclude_patterns') {
      const mm = t.match(/^-\s*(.+)$/);
      if (mm) {
        if (!out.prompt_anzeige_konsistenz.exclude_patterns.includes(mm[1]))
          out.prompt_anzeige_konsistenz.exclude_patterns.push(mm[1]);
      }
    }
  }
  return out;
}

export default function DisplayRulesView({ loadFile, saveFile }: Props) {
  const [rules, setRules] = useState<DisplayRulesShape>(DEFAULTS);
  const [yamlText, setYamlText] = useState('');
  const [tab, setTab] = useState<'gui' | 'yaml'>('gui');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const text = await loadFile(PATH);
      setYamlText(text);
      setRules(parseYaml(text));
    } catch {
      setYamlText(renderYaml(DEFAULTS));
      setRules(DEFAULTS);
    }
    setLoading(false);
  }, [loadFile]);

  useEffect(() => { reload(); }, [reload]);

  // Bei GUI-Edit auch yamlText neu rendern, damit User-Tab-Switch konsistent
  useEffect(() => {
    if (tab === 'gui') setYamlText(renderYaml(rules));
  }, [rules, tab]);

  const save = async (contentOverride?: string) => {
    setStatus('saving');
    const out = contentOverride ?? (tab === 'gui' ? renderYaml(rules) : yamlText);
    const ok = await saveFile(PATH, out);
    if (ok) {
      setStatus('saved');
      setYamlText(out);
      if (tab === 'yaml') setRules(parseYaml(out));
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  const updateRule = <T extends keyof DisplayRulesShape>(
    section: T, key: keyof DisplayRulesShape[T], value: any,
  ) => {
    setRules((prev) => ({
      ...prev,
      [section]: { ...(prev[section] as object), [key]: value },
    }));
  };

  if (loading) {
    return <div style={{ padding: 24, color: '#888' }}>Lade Anzeige-Regeln…</div>;
  }

  return (
    <div style={{ padding: 24, maxWidth: 920 }}>
      <h2 style={{ marginTop: 0 }}>🎨 Anzeige-Regeln</h2>
      <p style={{ color: '#666', maxWidth: 720, fontSize: 14 }}>
        Steuert <strong>was</strong> und <strong>wie</strong> der Chatbot im
        Widget anzeigt. Änderungen greifen sofort beim nächsten Chat-Turn
        (mtime-Cache, kein Backend-Neustart). Quelle:{' '}
        <code style={{ background: '#f4f4f8', padding: '2px 6px', borderRadius: 4 }}>
          {PATH}
        </code>
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button
          onClick={() => setTab('gui')}
          style={{
            padding: '8px 16px',
            background: tab === 'gui' ? '#1c4587' : '#e6e6ee',
            color: tab === 'gui' ? '#fff' : '#333',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          GUI-Editor
        </button>
        <button
          onClick={() => { setTab('yaml'); setYamlText(renderYaml(rules)); }}
          style={{
            padding: '8px 16px',
            background: tab === 'yaml' ? '#1c4587' : '#e6e6ee',
            color: tab === 'yaml' ? '#fff' : '#333',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          YAML (erweitert)
        </button>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => save()}
          disabled={status === 'saving'}
          style={{
            padding: '8px 18px',
            background: status === 'saved' ? '#28a745' : status === 'error' ? '#dc3545' : '#1c4587',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: status === 'saving' ? 'wait' : 'pointer',
            fontWeight: 600,
          }}
        >
          {status === 'saving' ? 'Speichere…'
            : status === 'saved' ? '✓ Gespeichert'
              : status === 'error' ? '✗ Fehler'
                : 'Speichern'}
        </button>
      </div>

      {tab === 'gui' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <Section
            title="📚 Gruppen-Boxen im Chat — Anzahl Treffer pro Box"
            desc={'Der Chatbot rendert seine Treffer in vier gleich aussehenden Boxen. Hier legst du fest, wie viele Treffer pro Box maximal angezeigt werden. Backend liefert nur so viel wie hier erlaubt — Frontend kürzt nicht clientseitig. Default je 3.'}
          >
            <NumberInput
              label="🗂️  Themenseiten"
              hint="Kuratierte WLO-Themenseiten (aus dem MCP-Repository)."
              value={rules.groups.themenseiten_max} min={1} max={20}
              onChange={(v) => updateRule('groups', 'themenseiten_max', v)}
            />
            <NumberInput
              label="📁  Sammlungen"
              hint="WLO-Sammlungen (aus dem MCP-Repository)."
              value={rules.groups.sammlungen_max} min={1} max={20}
              onChange={(v) => updateRule('groups', 'sammlungen_max', v)}
            />
            <NumberInput
              label="📦  Materialien (Einzelinhalte)"
              hint="OER-Ressourcen wie Videos, Arbeitsblätter, interaktive Übungen (aus dem MCP-Repository)."
              value={rules.groups.materialien_max} min={1} max={8}
              onChange={(v) => updateRule('groups', 'materialien_max', v)}
            />
            <NumberInput
              label="🛤️  Materialien bei Lernpfaden (M09)"
              hint="Lernpfade verlinken ihre Materialien im Pfad-Text — die Box darunter darf bis zu diesem Wert zeigen, damit alle verwendeten Inhalte abgedeckt sind."
              value={rules.groups.materialien_max_lernpfad} min={1} max={8}
              onChange={(v) => updateRule('groups', 'materialien_max_lernpfad', v)}
            />
            <NumberInput
              label="🌐  Webseiten-Inhalte"
              hint="RAG-Quellen — Unterseiten der WLO-Webseite, FAQ-Artikel, externe Referenzen aus den Wissensbereichen."
              value={rules.groups.webseiten_max} min={1} max={30}
              onChange={(v) => updateRule('groups', 'webseiten_max', v)}
            />
            <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px dashed #ddd' }}>
              <Toggle
                label="Materialien-Box komplett ausblenden (User erreicht sie nur über die Such-CTA)"
                checked={!rules.single_content_box.enabled}
                onChange={(v) => updateRule('single_content_box', 'enabled', !v)}
              />
            </div>
          </Section>

          <Section
            title="🗒️ Inline-Dokumente (Lernpfad / KI-Material)"
            desc="Lernpfade (M09) und KI-generierte Materialien (M10, M11) werden als gerahmte Box im Chat-Verlauf gerendert — optisch konsistent zu den Gruppen-Boxen, aber mit etwas kleinerer Schrift."
          >
            <Toggle
              label="Inline-Dokumente als Box anzeigen"
              checked={rules.inline_documents.enabled}
              onChange={(v) => updateRule('inline_documents', 'enabled', v)}
            />
            <NumberInput
              label="Schriftgröße in der Box (%)"
              hint="70–100 %. 85 % = ~14px bei 16px-Basis. Kleiner = mehr Inhalt sichtbar ohne Scrollen."
              value={rules.inline_documents.font_size_percent}
              min={70} max={100}
              onChange={(v) => updateRule('inline_documents', 'font_size_percent', v)}
            />
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {['M09', 'M10', 'M11'].map((id) => (
                <label key={id} style={{ display: 'inline-flex', gap: 6, fontSize: 13 }}>
                  <input
                    type="checkbox"
                    checked={!!rules.inline_documents.per_pattern[id]}
                    onChange={(e) => {
                      const next = { ...rules.inline_documents.per_pattern, [id]: e.target.checked };
                      updateRule('inline_documents', 'per_pattern', next);
                    }}
                  />
                  <code>{id}</code>{' '}
                  <span style={{ color: '#888' }}>
                    {id === 'M09' ? 'Lernpfad' : id === 'M10' ? 'KI-Material' : 'Iterative Edits'}
                  </span>
                </label>
              ))}
            </div>
          </Section>

          <Section
            title="💬 Quick-Replies"
            desc="Gesprächs-Vorschlags-Pillen unter der Bot-Antwort. Bei max_count: 0 sind alle Pillen ausgeblendet. Pro Pattern überschreibbar (Patterns → Antwort-Form: Modus Genau/Spekulativ/Keine + Anzahl)."
          >
            <NumberInput label="Max. Anzahl Pillen" value={rules.quick_replies.max_count} min={0} max={6} onChange={(v) => updateRule('quick_replies', 'max_count', v)} />
            <Toggle
              label="Inline-Fallback aktiv (Lotsen-Buttons werden als Markdown-Link am Ende eingebaut, wenn Pillen ausgeblendet)"
              checked={rules.quick_replies.inline_fallback_enabled}
              onChange={(v) => updateRule('quick_replies', 'inline_fallback_enabled', v)}
            />
          </Section>

          <Section
            title="🎯 Konsistenz Prompt ↔ Anzeige"
            desc="Wenn an: der LLM bekommt im finalen Response-Prompt nur Informationen über die im Chat sichtbaren Treffer — keine Halluzination über versteckte Materialien. Patterns in der Ausschluss-Liste dürfen weiter RAG-Synthese betreiben."
          >
            <Toggle
              label="Aktiv"
              checked={rules.prompt_anzeige_konsistenz.enabled}
              onChange={(v) => updateRule('prompt_anzeige_konsistenz', 'enabled', v)}
            />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
              <span style={{ color: '#666' }}>Ausschluss-Pattern (komma-getrennt):</span>
              <input
                type="text"
                value={rules.prompt_anzeige_konsistenz.exclude_patterns.join(', ')}
                onChange={(e) => {
                  const arr = e.target.value
                    .split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
                  updateRule('prompt_anzeige_konsistenz', 'exclude_patterns', arr);
                }}
                style={{ padding: '6px 10px', border: '1px solid #ddd', borderRadius: 4, fontFamily: 'monospace' }}
              />
              <span style={{ color: '#888', fontSize: 12 }}>
                Default: M04 (Wissens-Antwort), M15 (Orientierung) — beide brauchen RAG-Synthese.
              </span>
            </div>
          </Section>
        </div>
      )}

      {tab === 'yaml' && (
        <div>
          <p style={{ color: '#666', fontSize: 13 }}>
            Direkte YAML-Bearbeitung. Vorsicht: kaputt editierte YAML → Backend fällt auf Defaults zurück.
          </p>
          <textarea
            value={yamlText}
            onChange={(e) => setYamlText(e.target.value)}
            spellCheck={false}
            style={{
              width: '100%',
              minHeight: 480,
              fontFamily: 'Consolas, Monaco, monospace',
              fontSize: 13,
              padding: 12,
              border: '1px solid #ddd',
              borderRadius: 4,
              resize: 'vertical',
            }}
          />
        </div>
      )}
    </div>
  );
}

// ── Kleine UI-Helper ─────────────────────────────────────────────────
function Section({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div style={{ background: '#fafafd', border: '1px solid #e8e8ee', borderRadius: 8, padding: 16 }}>
      <h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>
      <p style={{ margin: '4px 0 14px', color: '#666', fontSize: 13 }}>{desc}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>{children}</div>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label style={{ display: 'inline-flex', gap: 8, alignItems: 'center', fontSize: 14, cursor: 'pointer' }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}</span>
    </label>
  );
}

function NumberInput({
  label, hint, value, min, max, onChange,
}: { label: string; hint?: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label style={{ display: 'inline-flex', gap: 10, alignItems: 'center', fontSize: 14 }}>
        <span style={{ width: 220 }}>{label}</span>
        <input
          type="number" value={value} min={min} max={max}
          onChange={(e) => {
            const n = parseInt(e.target.value, 10);
            if (Number.isFinite(n)) onChange(Math.max(min, Math.min(max, n)));
          }}
          style={{ width: 80, padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4 }}
        />
      </label>
      {hint && <span style={{ marginLeft: 230, fontSize: 12, color: '#888' }}>{hint}</span>}
    </div>
  );
}
