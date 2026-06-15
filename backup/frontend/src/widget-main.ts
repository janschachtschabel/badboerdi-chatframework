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
})().catch((err) => console.error('[BOERDi Widget] bootstrap failed:', err));
