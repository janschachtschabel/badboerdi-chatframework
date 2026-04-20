import { Component } from '@angular/core';
import { WidgetComponent } from './widget/widget.component';

/**
 * Dev-App (ng serve / localhost:4200).
 *
 * Rendert den gleichen WidgetComponent wie das produktive Custom-Element
 * `<boerdi-chat>` — inklusive Canvas-Shell, FAB und allen Layout-Regeln.
 * Dadurch ist Dev = Prod: wer im Dev-Server arbeitet sieht exakt das
 * Verhalten, das Embedder auf Drittseiten bekommen.
 *
 * Frueher wurde hier direkt `<badboerdi-chat>` eingebettet — das zeigte
 * zwar den Chat, aber kein Canvas (weil das Canvas-State im Widget sitzt).
 */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [WidgetComponent],
  template: `
    <boerdi-chat-widget
      [initialState]="'expanded'"
      [persistSession]="true"
      [primaryColor]="'#1c4587'"
      [position]="'bottom-right'">
    </boerdi-chat-widget>
  `,
  styles: [`
    :host { display: block; height: 100vh; background: #f5f7fb; }
  `],
})
export class AppComponent {}
