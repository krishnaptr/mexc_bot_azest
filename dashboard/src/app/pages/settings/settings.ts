import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { CardModule } from 'primeng/card';
import { InputNumberModule } from 'primeng/inputnumber';
import { ButtonModule } from 'primeng/button';
import { MessageService } from 'primeng/api';
import { ToggleSwitchModule } from 'primeng/toggleswitch';
import { SelectModule } from 'primeng/select';
import { InputTextModule } from 'primeng/inputtext';
import { BotService } from '../../services/bot.service';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    CardModule,
    InputNumberModule,
    ButtonModule,
    ToggleSwitchModule,
    SelectModule,
    InputTextModule
  ],
  templateUrl: './settings.html'
})
export class Settings implements OnInit {
private botService = inject(BotService);
  private messageService = inject(MessageService)
  isSaving = false;
  envConfig: any = {};
  generalConfig: any = {};
  intervalOptions = [
    { label: '1 Menit', value: '1m' },
    { label: '5 Menit', value: '5m' },
    { label: '15 Menit', value: '15m' },
    { label: '30 Menit', value: '30m' },
    { label: '1 Jam', value: '1h' },
    { label: '4 Jam', value: '4h' },
    { label: '1 Hari', value: '1d' }
  ];

  trendConfig: any = {
    interval: '15m', rsi_min: 30, rsi_max: 75, vol_mult: 1.1,
    use_ema_200: true, tp_percent: 0.04, sl_atr_mult: 2.0,
    trail_start: 0.02, trail_dist: 0.01, delay_scan: 60, use_hard_tp: true
  };

  scalpConfig: any = {
    interval: '1m', rsi_min: 20, rsi_max: 52, vol_mult: 1.0,
    use_ema_200: true, tp_percent: 0.02, sl_atr_mult: 2.5,
    trail_start: 0.015, trail_dist: 0.008, delay_scan: 10, use_hard_tp: true
  };

  ngOnInit() {
    this.loadSettings();
  }

  loadSettings() {
    this.botService.getSettings().subscribe({
      next: (res) => {
        if (res.status === 'success') {
          this.envConfig = res.data.env;
          this.generalConfig = res.data.general;
          this.trendConfig = res.data.trend;
          this.scalpConfig = res.data.scalp;
        }
      },
      error: () => {
        this.messageService.add({ severity: 'error', summary: 'Error', detail: 'Gagal memuat konfigurasi dari server.' });
      }
    });
  }

  saveSettings() {
    this.isSaving = true;
    const payload = {
      env: this.envConfig,
      general: this.generalConfig,
      trend: this.trendConfig,
      scalp: this.scalpConfig
    };

    this.botService.saveSettings(payload).subscribe({
      next: () => {
        this.isSaving = false;
        this.messageService.add({
          severity: 'success',
          summary: 'Tersimpan',
          detail: 'Konfigurasi bot berhasil diperbarui di server!',
          life: 3000
        });
      },
      error: () => {
        this.isSaving = false;
        this.messageService.add({ severity: 'error', summary: 'Gagal', detail: 'Tidak dapat menghubungi server.' });
      }
    });
  }
}
