import { Component, inject, OnDestroy, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BotService } from '../../services/bot.service';
import { TableModule } from 'primeng/table';
import { InputTextModule } from 'primeng/inputtext';
import { IconFieldModule } from 'primeng/iconfield';
import { InputIconModule } from 'primeng/inputicon';
import { TagModule } from 'primeng/tag';
import { ButtonModule } from 'primeng/button';

@Component({
  selector: 'app-history',
  standalone: true,
  imports: [
    CommonModule,
    TableModule,
    InputTextModule,
    IconFieldModule,
    InputIconModule,
    TagModule,
    ButtonModule,
  ],
  templateUrl: './history.html',
})
export class History implements OnInit, OnDestroy {
  botService = inject(BotService);
  searchValue = signal<string>('');


  ngOnInit() {
    this.botService.startPolling(5);
  }

  ngOnDestroy() {
    this.botService.stopPolling();
  }

  getSeverity(pnl: number) {
    return pnl > 0 ? 'success' : 'danger';
  }
}
