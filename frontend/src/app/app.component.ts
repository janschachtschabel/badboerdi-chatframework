import { Component } from '@angular/core';
import { ChatComponent } from './chat/chat.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [ChatComponent],
  template: `<badboerdi-chat></badboerdi-chat>`,
  styles: [`:host { display: block; height: 100vh; }`],
})
export class AppComponent {}
