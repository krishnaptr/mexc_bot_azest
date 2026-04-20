import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { CardModule } from 'primeng/card';
import { ButtonModule } from 'primeng/button';
import { BadgeModule } from 'primeng/badge';
import { CommonModule } from '@angular/common';
import { BotService } from '../../services/bot.service';
import { ChartModule } from 'primeng/chart';
import { TableModule } from 'primeng/table';
@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CardModule,
    ButtonModule,
    BadgeModule,
    CommonModule,
    ChartModule,
    TableModule,
  ],
  templateUrl: './dashboard.html',
})
export class Dashboard implements OnInit, OnDestroy {
  botService = inject(BotService);
  chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { mode: 'index', intersect: false },
    },
    scales: {
      x: {
        display: false,
        grid: { display: false },
      },
      y: {
        grid: {
          color: 'rgba(148, 163, 184, 0.1)',
          drawBorder: false,
        },
      },
    },
  };

  ngOnInit() {
    this.botService.startPolling(5);
  }

  ngOnDestroy() {
    this.botService.stopPolling();
  }
}
