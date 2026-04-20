import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { BotStats, TradeRecord, ChartResponse } from '../models/bot.model';
import { Subscription, tap, timer } from 'rxjs';
import { MessageService } from 'primeng/api';
@Injectable({
  providedIn: 'root',
})
export class BotService {
  private http = inject(HttpClient);
  private messageService = inject(MessageService);
  private apiUrl = 'http://localhost:8000/api';

  // ==========================================
  // STATE (SIGNALS)
  // ==========================================

  isBotActive = signal<boolean>(false);
  isServerOnline = signal<boolean>(false);
  isDarkMode = signal<boolean>(false);
  isDryRun = signal<boolean>(true);
  equity = signal<number>(0);
  winRate = signal<number>(0);
  totalTrades = signal<number>(0);

  tradeHistory = signal<TradeRecord[]>([]);
  systemLogs = signal<string[]>([]);
  chartData = signal<any>(null);

  private pollingSub?: Subscription;

  startPolling(intervalSeconds: number = 5) {
    this.stopPolling();
    this.pollingSub = timer(0, intervalSeconds * 1000)
      .pipe(
        tap(() => {
          this.fetchDashboardStats();
          this.fetchTradeHistory();
          this.fetchEquityCurve();
          this.fetchLogs();
        }),
      )
      .subscribe();
  }

  stopPolling() {
    if (this.pollingSub) {
      this.pollingSub.unsubscribe();
    }
  }

  // ==========================================
  // FUNGSI HTTP
  // ==========================================

  fetchDashboardStats() {
    this.http.get<BotStats>(`${this.apiUrl}/stats`).subscribe({
      next: (response) => {
        this.isServerOnline.set(true);
        this.equity.set(response.equity);
        this.winRate.set(response.win_rate);
        this.totalTrades.set(response.total_trades);
        this.isBotActive.set(response.is_active);
        this.isDryRun.set(response.dry_run)
      },
      error: () => {
        this.isServerOnline.set(false);
        this.isBotActive.set(false);
      },
    });
  }

  fetchTradeHistory() {
    this.http
      .get<{ status: string; data: TradeRecord[] }>(`${this.apiUrl}/history`)
      .subscribe({
        next: (response) => {
          if (response.status === 'success') {
            this.tradeHistory.set(response.data);
          }
        },
        error: (err) => console.error('Gagal ambil history:', err),
      });
  }

  fetchEquityCurve() {
    this.http.get<ChartResponse>(`${this.apiUrl}/equity`).subscribe({
      next: (response) => {
        if (response.status === 'success') {
          this.chartData.set({
            labels: response.labels,
            datasets: [
              {
                label: 'Cumulative PNL (%)',
                data: response.cumulative_pnl,
                fill: true,
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                tension: 0.4,
                borderWidth: 2,
                pointRadius: 4,
                pointBackgroundColor: '#ffffff',
                pointBorderColor: '#6366f1',
                pointBorderWidth: 2,
                pointHoverRadius: 6,
                pointHitRadius: 10,
              },
            ],
          });
        }
      },
      error: (err) => console.error('Gagal ambil data chart:', err),
    });
  }

  fetchLogs() {
    this.http
      .get<{ status: string; data: string[] }>(`${this.apiUrl}/logs`)
      .subscribe({
        next: (res) => {
          if (res.status === 'success') {
            this.systemLogs.set(res.data);
          }
        },
        error: () => console.error('Gagal mengambil log sistem'),
      });
  }

  getSettings() {
    return this.http.get<{ status: string; data: any }>(
      `${this.apiUrl}/settings`,
    );
  }

  saveSettings(settingsData: any) {
    return this.http.post<{ status: string; message: string }>(
      `${this.apiUrl}/settings`,
      settingsData,
    );
  }

  toggleBot() {
    const newStatus = !this.isBotActive();
    const actionLabel = newStatus ? 'dijalankan' : 'dijeda';

    this.http
      .post<{
        status: string;
        is_active?: boolean;
        error_code?: string;
        message?: string;
      }>(`${this.apiUrl}/bot/toggle`, { active: newStatus })
      .subscribe({
        next: (res) => {
          if (res.status === 'error') {
            this.messageService.add({
              severity: 'warn',
              summary: 'Mesin Offline',
              detail: res.message || 'Gagal mengaktifkan bot.',
              life: 5000,
            });

            this.isBotActive.set(false);
            return;
          }

          if (res.is_active !== undefined) {
            this.isBotActive.set(res.is_active);
          }

          this.messageService.add({
            severity: 'success',
            summary: 'Status Bot Update',
            detail: `Bot berhasil ${actionLabel}`,
            life: 3000,
          });
        },
        error: (err) => {
          this.messageService.add({
            severity: 'error',
            summary: 'Gagal Kontrol Bot',
            detail: 'Server API tidak merespons. Periksa terminal Python Anda.',
            life: 5000,
          });
          console.error(err);
        },
      });
  }

  toggleDarkMode() {
    this.isDarkMode.update((val) => !val);
    const htmlTag = document.documentElement;
    if (this.isDarkMode()) {
      htmlTag.classList.add('dark');
    } else {
      htmlTag.classList.remove('dark');
    }
  }
}
