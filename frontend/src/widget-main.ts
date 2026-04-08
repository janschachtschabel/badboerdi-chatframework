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
import { createCustomElement } from '@angular/elements';
import { WidgetComponent } from './app/widget/widget.component';

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

  customElements.define('boerdi-chat', element);
})().catch((err) => console.error('[BOERDi Widget] bootstrap failed:', err));
