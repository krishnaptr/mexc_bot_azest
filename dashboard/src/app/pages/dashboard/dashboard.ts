import { Component, inject, OnDestroy, OnInit } from '@angular/core';
import { CardModule } from 'primeng/card';
import { ButtonModule } from 'primeng/button';
import { BadgeModule } from 'primeng/badge';
import { CommonModule } from '@angular/common';
import { BotService } from '../../services/bot.service';
import { ChartModule } from 'primeng/chart';
import { TableModule } from 'primeng/table';
import { Router } from '@angular/router';
import { TradingChartComponent } from '../../components/trading-chart/trading-chart';
import { MessageService } from 'primeng/api';
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
    TradingChartComponent,
  ],
  templateUrl: './dashboard.html',
})
export class Dashboard implements OnInit, OnDestroy {
  public router = inject(Router);
  private messageService = inject(MessageService);
  botService = inject(BotService);
 chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        mode: 'index',
        intersect: false,
        callbacks: {
          label: function(context: any) {
            return ` PNL: ${context.parsed.y}%`;
          }
        }
      },
    },
    scales: {
      x: {
        ticks: { color: '#94a3b8', maxTicksLimit: 7 },
        grid: { display: false },
      },
      y: {
        ticks: {
          color: '#94a3b8',
          callback: function(value: any) { return value + '%'; }
        },
        grid: {
          color: 'rgba(148, 163, 184, 0.1)',
          drawBorder: false,
        },
      },
    },
    elements: {
      line: { tension: 0.4 }
    }
};

  public toHistory() {
    this.router.navigateByUrl('/history').then();
  }

  ngOnInit() {
    this.botService.startPolling(5);
  }

  ngOnDestroy() {
    this.botService.stopPolling();
  }

  executePanicSell() {
    if (
      confirm(
        '🚨 PERINGATAN! Anda yakin ingin PANIC SELL ke harga market sekarang juga?',
      )
    ) {
      this.botService.panicSell().subscribe({
        next: (res) => {
          this.messageService.add({
            severity: 'success',
            summary: 'Panic Diterima',
            detail: res.message,
          });
        },
        error: () => {
          this.messageService.add({
            severity: 'error',
            summary: 'Gagal',
            detail: 'Server tidak merespons.',
          });
        },
      });
    }
  }
}
