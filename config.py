import os
from dotenv import load_dotenv

# Muat variabel dari file .env (jika ada)
load_dotenv()

# --- KONFIGURASI API BURS & TELEGRAM ---
API_KEY = os.getenv('API_KEY', '').strip() or None
SECRET_KEY = os.getenv('SECRET_KEY', '').strip() or None
TELE_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELE_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- PENGATURAN TRADING UMUM ---
BASE_URL = 'https://api.mexc.com'
SYMBOL = 'ALGOUSDT'
USDT_AMOUNT = 50.0   # Nominal uang per transaksi
DRY_RUN = True       # True = Simulasi/Paper Trading, False = Uang Asli
EXCHANGE_FEE = 0.001 # MEXC Spot (Maksimal Taker + Taker = 0.10% Total)

# --- FILE PENYIMPANAN ---
STATE_FILE = "bot_state.json" 
DB_FILE = "trading_history.db"

# --- GLOBAL STRATEGY SETTINGS ---
STRATEGIES = {
    "TREND": {
        "interval": "15m",
        "rsi_min": 30, "rsi_max": 60, "vol_mult": 1.5,
        "use_ema_200": True, "tp_percent": 0.04,
        "sl_atr_mult": 2.0, "trail_start": 0.03, "trail_dist": 0.02, "delay_scan": 60,
        "use_hard_tp": False
    },
    "SCALP": {
        "interval": "1m",
        "rsi_min": 20, "rsi_max": 52,     
        "vol_mult": 1.0,                  
        "use_ema_200": True,              
        "tp_percent": 0.015,              
        "sl_atr_mult": 2.5,               
        "trail_start": 0.005, # Bot mulai pasang jaring saat profit 0.5%
        "trail_dist": 0.003,              
        "delay_scan": 10,                 
        "use_hard_tp": False              
    }
}