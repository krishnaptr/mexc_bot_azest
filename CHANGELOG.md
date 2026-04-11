# Changelog
Semua perubahan penting pada bot trading ini akan dicatat di file ini.

## [1.2.0] - 2026-04-11
### Added
- **Sistem Strategy Switcher**: Menambahkan dictionary `STRATEGIES` untuk menyimpan parameter "TREND" dan "SCALP" di satu tempat.
- **Mode Scalping/Rebound**: Strategi baru yang fokus pada *oversold rsi* dan *volume spikes* tanpa mewajibkan konfirmasi EMA 200.
- **Telegram Remote Control**: Perintah `/mode_trend` dan `/mode_scalp` untuk mengganti strategi secara instan tanpa restart script.
- **Monitoring Adaptif**: Fungsi `monitor_position()` sekarang menyesuaikan *Target Profit* dan *Trailing Stop* secara otomatis berdasarkan mode yang aktif.
- **Identitas Log**: Menambahkan prefix `[TREND]` atau `[SCALP]` pada log terminal untuk memudahkan pemantauan strategi.

### Changed
- **Real-time Price Engine**: Mengubah pembacaan harga dari `last['close']` (candle sebelumnya) ke `ticker_realtime['askPrice']` agar lebih responsif terhadap lonjakan harga mendadak.
- **Peningkatan Presisi Log**: Mengembalikan variabel `Price` pada log monitoring yang sempat hilang dan menambahkan detail simbol koin.
- **Shutdown Safety**: Memperbarui logika `KeyboardInterrupt` (Ctrl+C) agar langsung mematikan thread trading (`bot_active = False`) guna mencegah "scan liar" setelah posisi ditutup paksa.

### Fixed
- **Pylance Error**: Memperbaiki bug `"curr_rsi" is not defined` dengan mendefinisikan variabel RSI sebelum digunakan dalam logika filter.
- **Race Condition**: Memperbaiki jeda waktu antara perintah stop manual dengan aktivitas thread latar belakang.

## [1.1.0] - 2026-04-11
### Added
- **Limit Order Support**: Menambahkan logika antre harga (Limit Buy) jika spread terlalu lebar namun masih di bawah batas toleransi.
- **Spread Guard**: Perlindungan otomatis yang mengabaikan sinyal jika selisih harga bid/ask (spread) terlalu berbahaya (di atas 2.5%).

## [1.0.0] - Awal Proyek
### Added
- **Core Engine**: Sistem trading loop dasar dengan integrasi MEXC API.
- **Indikator Teknis**: Implementasi EMA 200, EMA 50, RSI, VWAP, dan Volume SMA.
- **Risk Management**: Stop Loss dinamis berbasis ATR (Average True Range).
- **Telegram Notifier**: Integrasi pengiriman sinyal dan status bot ke Telegram.
- **Simulation Mode**: Fitur Dry Run untuk testing tanpa menggunakan saldo asli.

---

### Tips Penggunaan:

**Selalu gunakan Versi [1.2.0] sebagai standar karena memiliki sistem Strategy Switcher yang adaptif.

**Gunakan Mode SCALP untuk koin dengan volatilitas tinggi (seperti XRP, SIREN, atau koin gainers) untuk menangkap keuntungan cepat dari pantulan harga.

**Gunakan Mode TREND untuk koin dengan kapitalisasi pasar besar dan pergerakan stabil (seperti BTC, ETH, BNB) untuk memaksimalkan keuntungan dari tren jangka panjang yang terkonfirmasi.
