/**
 * BOERDi Widget Bootstrap
 *
 * Builds a single-file Custom Element <boerdi-chat> that can be embedded
 * on any host page via:
 *
 *   <script src="/widget/boerdi-widget.js" defer></script>
 *   <boerdi-chat api-url="https://api.wlo.de"></boerdi-chat>
 */
import 'zone.js';
import { createApplication } from '@angular/platform-browser';
import { createCustomElement, NgElement } from '@angular/elements';
import { WidgetComponent } from './app/widget/widget.component';

/**
 * Auf dem `<boerdi-chat>`-Element zur Verfügung gestellte Methoden,
 * damit die einbettende Seite das Panel direkt steuern kann — ohne
 * den DOM-Hack `boerdiChatEl.shadowRoot.querySelector('button').click()`.
 *
 * Beispiel-Nutzung in der Host-Seite:
 * ```js
 * const el = document.querySelector('boerdi-chat');
 * el.openChatbot();   // Panel öffnen
 * el.closeChatbot();  // Panel schließen
 * el.toggleChatbot(); // Toggle
 * el.isChatbotOpen(); // -> boolean
 * ```
 *
 * Alternative: HTML-Attribut zur Laufzeit ändern (greift dank
 * ``ngOnChanges`` im WidgetComponent):
 * ```js
 * el.setAttribute('initial-state', 'expanded');
 * el.setAttribute('initial-state', 'collapsed');
 * ```
 */
type BoerdiChatPublicMethods = 'openChatbot' | 'closeChatbot' | 'toggleChatbot' | 'isChatbotOpen';
const PUBLIC_METHODS: ReadonlyArray<BoerdiChatPublicMethods> = [
  'openChatbot', 'closeChatbot', 'toggleChatbot', 'isChatbotOpen',
];

(async () => {
  // Avoid double registration when script is loaded multiple times
  if (customElements.get('boerdi-chat')) {
    return;
  }

  const app = await createApplication({
    providers: [],
  });

  const element = createCustomElement(WidgetComponent, {
    injector: app.injector,
  });

  // Angular's ``createCustomElement`` exposed nur @Input/@Output am
  // Element — Methoden bleiben am inneren Component-Proxy. Wir hängen
  // sie hier manuell an den Element-Prototyp, sodass sie als normale
  // Methoden des `<boerdi-chat>`-DOM-Knotens aufrufbar sind.
  const proto = element.prototype as NgElement & Record<string, unknown>;
  for (const m of PUBLIC_METHODS) {
    if (typeof proto[m] === 'function') continue;  // schon vorhanden
    proto[m] = function (this: NgElement, ...args: unknown[]) {
      // Angular 17+: der Component-Ref liegt unter
      // ``_ngElementStrategy.componentRef``, NICHT direkt auf der Element-
      // Instanz. Frühere Versionen hatten ``element.componentRef`` — wir
      // probieren beide Pfade, damit der Wrapper version-stable bleibt.
      // Vor dem connectedCallback ist beides ``undefined`` — wir geben
      // dann ``undefined`` zurück (kein Crash bei frühen Aufrufen).
      const self = this as unknown as {
        _ngElementStrategy?: { componentRef?: { instance: Record<string, unknown> } };
        componentRef?: { instance: Record<string, unknown> };
      };
      const compRef = self._ngElementStrategy?.componentRef || self.componentRef;
      const instance = compRef?.instance;
      const fn = instance && typeof instance[m] === 'function' ? instance[m] : null;
      if (typeof fn !== 'function') return undefined;
      return (fn as (...a: unknown[]) => unknown).apply(instance, args);
    };
  }

  customElements.define('boerdi-chat', element);

  // Defensive: nur die ERSTE <boerdi-chat>-Instanz auf der Seite rendern.
  // Hintergrund (Welle C Sprint 7, 2026-05-19): WordPress-Embed-Setups wie
  // wp-test.wirlernenonline.de zogen sich gelegentlich zwei Chatbots
  // gestapelt rein, weil das Widget-Snippet sowohl im Theme-Header als
  // auch in einem Content-Block eingebunden war. Statt sich auf saubere
  // Host-Konfiguration zu verlassen, blendet das Widget alle Duplikate
  // aus (display:none auf dem zweiten+ Element) und logt eine Warnung.
  //
  // Wir nutzen einen MutationObserver, weil WordPress-Sites Tags
  // dynamisch via JavaScript einfügen können (Lazy-Loading, AJAX-Reload
  // bestimmter Layout-Blöcke). Ein einmaliger Check beim Bootstrap reicht
  // nicht — wir müssen auf Insert-Events reagieren.
  const enforceSingleInstance = () => {
    const all = document.querySelectorAll('boerdi-chat');
    if (all.length <= 1) return;
    for (let i = 1; i < all.length; i++) {
      const el = all[i] as HTMLElement;
      if (el.dataset['boerdiDuplicateHidden'] === '1') continue;
      el.dataset['boerdiDuplicateHidden'] = '1';
      el.style.display = 'none';
      console.warn(
        '[BOERDi Widget] Duplicate <boerdi-chat> hidden — nur die erste Instanz rendert.',
        el,
      );
    }
  };
  enforceSingleInstance();
  if (typeof MutationObserver !== 'undefined' && document.body) {
    const mo = new MutationObserver(enforceSingleInstance);
    mo.observe(document.body, { childList: true, subtree: true });
  }
})().catch((err) => console.error('[BOERDi Widget] bootstrap failed:', err));
