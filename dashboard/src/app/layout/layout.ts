import { Component, inject } from '@angular/core';
import { RouterOutlet, RouterModule } from '@angular/router';
import { ButtonModule } from 'primeng/button';
import { BotService } from '../services/bot.service';
import { NgClass } from '@angular/common';
import { ToastModule } from 'primeng/toast';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterOutlet, RouterModule, ButtonModule, NgClass, ToastModule],
  templateUrl: './layout.html'
})
export class Layout {
  botService = inject(BotService);
}
