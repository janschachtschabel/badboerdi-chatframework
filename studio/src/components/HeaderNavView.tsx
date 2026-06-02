'use client';

import { useState, useEffect, useCallback, type CSSProperties } from 'react';

/**
 * HeaderNavView (Welle E) — Studio-Editor für die optionalen Kopfzeilen-
 * Navigations-Buttons des Widgets (Home / Fachportale / Suche). Sie erscheinen
 * links vom „Neuer Chat"-Button im Widget-Header.
 *
 * Backend-API (generischer Datei-Editor, wie DisplayRulesView):
 *   GET  /api/config/file?path=01-base/header-nav.yaml  → liefert YAML als Text
 *   PUT  /api/config/file                               → speichert
 *
 * Das Widget liest die Liste beim Boot über /api/config/guide-mode (Feld
 * ``header_nav``). YAML-Änderungen greifen beim nächsten Widget-Reload
 * (mtime-Cache, kein Backend-Neustart). An Links zu vertrauenswürdigen
 * WLO-Hosts hängt das Widget dynamisch ``?bsid=<sid>`` an.
 */
interface Props {
  loadFile: (path: string) => Promise<string>;
  saveFile: (path: string, content: string) => Promise<boolean>;
}

const PATH = '01-base/header-nav.yaml';

interface NavBtn {
  id: string;
  enabled: boolean;
  label: string;
  icon: string;
  url: string;
  new_tab: boolean;
}

const DEFAULTS: NavBtn[] = [
  { id: 'home', enabled: true, label: 'Startseite', icon: 'home', url: 'https://wp-test.wirlernenonline.de/home/', new_tab: false },
  { id: 'fachportale', enabled: true, label: 'Fachportale', icon: 'topic', url: 'https://wp-test.wirlernenonline.de/bildungsinhalte/fachportale/', new_tab: false },
  { id: 'suche', enabled: true, label: 'Suche im WLO-Repository', icon: 'search', url: 'https://repository.staging.openeduhub.net/edu-sharing/components/search', new_tab: false },
];

// Bekannte Icon-Namen (shared/icons.ts) für das Dropdown. Freitext bleibt
// erlaubt (icon kann jeder Name aus icons.ts sein, unbekannt → Fallback).
const ICON_CHOICES = ['home', 'topic', 'search', 'school', 'language', 'explore', 'auto_stories', 'menu_book'];

function escYaml(s: string): string {
  return (s || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function renderYaml(buttons: NavBtn[]): string {
  const items = buttons.map((b) => (
    `    - id: ${(b.id || 'btn').trim()}\n` +
    `      enabled: ${b.enabled}\n` +
    `      label: "${escYaml(b.label)}"\n` +
    `      icon: ${(b.icon || 'explore').trim()}\n` +
    `      url: "${escYaml(b.url)}"\n` +
    `      new_tab: ${b.new_tab}`
  )).join('\n\n');
  return `# Optionale Kopfzeilen-Navigations-Buttons im Widget (Studio-pflegbar).
# Erscheinen LINKS vom „Neuer Chat"-Button, gleiches outlined-neutrales Design.
# An Trusted-WLO-Hosts hängt das Widget dynamisch ?bsid=<sid> an, damit die
# Chat-Session auf der Zielseite weiterläuft (sofern das Widget dort eingebettet
# ist). icon: Name aus shared/icons.ts. new_tab: true → neuer Tab.

header_nav:
  buttons:
${items || '    []'}
`;
}

function unquote(v: string): string {
  let s = (v || '').trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    s = s.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }
  return s;
}

function parseYaml(text: string): NavBtn[] {
  const lines = (text || '').split(/\r?\n/);
  const out: NavBtn[] = [];
  let cur: Partial<NavBtn> | null = null;
  const flush = () => {
    if (cur && (cur.url || cur.id)) {
      out.push({
        id: String(cur.id || `btn${out.length}`),
        enabled: cur.enabled !== false,
        label: String(cur.label ?? ''),
        icon: String(cur.icon || 'explore'),
        url: String(cur.url ?? ''),
        new_tab: cur.new_tab === true,
      });
    }
    cur = null;
  };
  for (const raw of lines) {
    const m = raw.match(/^\s*-\s+id:\s*(.*)$/);
    if (m) { flush(); cur = { id: unquote(m[1]) }; continue; }
    if (!cur) continue;
    const kv = raw.match(/^\s+([a-z_]+):\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const val = kv[2].trim();
    if (key === 'enabled') cur.enabled = val === 'true';
    else if (key === 'new_tab') cur.new_tab = val === 'true';
    else if (key === 'label') cur.label = unquote(val);
    else if (key === 'icon') cur.icon = unquote(val);
    else if (key === 'url') cur.url = unquote(val);
  }
  flush();
  return out.length ? out : JSON.parse(JSON.stringify(DEFAULTS));
}

export default function HeaderNavView({ loadFile, saveFile }: Props) {
  const [buttons, setButtons] = useState<NavBtn[]>(DEFAULTS);
  const [yamlText, setYamlText] = useState('');
  const [tab, setTab] = useState<'gui' | 'yaml'>('gui');
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const text = await loadFile(PATH);
      if (text && text.trim()) {
        setYamlText(text);
        setButtons(parseYaml(text));
      } else {
        setButtons(DEFAULTS);
        setYamlText(renderYaml(DEFAULTS));
      }
    } catch {
      setButtons(DEFAULTS);
      setYamlText(renderYaml(DEFAULTS));
    }
    setLoading(false);
  }, [loadFile]);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    if (tab === 'gui') setYamlText(renderYaml(buttons));
  }, [buttons, tab]);

  const save = async () => {
    setStatus('saving');
    const out = tab === 'gui' ? renderYaml(buttons) : yamlText;
    const ok = await saveFile(PATH, out);
    if (ok) {
      setStatus('saved');
      setYamlText(out);
      if (tab === 'yaml') setButtons(parseYaml(out));
      setTimeout(() => setStatus('idle'), 2000);
    } else {
      setStatus('error');
    }
  };

  const updateBtn = (idx: number, key: keyof NavBtn, value: string | boolean) => {
    setButtons((prev) => prev.map((b, i) => (i === idx ? ({ ...b, [key]: value } as NavBtn) : b)));
  };

  const tabBtn = (which: 'gui' | 'yaml', text: string) => (
    <button
      onClick={() => { setTab(which); if (which === 'yaml') setYamlText(renderYaml(buttons)); }}
      style={{
        padding: '8px 16px',
        background: tab === which ? '#1c4587' : '#e6e6ee',
        color: tab === which ? '#fff' : '#333',
        border: 'none', borderRadius: 6, cursor: 'pointer',
      }}
    >{text}</button>
  );

  if (loading) {
    return <div style={{ padding: 24, color: '#888' }}>Lade Kopfzeilen-Navigation…</div>;
  }

  const inputStyle: CSSProperties = {
    width: '100%', padding: '6px 8px', borderRadius: 6,
    border: '1px solid #cbd5e1', fontSize: 13, boxSizing: 'border-box',
  };
  const labelStyle: CSSProperties = { fontSize: 12, color: '#555', display: 'block', marginBottom: 3 };

  return (
    <div style={{ padding: 24, maxWidth: 920 }}>
      <h2 style={{ marginTop: 0 }}>🧭 Kopfzeilen-Navigation</h2>
      <p style={{ color: '#666', maxWidth: 760, fontSize: 14 }}>
        Optionale Buttons in der Widget-Kopfzeile (links vom „Neuer Chat"-Button).
        Jeder Button einzeln an-/abschaltbar mit frei wählbarer Ziel-URL. An
        Links zu vertrauenswürdigen WLO-Hosts hängt das Widget automatisch die
        Session-ID (<code>?bsid=</code>) an, damit der Chat auf der Zielseite
        weiterläuft. Quelle:{' '}
        <code style={{ background: '#f4f4f8', padding: '2px 6px', borderRadius: 4 }}>{PATH}</code>
        {' '}— greift beim nächsten Widget-Reload.
      </p>

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        {tabBtn('gui', 'GUI-Editor')}
        {tabBtn('yaml', 'YAML (erweitert)')}
        <div style={{ flex: 1 }} />
        <button
          onClick={save}
          disabled={status === 'saving'}
          style={{
            padding: '8px 18px',
            background: status === 'saved' ? '#28a745' : status === 'error' ? '#dc3545' : '#1c4587',
            color: '#fff', border: 'none', borderRadius: 6,
            cursor: status === 'saving' ? 'wait' : 'pointer', fontWeight: 600,
          }}
        >
          {status === 'saving' ? 'Speichere…' : status === 'saved' ? '✓ Gespeichert' : status === 'error' ? '✗ Fehler' : 'Speichern'}
        </button>
      </div>

      {tab === 'gui' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {buttons.map((b, i) => (
            <div key={b.id || i} style={{
              border: '1px solid #e2e8f0', borderRadius: 10, padding: 16,
              background: b.enabled ? '#fff' : '#f8fafc',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
                  <input type="checkbox" checked={b.enabled}
                    onChange={(e) => updateBtn(i, 'enabled', e.target.checked)} />
                  Button anzeigen
                </label>
                <code style={{ marginLeft: 'auto', color: '#94a3b8', fontSize: 12 }}>id: {b.id}</code>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={labelStyle}>Beschriftung (Tooltip)</label>
                  <input style={inputStyle} value={b.label}
                    onChange={(e) => updateBtn(i, 'label', e.target.value)} />
                </div>
                <div>
                  <label style={labelStyle}>Icon</label>
                  <input style={inputStyle} value={b.icon} list={`icons-${i}`}
                    onChange={(e) => updateBtn(i, 'icon', e.target.value)} />
                  <datalist id={`icons-${i}`}>
                    {ICON_CHOICES.map((c) => <option key={c} value={c} />)}
                  </datalist>
                </div>
                <div style={{ gridColumn: '1 / span 2' }}>
                  <label style={labelStyle}>Ziel-URL</label>
                  <input style={inputStyle} value={b.url} placeholder="https://…"
                    onChange={(e) => updateBtn(i, 'url', e.target.value)} />
                </div>
                <div style={{ gridColumn: '1 / span 2' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#333' }}>
                    <input type="checkbox" checked={b.new_tab}
                      onChange={(e) => updateBtn(i, 'new_tab', e.target.checked)} />
                    In neuem Tab öffnen (sonst gleicher Tab — Chat „wandert mit")
                  </label>
                </div>
              </div>
            </div>
          ))}
          <p style={{ color: '#94a3b8', fontSize: 12, margin: 0 }}>
            Buttons hinzufügen/entfernen über den YAML-Editor (oben).
          </p>
        </div>
      )}

      {tab === 'yaml' && (
        <textarea
          value={yamlText}
          onChange={(e) => setYamlText(e.target.value)}
          spellCheck={false}
          style={{
            width: '100%', minHeight: 320, fontFamily: 'monospace', fontSize: 13,
            padding: 12, borderRadius: 8, border: '1px solid #cbd5e1', boxSizing: 'border-box',
          }}
        />
      )}
    </div>
  );
}
