# config.py
import os
import json
from dotenv import load_dotenv

load_dotenv()

SETTINGS_FILE = "settings.json"
STATE_FILE = "bot_state.json" 
DB_FILE = "trading_history.db"

API_KEY = ""
SECRET_KEY = ""
TELE_TOKEN = ""
TELE_CHAT_ID = ""
SYMBOL = "BTCUSDT"
USDT_AMOUNT = 50.0
DRY_RUN = True
STRATEGIES = {}

BASE_URL = 'https://api.mexc.com'
EXCHANGE_FEE = 0.001

def get_settings():
    """
    Fungsi ini dipanggil oleh Bot di SETIAP LUP (Loop)
    agar bot selalu mendapatkan konfigurasi terbaru dari Dashboard.
    """
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                
            needs_save = False
            
            # Timpa nilai ENV dari .env lokal jika di JSON kosong, dan tandai untuk di-save
            if not data['env'].get('api_key'):
                env_val = os.getenv('API_KEY', '').strip()
                if env_val:
                    data['env']['api_key'] = env_val
                    needs_save = True
                    
            if not data['env'].get('secret_key'):
                env_val = os.getenv('SECRET_KEY', '').strip()
                if env_val:
                    data['env']['secret_key'] = env_val
                    needs_save = True
                    
            if not data['env'].get('tele_token'):
                env_val = os.getenv('TELEGRAM_TOKEN', '').strip()
                if env_val:
                    data['env']['tele_token'] = env_val
                    needs_save = True
                    
            if not data['env'].get('tele_chat_id'):
                env_val = os.getenv('TELEGRAM_CHAT_ID', '').strip()
                if env_val:
                    data['env']['tele_chat_id'] = env_val
                    needs_save = True
            
            # Jika ada data baru yang ditarik dari .env, PERMANENKAN ke settings.json
            if needs_save:
                with open(SETTINGS_FILE, "w") as f_out:
                    json.dump(data, f_out, indent=4)
                    
            return data
        except Exception as e:
            print(f"Gagal membaca settings.json: {e}")
            
    # Jika settings.json belum ada (baru pertama kali di-run), return default ini
    return {
        "env": {
            "api_key": os.getenv('API_KEY', '').strip() or "",
            "secret_key": os.getenv('SECRET_KEY', '').strip() or "",
            "tele_token": os.getenv('TELEGRAM_TOKEN', '').strip() or "",
            "tele_chat_id": os.getenv('TELEGRAM_CHAT_ID', '').strip() or ""
        },
        "general": {
            "symbol": "BTCUSDT",
            "usdt_amount": 50.0,
            "use_compounding": True,
            "risk_percentage": 5.0,
            "dry_run": True
        },
"trend": {
            "interval": "15m", 
            "rsi_min": 40,             # Koin uptrend jarang turun sampai 25.
            "rsi_max": 72,             # Beri izin bot membeli saat momentum sedang kuat (RSI 40-72).
            "vol_mult": 0.5,           # Syarat volume ringan (50% dari rata-rata), agar membuang sinyal sepi.
            "use_ema_200": True, 
            "tp_percent": 0.025,       # TP 2.5% 
            "sl_atr_mult": 2.5,        # SL napas panjang
            "breakeven_start": 0.012,  # Amankan modal di +1.2%
            "trail_start": 0.015,      # Mulai trailing di +1.5%
            "trail_dist": 0.005,       
            "delay_scan": 60, "use_hard_tp": True, "use_mtf": True, "macro_interval": "4h"
        },
"scalp": {
            "interval": "5m",         
            "rsi_min": 20,             
            "rsi_max": 45,             # Cari yang sedang oversold/koreksi
            "vol_mult": 0.8,           
            "use_ema_200": False,      
            "tp_percent": 0.007,       # TARGET KECIL: 0.7%. Sangat mudah tersentuh di 5m.
            "sl_atr_mult": 2.5,        
            "breakeven_start": 0.004,  # Amankan modal secepatnya saat untung 0.4%
            "trail_start": 0.005,      # Mulai membuntuti harga di 0.5%
            "trail_dist": 0.002,       # Jarak trailing sangat ketat (0.2%)
            "delay_scan": 10, "use_hard_tp": True, "use_mtf": False, "macro_interval": "1h"
        }
    }

# Notes:

# 1. Kacamata Waktu & Kecepatan (Waktu)
# *`interval` (Waktu Grafik):* *Fungsi:* Menentukan dari kacamata mana bot melihat grafik. 
#     Trend (`15m`):* Melihat lilin (candle) 15 menitan. Pergerakan lebih stabil dan minim sinyal palsu.
#     Scalp (`5m`):* Melihat lilin 1 menitan. Sangat cepat, agresif, dan penuh dengan riak (noise).
# *`delay_scan` (Waktu Istirahat):
#     Fungsi:* Waktu tunggu (dalam detik) sebelum bot mengecek harga lagi setelah satu putaran selesai.
#     Trend (`60`):* Cek setiap 1 menit. Cocok karena grafik 15m tidak berubah tiap detik.
#     Scalp (`10`):* Cek setiap 10 detik. Harus cepat karena di grafik 1m, telat beberapa detik bisa kehilangan momen.

# 2. Kriteria Pembelian (Kapan Beli?)
# *`rsi_min` & `rsi_max` (Zona Nyaman RSI):
#     Fungsi:* Memastikan koin tidak terlalu jenuh jual (kepanikan) dan tidak terlalu jenuh beli (pucuk).
#     Trend (`30 - 75`):* Cukup longgar. Tren yang kuat biasanya memiliki RSI tinggi (hingga 75) dan masih bisa terus naik.
#     Scalp (`20 - 52`):* Sangat ketat! Bot hanya mau beli koin yang sedang berada di bawah (RSI rendah), berharap koin tersebut memantul (rebound) sedikit ke arah tengah (52) untuk segera dijual untung.
# *`vol_mult` (Syarat Ledakan Volume):
#     Fungsi:* Bot hanya beli jika ada ledakan volume transaksi dibandingkan rata-rata.
#     Trend (`1.1`):* Butuh volume 10% lebih besar dari rata-rata untuk konfirmasi tren asli.
#     Scalp (`1.0`):* Volume biasa (rata-rata) sudah cukup untuk masuk, karena target untungnya sangat kecil.
# *`use_ema_200` (Penyaring Arah Angin):
#     Fungsi:* Jika `True`, bot HANYA akan membeli jika harga berada di atas garis EMA 200 (pasar sedang uptrend/naik). Ini menghindarkan dari membeli koin yang sedang *nyungsep*.

# 3. Manajemen Risiko & Keuntungan (Kapan Jual?)
# *`tp_percent` (Target Keuntungan Absolut):
#     Trend (`0.04` = 4%):* Menargetkan profit 4% per transaksi.
#     Scalp (`0.02` = 2%):* Mengambil sedikit untung 2% dan langsung kabur.
# *`use_hard_tp` (Penjualan Kaku):
#     Fungsi:* Jika `True`, bot akan otomatis menjual tepat di angka `tp_percent` tanpa kompromi. Ia tidak akan menunggu harga naik lebih tinggi lagi.
# *`sl_atr_mult` (Jarak Stop Loss/Cut Loss):
#     Fungsi:* Jarak kerugian maksimal yang diizinkan berdasarkan volatilitas (keliaran) koin.
#     Trend (`1.5`):* Relatif sedang.
#     Scalp (`2.5`):* Angkanya terlihat besar (2.5x), TAPI karena ini grafik 1 menit, pergerakan koinnya sangat sempit. Jadi 2.5x ATR di 1 menit jauh lebih kecil secara dolar dibandingkan 1.5x ATR di 15 menit.
# *`trail_start` & `trail_dist` (Jaring Pengaman Otomatis / Trailing Stop):
#     Fungsi:* Ini adalah fitur tercanggih. Jika harga belum menyentuh Take Profit (TP), tapi sudah mulai naik lumayan tinggi, bot akan "membangun" titik Stop Loss baru yang mengikuti harga naik dari bawah untuk mengunci profit.
#     Trend (`start: 0.02, dist: 0.01`):* Jika harga naik +2%, fitur aktif. Bot akan terus mengikuti dari jarak -1% di bawah pucuk harga. Jika harga tiba-tiba berbalik arah dan turun 1%, bot langsung menjual dengan sisa profit 1%.
#     Scalp (`start: 0.015, dist: 0.008`):* Fitur aktif lebih cepat saat harga baru naik 1.5%.
# *`breakeven_start`:
#     Fungsi:* Fitur untuk otomatis menaikan SL jika sudah menyentuh minimal profit yang di tentukan.
#     Trend (`0.015`):* akan di trigger jika profit sudah +1.5%.
#     Scalp (`0.008`):* akan di trigger jika profit sudah +0.8%.