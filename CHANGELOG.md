# Changelog
Semua perubahan penting pada bot trading ini akan dicatat di file ini.

## [1.5.0] - 2026-04-14
### Added
- **Hammer Pattern Detection**: Menambahkan fungsi `is_hammer()` untuk mendeteksi pola *candlestick reversal* secara otomatis. Sinyal ini mendapat prioritas eksekusi tinggi (*Aggressive Entry*) saat berada di area *oversold*.
- **RSI Hook (Momentum Confirmation)**: Menambahkan logika `rsi_moving_up` untuk mendeteksi pantulan RSI (`curr_rsi > prev['rsi']`). Bot kini tidak akan membeli aset yang sedang terjun bebas (*menghindari "Catching a Falling Knife"*), melainkan menunggu hingga harga mulai berbalik naik.
- **Strict Interval Validation**: Menambahkan sistem keamanan pada fungsi `fetch_data()` untuk memastikan format interval valid (misal: `"1m"`, `"15m"`) agar terhindar dari *crash* API MEXC (Error Code: `-1121`).
- **Comprehensive Scan Logging**: Memperbarui log pemindaian terminal agar menampilkan `SYMBOL`, `Price`, status `RSI_UP`, dan `Hammer` dalam satu baris, mempermudah pemantauan indikator secara *real-time*.

### Changed
- **Unified & Optimized Trigger Logic**: Merombak total blok eksekusi `trigger_buy` di dalam `trading_loop`. Menghapus logika yang tumpang tindih/duplikat dan menyatukannya ke dalam satu alur hirarki yang lebih efisien dan mudah dibaca (*Refactored*).
- **Aggressive yet Safe Scalp Parameters**: Menyesuaikan ulang `STRATEGIES["SCALP"]`:
    - Mengaktifkan kembali `use_ema_200` sebagai batas tren wajib (Anti-Pisau Jatuh).
    - Memperlebar jangkauan `rsi_max` ke `52` dan `rsi_min` ke `20`.
    - Melonggarkan `vol_mult` menjadi `1.0`.
    - Mengubah `trail_start` ke `0.007` (0.7%) untuk memperhitungkan *round-trip trading fee* agar profit bersih tidak tergerus biaya bursa.
- **Realtime Forced Exit Pricing**: Perintah Telegram `/stop`, `/panic`, dan `/exit` sekarang mengambil harga *Bid* terbaru dari API terlebih dahulu sebelum mengirim parameter `forced_price` ke fungsi jual.

### Fixed
- **Simulation Precision Bug (PNL 0.00%)**: Memperbaiki masalah di mana *Dry Run* selalu mencatat PNL 0.00%. Ini dilakukan dengan memisahkan pembulatan `price_str` khusus untuk Mode Live (REST API MEXC) dan mempertahankan harga `float` murni berpresisi tinggi untuk simulasi.
- **Missing Terminal Sell Log**: Mengembalikan baris `logging.info(...)` pada blok eksekusi `SELL` mode simulasi yang sempat terhapus di versi sebelumnya.
- **Accidental Spread Market Order Fallback**: Memastikan limit_price tidak pernah menyentuh *Ask Price* saat spread lebar agar order benar-benar antre (Limit) dan tidak tereksekusi instan seperti Market order.

## [1.4.0] - 2026-04-12
### Added
- **Unified Profit Tracker**: Menyatukan sistem penghitungan profit. Variabel `total_accumulated_profit` kini secara otomatis mengakumulasi keuntungan baik dari mode **Simulasi (Dry Run)** maupun **Real Trading (Live)**.
- **Smart Startup Status**: Bot kini memberikan notifikasi yang lebih logis saat dinyalakan. Menampilkan status `⚡ INSTANT ENTRY` jika `force_buy` aktif, dan `🔍 AUTO SCAN` jika dalam mode normal.
- **Persistent Global State**: Memastikan status *Trade Count* dan *Accumulated Profit* tersimpan ke dalam `bot_state.json` segera setelah transaksi `SELL` berhasil di kedua mode.
- **Emergency Auto-Sell on Shutdown**: Menambahkan protokol keamanan yang secara otomatis mencoba mengeksekusi `MARKET SELL` jika pengguna mematikan bot (Ctrl+C) saat masih ada posisi aktif, guna mencegah aset tertahan tanpa pengawasan.
- **Telegram Auto-Revive System**: Menambahkan logika "Health Check" di loop utama yang secara otomatis membangkitkan ulang (*restart*) thread Telegram jika terdeteksi mati atau tidak responsif akibat gangguan jaringan.
- **Dynamic Trailing Stop (Scalp)**: Mengimplementasikan fitur pelacakan keuntungan agresif pada mode Scalp. Bot kini dapat menahan posisi lebih lama saat harga melonjak (*pump*) dan hanya akan menjual jika terjadi penurunan sebesar 0.4% dari titik tertinggi.
- **Python-Side Request Timeout**: Menambahkan parameter `timeout` pada level aplikasi saat melakukan *request* ke API Telegram untuk mencegah thread membeku (*freezing*) selamanya saat terjadi kegagalan sinkronisasi server.

### Changed
- **Variable Refactoring (Clean Code)**:
    - Mengubah `total_simulated_profit` menjadi `total_accumulated_profit` agar lebih representatif untuk penggunaan saldo asli.
    - Mengubah `paper_entry_price` menjadi `entry_price` sebagai variabel tunggal pemantau harga beli untuk semua mode.
- **Enhanced Live Reporting**: Pesan notifikasi `REAL TRADE COMPLETED` kini menyertakan kalkulasi PNL bersih dan total akumulasi profit keseluruhan secara real-time.
- **Thread Safety Improvement**: Memperbarui logika `bot_active = False` pada *main execution* untuk memastikan semua thread (Trading & Telegram) berhenti secara sinkron saat sinyal shutdown diterima.
- **Optimized Scalp Sensitivity**: Penyesuaian parameter strategi untuk respon lebih cepat:
    - Menaikkan batas atas RSI dari `55` ke `65`.
    - Menurunkan ambang batas Volume Multiplier menjadi `1.1x`.
    - Mempercepat frekuensi pemindaian (*delay_scan*) menjadi 15 detik.
- **Hard TP Bypass**: Mengubah status `use_hard_tp` menjadi `False` pada mode Scalp untuk memberikan ruang bagi logika *Trailing Stop* dalam memaksimalkan profit saat kondisi *bullish*.
- **SL Adjust**: Mengubah variabel untuk Stop Lost.

### Fixed
- **Live Profit Leak**: Memperbaiki bug di mana profit pada mode Live tidak tercatat pada variabel total akumulasi (sebelumnya hanya muncul di notifikasi Telegram tanpa disimpan ke memori).
- **Execution Logic Redundancy**: Menghapus duplikasi pemanggilan fungsi notifikasi startup pada blok eksekusi utama.
- **Limit Order Formatting**: Mengembalikan logika format harga dan kuantitas untuk `ORDER_TYPE = LIMIT` pada mode Live yang sempat hilang, memastikan kepatuhan terhadap *step size* API MEXC.
- **Telegram Thread Freezing**: Memperbaiki masalah bot tidak merespons perintah (commands) setelah berjalan berjam-jam dengan mengoptimalkan durasi *long-polling* dan penanganan *exception* pada koneksi HTTP.
- **Terminal Sell Logging**: Menambahkan baris `logging.info` yang sebelumnya absen pada proses eksekusi `SELL`, memastikan setiap transaksi terekam di terminal/konsol selain di Telegram.

## [1.3.0] - 2026-04-12
### Added
- **Multi-Timeframe Adaptive Data**: Fungsi `fetch_data()` kini menerima parameter `interval` secara dinamis. Bot akan secara otomatis menarik data K-Line (candlestick) yang berbeda (misal: 1m untuk Scalp, 15m untuk Trend) sesuai mode yang aktif.
- **Dynamic Scan Delay**: Menambahkan parameter `delay_scan` pada konfigurasi strategi. Bot sekarang memiliki "ritme napas" yang adaptif, bot melakukan pemindaian lebih cepat saat Scalping (20s) dan lebih tenang saat memantau Trend (60s).
- **Remote Symbol Switcher**: Perintah Telegram baru `/symbol <NAMA_KOIN>` untuk mengganti target koin secara instan tanpa menyentuh kode.
- **Live Verification System**: Bot akan memverifikasi keberadaan koin ke API MEXC sebelum menyetujui pergantian simbol untuk mencegah error akibat salah ketik.
- **Safety Lock (Symbol Change)**: Menambahkan proteksi yang menolak pergantian simbol jika bot masih memiliki posisi terbuka (`active_trade = True`) guna mencegah kekacauan data pada fungsi monitoring.

### Changed
- **Peningkatan Data Limit**: Menaikkan pengambilan data awal ke `limit: 250` untuk memastikan indikator jangka panjang seperti **EMA 200** memiliki data historis yang cukup dan akurat (menghindari nilai "floating").
- **Indikator Power Pack**: Melengkapi `fetch_data()` dengan perhitungan `vol_sma`, `vwap`, dan `ema_50` secara terpusat agar DataFrame selalu siap digunakan oleh logika filter mana pun.
- **Robust Status Report**: Memperbarui perintah `/status` dengan perhitungan *Floating PNL*, *Total Equity*, dan visualisasi saldo yang lebih rapi menggunakan format Markdown.

### Fixed
- **DataFrame Column Error**: Memperbaiki bug `'vol_sma'` (KeyError) dengan memastikan semua indikator dihitung di dalam fungsi fetcher sebelum data diproses oleh loop utama.
- **Telegram Markdown Crash**: Memperbaiki masalah pesan status yang tidak muncul akibat tanda baca (backtick/asterisk) yang tidak seimbang pada pengiriman pesan Telegram.
- **Return Logic Enhancement**: Mengganti penggunaan `continue` menjadi `return` pada handler Telegram untuk memperbaiki error interpretasi Python pada blok fungsi di luar loop.

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

### Tips Penggunaan (Update):

* **Manajemen Harapan & Fee**: Pada strategi Scalp, sadari bahwa target `0.7%` atau `1.5%` mungkin terdengar kecil, namun itu diformulasikan untuk tetap menghasilkan Profit Bersih (Nett) *setelah* dipotong biaya trading MEXC (Beli + Jual).
* **Monitoring Responsif**: Saat posisi aktif (`active_trade = True`), bot akan meningkatkan frekuensi pengecekan harga (setiap 3-5 detik). Ini normal dan bertujuan agar *Stop Loss* tereksekusi tepat waktu.
* **Keamanan Shutdown**: Jika ingin mematikan bot saat trading riil, gunakan `Ctrl + C` di terminal agar bot sempat menutup posisi. Menutup paksa jendela terminal secara langsung akan mematikan bot tanpa sempat menjual aset yang sedang di-hold.
* **Optimasi API**: Gunakan `delay_scan` yang lebih tinggi (>60s) pada timeframe besar untuk menghindari *rate limit* API jika kamu berencana memantau banyak koin.
* **Ganti Koin Cepat**: Gunakan `/symbol BTCUSDT` untuk berpindah fokus ke aset dengan likuiditas tinggi jika pasar sedang mengalami volatilitas ekstrem yang tidak menentu.
* **Akurasi EMA**: Jika kamu menggunakan timeframe besar (seperti 1h atau 4h), pastikan bot dibiarkan menyala beberapa saat agar perhitungan EMA 200 benar-benar stabil mengikuti pergerakan harga terbaru.
* **Gunakan Mode SCALP**: untuk koin dengan volatilitas tinggi (seperti XRP, SIREN, atau koin gainers) untuk menangkap keuntungan cepat dari pantulan harga.
* **Gunakan Mode TREND**: untuk koin dengan kapitalisasi pasar besar dan pergerakan stabil (seperti BTC, ETH, BNB) untuk memaksimalkan keuntungan dari tren jangka panjang yang terkonfirmasi.
