# Changelog
Semua perubahan penting pada bot trading ini akan dicatat di file ini.

## [2.1.0] - 2026-04-21
### Added
- **Standalone Backtest Engine (`backtest.py`)**: Menambahkan skrip mesin waktu independen untuk menguji parameter strategi secara matematis terhadap 1000 *candle* historis di MEXC. Memberikan laporan detail terkait *Win Rate*, Total Trade, dan Net Profit sebelum bot dijalankan dengan uang riil.
- **Risk-Free Trade (Break-Even Stop Loss)**: Mengimplementasikan sistem pertahanan modal tingkat lanjut. Bot kini otomatis memindahkan *Stop Loss* ke titik *Entry Price + Fee* segera setelah profit mencapai ambang batas tertentu (`breakeven_start`), memastikan posisi yang sudah untung tidak akan pernah berakhir minus.
- **Multi-Timeframe (MTF) Macro Filter**: Menambahkan "Kacamata Makro". Bot kini menarik data dari *timeframe* besar (misal `4h`) untuk memastikan tren utama sedang *Bullish* (Harga > EMA 200 Makro) sebelum mengizinkan eksekusi sinyal beli di *timeframe* kecil (misal `15m`). Terbukti ampuh mencegah jebakan *Bull Trap*.

### Changed
- **Zero-Fee Maker Strategy**: Merombak total logika eksekusi *Trade*. Eksekusi `BUY` dan `HARD TP` kini secara ketat dipaksa menggunakan antrean *Limit Order* (Maker) untuk menikmati potongan *Fee* 0% dari bursa. Sementara `SELL` akibat *Stop Loss* / *Trailing* tetap menggunakan *Market Order* (Taker 0.1%) sebagai prosedur darurat.
- **Single-Coin Pro Focus**: Membatalkan arsitektur *Multi-Coin* eksperimental dan mengembalikan fokus mesin utama ke *Single-Coin* murni. Memastikan alokasi memori, sinkronisasi *thread*, dan kecepatan respons bot berada di tingkat maksimal untuk satu aset spesifik.
- **Mean Reversion Scalping (Buy The Dip)**: Merombak total parameter strategi `SCALP` dari *Trend Following* menjadi *Mean Reversion*. Interval diubah ke `5m`, batasan RSI diturunkan secara drastis untuk mencari harga diskon/panik (*oversold*), dan syarat volume dilonggarkan agar bot berani menangkap peluang saat pasar sedang koreksi tajam.

### Fixed
- **Backtest Fee Buffer Crash**: Memperbaiki `NameError` pada `backtest.py` dengan menyesuaikan rumus perhitungan *Break-Even* menggunakan pemisahan biaya secara akurat (`fee_maker` + `fee_taker`).
- **ADX Contradiction on Scalp**: Memperbaiki masalah di mana bot menolak melakukan *trading* pada mode Scalp akibat syarat ADX > 25 yang bertentangan dengan syarat RSI rendah. Logika ADX kini diabaikan/dimatikan khusus untuk strategi SCALP di dalam mesin *backtest* maupun *live*.

## [2.0.0] - 2026-04-18
### Added
- **Decoupled Full-Stack Architecture**: Perubahan fundamental arsitektur dengan memisahkan mesin inti (`main.py`) dari server antarmuka (`api_server.py`). Memungkinkan Dashboard Web tetap berjalan stabil meskipun mesin trading sedang dalam kondisi *restart* atau *crash*.
- **Bot Heartbeat System**: Implementasi sistem "Detak Jantung" digital. `main.py` kini memperbarui *timestamp* setiap loop, memungkinkan Dashboard untuk mendeteksi secara *real-time* apakah mesin trading benar-benar sedang hidup (*Online*) atau mati (*Offline*).
- **ADX Indicator (Trend Strength Filter)**: Menambahkan indikator *Average Directional Index* (ADX). Bot kini memiliki filter "Anti-Sideways"; hanya akan mengeksekusi *Entry* jika kekuatan tren berada di atas nilai 25, mengurangi sinyal palsu pada pasar yang mendatar.
- **Dynamic Hot-Reload Settings**: Memindahkan konfigurasi statis ke dalam `settings.json`. Pengguna kini dapat mengubah parameter strategi (RSI, ATR, SL, TP) langsung dari Dashboard tanpa perlu mematikan dan menyalakan ulang skrip Python.
- **MEXC Real-Time Balance Sync**: Integrasi API Akun MEXC pada Dashboard. Statistik *Equity* kini dapat menampilkan saldo USDT asli langsung dari dompet bursa saat mode LIVE aktif.
- **Dashboard-Telegram Sync Notification**: Sinkronisasi status sakelar. Menekan tombol "Jeda" atau "Aktif" di Web kini otomatis mengirimkan notifikasi laporan status ke Telegram.

### Changed
- **Hard-Capped Stop Loss Logic**: Menambahkan "Sabuk Pengaman" ekstra pada perhitungan SL. Jika perhitungan ATR menghasilkan jarak *Stop Loss* yang terlalu dalam (misal > 10%), sistem akan otomatis memaksanya (*Hard Cap*) ke angka maksimal -5% untuk melindungi modal dari volatilitas ekstrem.
- **Reverse Chronological Logging**: Mengubah urutan tampilan log pada Dashboard. Aktivitas terbaru kini muncul di baris paling atas, menghilangkan kebutuhan pengguna untuk melakukan *scroll* manual.
- **API Guard on Toggle**: Mengubah logika tombol aktifasi. Server API kini akan menolak perintah "Aktifkan Bot" dan memberikan peringatan jika mendeteksi `main.py` belum dijalankan di terminal.

### Fixed
- **Optimistic UI Toggle Failure**: Memperbaiki masalah di mana tombol Dashboard terlihat aktif padahal mesin mati. Kini UI akan otomatis kembali ke posisi *Off* jika aktivasi gagal.
- **Config Attribute Error (`BASE_URL` & `TELE_TOKEN`)**: Memperbaiki *crash* sistem saat *startup* akibat variabel lingkungan yang belum terinisialisasi dengan benar pada arsitektur baru.
- **Auto-Wake State on Manual Run**: Memastikan status bot di Dashboard otomatis berubah menjadi hijau (Aktif) segera setelah pengguna menjalankan `python main.py` di terminal.

## [1.6.0] - 2026-04-14
### Added
- **SQLite Database Integration**: Mengganti sistem pencatatan `.txt` tradisional dengan *database* relasional SQLite (`trading_history.db`). Semua riwayat `BUY`, `SELL`, `Gross PNL`, dan `Net PNL` kini direkam secara terstruktur dalam tabel.
- **FastAPI Backend Server**: Membuat file independen `api_server.py` yang menyediakan endpoint RESTful API (`/api/stats`, `/api/history`, `/api/equity`). Server ini bertugas sebagai jembatan untuk menyuplai data *real-time* ke antarmuka Dashboard Angular.
- **Microservices Architecture**: Memecah `main.py` yang sebelumnya monolith (1000+ baris) menjadi modul-modul terpisah (*Separation of Concerns*):
    - `config.py`: Sentralisasi konfigurasi, API Key, dan setting strategi.
    - `database.py`: Menangani urusan penyimpanan file JSON dan operasi SQLite.
    - `telegram_bot.py`: Mengisolasi fungsi *long-polling* dan notifikasi Telegram dari beban kerja indikator trading.

### Changed
- **MEXC Real Fee Adjustment**: Menurunkan asumsi `EXCHANGE_FEE` dari `0.20%` ke `0.10%` (`0.001`) berdasarkan struktur tarif MEXC yang menguntungkan (Maker 0%, Taker 0.05%).
- **Faster Scalping Trailing**: Menurunkan trigger `trail_start` pada mode SCALP ke `0.005` (0.5%) karena biaya *round-trip* bursa lebih murah, memungkinkan bot mengunci profit lebih dini.
- **Net Profit Logic Focus**: Mengubah logika PNL pada monitor terminal dan status Telegram agar selalu menampilkan **Net PNL** (Profit setelah dipotong biaya bursa), bukan Gross PNL, memberikan transparansi *real-time* terhadap profit aktual.
- **Command Renaming**: Mengubah perintah telegram `/testbuy` menjadi `/forcebuy` agar pengguna lebih waspada bahwa perintah tersebut mengeksekusi uang sungguhan saat bot berada dalam mode LIVE.

### Fixed
- **Force Buy Instant-Sell Bug**: Memperbaiki logika `/forcebuy` yang memicu bot untuk langsung menjual koin di detik pertama pembelian. Hal ini diatasi dengan mereset perhitungan `stop_loss` ke `0.0` sampai harga *entry* eksekusi aktual benar-benar diterima dari bursa.
- **Missing Terminal Buy Logs**: Menambahkan `logging.info()` untuk eksekusi `MARKET` dan `LIMIT BUY` (baik di mode Simulasi maupun Live) yang sebelumnya absen dari terminal *console*.
- **Telegram Context Error**: Mengatasi isu *AttributeError* dengan menyesuaikan parameter modul `sys.modules[__name__]` saat mengaktifkan thread `telegram_bot.start_polling()` agar asisten Telegram dapat mengontrol state di `main.py` dengan benar.

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

### Tips Penggunaan (Update V2.1.0):

* **Manajemen Harapan & Fee**: Bot saat ini mengutamakan sistem Zero-Fee Maker (Antre Limit 0%), sehingga target TP sekecil 0.7% pada timeframe 5m sangat mungkin menghasilkan *Nett Profit* yang bersih.
* **Gunakan Mesin Backtest**: JANGAN PERNAH mengubah konfigurasi secara acak. Gunakan perintah `python backtest.py` untuk menguji parameter Anda setiap kali Anda berpindah koin (Karakteristik Aset/Asset Personality).
* **Monitoring Responsif**: Saat posisi aktif (`active_trade = True`), bot akan meningkatkan frekuensi pengecekan harga. Ini normal dan bertujuan agar *Break-Even* atau *Stop Loss* tereksekusi secepat kilat.
* **Keamanan Shutdown**: Gunakan `Ctrl + C` di terminal agar bot sempat menjual koin secara otomatis jika Anda ingin menghentikan operasi secara total.
* **Ganti Koin Cepat**: Gunakan `/symbol BTCUSDT` untuk berpindah ke aset dengan volatilitas tinggi, namun selalu sinkronkan dengan hasil backtest.
* **Gunakan Mode SCALP**: Untuk menangkap "Pisau Jatuh" saat pasar sedang merah/koreksi (Mean Reversion).
* **Gunakan Mode TREND**: Untuk koin dengan kapitalisasi pasar besar (BTC/ETH) yang bergerak searah dengan filter makro (MTF 4h).