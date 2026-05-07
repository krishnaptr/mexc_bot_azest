from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import hmac
import hashlib
import requests
import time
import os
import uvicorn
import config
from urllib.parse import urlencode

# Inisialisasi Aplikasi Web
app = FastAPI(title="MEXC Bot API Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SETTINGS_FILE = "settings.json"
DB_FILE = config.DB_FILE
STATE_FILE = config.STATE_FILE

# Konfigurasi Bawaan (Default) jika file belum ada
DEFAULT_SETTINGS = {
    "env": {
        "api_key": "", "secret_key": "", "tele_token": "", "tele_chat_id": ""
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
            "rsi_min": 40,             # Naikkan sedikit. Koin uptrend jarang turun sampai 25.
            "rsi_max": 72,             # LONGGARKAN. Beri izin bot membeli saat momentum sedang kuat (RSI 40-72).
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
            "interval": "5m",          # Habitat asli Scalper
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

def read_settings():
    """Membaca pengaturan dari file JSON, dan otomatis menarik dari .env jika kosong"""
    data = DEFAULT_SETTINGS.copy()
    needs_save = False
    
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
        except: pass

    # Sinkronisasi Otomatis dari .env ke JSON
    if not data.get("env", {}).get("api_key"):
        env_val = os.getenv("API_KEY", "").strip()
        if env_val:
            data.setdefault("env", {})["api_key"] = env_val
            needs_save = True
            
    if not data.get("env", {}).get("secret_key"):
        env_val = os.getenv("SECRET_KEY", "").strip()
        if env_val:
            data.setdefault("env", {})["secret_key"] = env_val
            needs_save = True
            
    if not data.get("env", {}).get("tele_token"):
        env_val = os.getenv("TELEGRAM_TOKEN", "").strip()
        if env_val:
            data.setdefault("env", {})["tele_token"] = env_val
            needs_save = True
            
    if not data.get("env", {}).get("tele_chat_id"):
        env_val = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if env_val:
            data.setdefault("env", {})["tele_chat_id"] = env_val
            needs_save = True
            
    # Jika ada yang kosong dan berhasil diisi oleh .env, simpan ke file
    if needs_save:
        write_settings(data)
        
    return data

def write_settings(data):
    """Menyimpan pengaturan ke file JSON"""
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except: return False

@app.get("/api/settings")
def get_settings():
    """Endpoint untuk mengambil pengaturan saat web dibuka"""
    try:
        settings = read_settings()
        return {"status": "success", "data": settings}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/settings")
async def update_settings(request: Request):
    """Endpoint untuk menyimpan pengaturan dari web"""
    try:
        new_settings = await request.json()
        write_settings(new_settings)
        return {"status": "success", "message": "Konfigurasi berhasil disimpan"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def read_bot_state():
    """Membaca memori terakhir bot dari file JSON."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {}

def write_bot_state(data):
    """Menulis memori ke file JSON."""
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f, indent=4)
        return True
    except: return False

def get_real_usdt_balance(api_key, secret_key):
    """Fungsi pembantu untuk mengecek saldo USDT asli di dompet MEXC"""
    if not api_key or not secret_key:
        return 0.0
    
    try:
        params = {
            'timestamp': int(time.time() * 1000),
            'recvWindow': 60000
        }
        # Membuat tanda tangan (Signature) keamanan wajib MEXC
        query_string = urlencode(params)
        signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
        params['signature'] = signature
        
        headers = {'X-MEXC-APIKEY': api_key}
        
        # Tembak API Akun MEXC
        res = requests.get("https://api.mexc.com/api/v3/account", params=params, headers=headers, timeout=5).json()
        
        if 'balances' in res:
            for b in res['balances']:
                if b['asset'] == 'USDT':
                    return float(b['free'])
    except Exception as e:
        print(f"Gagal mengambil saldo asli: {e}")
        
    return 0.0

@app.get("/api/stats")
def get_bot_stats():
    """Endpoint untuk Kartu Statistik di Dashboard Atas (Live & Simulasi Terpisah)."""
    try:
        # 1. BACA SETTINGS & STATE (Cukup panggil 1 kali saja)
        settings = read_settings()
        is_dry_run = settings.get("general", {}).get("dry_run", True)
        api_key = settings.get("env", {}).get("api_key", "")
        secret_key = settings.get("env", {}).get("secret_key", "")
        
        state = read_bot_state()
        is_active_intent = state.get("is_active", True)
        last_heartbeat = state.get("last_heartbeat", 0)
        
        # Tentukan filter database (Asumsi kolom di SQLite bernama 'mode')
        mode_filter = "SIMULASI" if is_dry_run else "LIVE"
        current_time = time.time()
        is_engine_alive = (current_time - last_heartbeat) < 15

        # 2. HITUNG STATISTIK DARI DATABASE
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL' AND mode=?", (mode_filter,))
            total_trades = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT SUM(net_pnl) FROM trades WHERE side='SELL' AND mode=?", (mode_filter,))
            sum_pnl = cursor.fetchone()[0] or 0.0
            
            cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL' AND net_pnl > 0 AND mode=?", (mode_filter,))
            winning_trades = cursor.fetchone()[0] or 0
        except:
            # Fallback (Jaring Pengaman) jika database versi lama belum punya kolom 'mode'
            cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL'")
            total_trades = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(net_pnl) FROM trades WHERE side='SELL'")
            sum_pnl = cursor.fetchone()[0] or 0.0
            cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL' AND net_pnl > 0")
            winning_trades = cursor.fetchone()[0] or 0

        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        conn.close()
        
        # 3. PERHITUNGAN SALDO (EQUITY)
        if is_dry_run:
            import database
            
            usdt_sim = database.load_sim_balance()
            if state.get("active_trade", False):
                try:
                    entry_p = state.get("entry_price", 0.0)
                    ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': settings.get("general", {}).get("symbol", "BTCUSDT")}, timeout=5).json()
                    curr_p = float(ticker['bidPrice'])
                    if sl_p == 0.0 and entry_p > 0:
                        sl_p = entry_p * 0.99
                    # Asumsi jumlah koin yang dibeli = Modal per trade / Harga Beli
                    usdt_per_trade = settings.get("general", {}).get("usdt_amount", 50.0)
                    jumlah_koin = usdt_per_trade / entry_p
                    nilai_koin_sekarang = jumlah_koin * curr_p
                    
                    equity = usdt_sim + nilai_koin_sekarang
                except:
                    equity = usdt_sim # Fallback jika gagal tarik harga
            else:
                equity = usdt_sim
                
        else:
            # Jika Uang Asli, tembak API MEXC untuk melihat sisa USDT aktual di dompet
            equity = get_real_usdt_balance(api_key, secret_key)

        pos_data = None
        if state.get("active_trade", False):
            import config
            import requests
            
            entry_p = state.get("entry_price", 0.0)
            sl_p = state.get("stop_loss", 0.0)
            symbol = settings.get("general", {}).get("symbol", "BTCUSDT")

            if sl_p == 0.0 and entry_p > 0:
                sl_p = entry_p * 0.99
            
            try:
                # Ambil harga live langsung dari MEXC Orderbook
                ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': symbol}, timeout=5).json()
                curr_p = float(ticker['bidPrice'])
                
                # Hitung PNL persis seperti rumus monitor_position di main.py
                pnl_gross = (curr_p - entry_p) / entry_p
                pnl_net = pnl_gross - config.EXCHANGE_FEE
                
                # Hitung estimasi Target TP (Mengambil dari setting TREND)
                tp_pct = settings.get("trend", {}).get("tp_percent", 0.025)
                tp_price = entry_p * (1 + tp_pct)
                
            except Exception:
                curr_p, pnl_net, tp_price = 0.0, 0.0, 0.0
                
            pos_data = {
                "symbol": symbol,
                "entry_price": entry_p,
                "current_price": curr_p,
                "pnl": pnl_net,
                "sl_price": sl_p,
                "tp_price": tp_price
            }
        return {
            "status": "success",
            "is_active": is_active_intent and is_engine_alive,
            "engine_status": "ONLINE" if is_engine_alive else "OFFLINE",
            "active_trade": state.get("active_trade", False),
            "position": pos_data,
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "equity": round(equity, 2),
            "total_net_pnl_percent": round(sum_pnl * 100, 2),
            "dry_run": is_dry_run
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/bot/panic")
async def trigger_panic():
    """Mengirim sinyal radio darurat ke main.py lewat state.json"""
    try:
        import database
        state = database.load_state()
        
        if not state.get("active_trade", False):
            return {"status": "error", "message": "Tidak ada posisi aktif yang bisa dijual."}
            
        state["trigger_panic"] = True
        database.save_state(state)
        
        return {"status": "success", "message": "Sinyal PANIC SELL berhasil dikirim ke Mesin Trading!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@app.post("/api/bot/toggle")
async def toggle_bot(request: Request):
    """Endpoint untuk mengubah status bot (Aktif/Jeda) dari UI."""
    try:
        data = await request.json()
        new_status = data.get("active", True)
        
        state = read_bot_state()

        # Jika user ingin mengaktifkan bot (True), kita cek dulu mesinnya
        if new_status == True:
            last_heartbeat = state.get("last_heartbeat", 0)
            current_time = time.time()
            
            if (current_time - last_heartbeat) > 15:
                return {
                    "status": "error", 
                    "error_code": "ENGINE_OFFLINE",
                    "message": "Gagal mengaktifkan: Mesin utama (main.py) belum berjalan!"
                }
        # ===========================
        
        # Jika mesin hidup (atau jika perintahnya adalah 'Pause'/False), izinkan
        state["is_active"] = new_status
        write_bot_state(state)
        
        return {"status": "success", "is_active": new_status}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/history")
def get_trade_history():
    """Endpoint untuk Tabel Riwayat Transaksi."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        
        # Ambil 50 transaksi terakhir, urutkan dari yang paling baru
        cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
        conn.close()
        
        return {"status": "success", "data": [dict(row) for row in rows]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/equity")
def get_equity_curve():
    """Mengirim data untuk menggambar grafik garis (Equity Curve) di Web"""
    try:
        import sqlite3
        
        settings = read_settings()
        is_dry_run = settings.get("general", {}).get("dry_run", True)
        mode_filter = "SIMULASI" if is_dry_run else "LIVE"

        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        
        # Ambil semua transaksi JUAL yang sudah selesai
        try:
            cursor.execute("SELECT timestamp, net_pnl FROM trades WHERE side='SELL' AND mode=? ORDER BY id ASC", (mode_filter,))
        except:
            cursor.execute("SELECT timestamp, net_pnl FROM trades WHERE side='SELL' ORDER BY id ASC")
            
        trades = cursor.fetchall()
        conn.close()

        labels = ["Start"]
        cumulative_pnl = [0.0]
        current_sum = 0.0
        
        for t in trades:
            time_str = t[0] 
            pnl_decimal = t[1] or 0.0
            
            try: short_time = time_str.split(" ")[1][:5] # Ambil Jam:Menit
            except: short_time = time_str
                
            current_sum += (pnl_decimal * 100)
            labels.append(short_time)
            cumulative_pnl.append(round(current_sum, 2))

        return {
            "status": "success",
            "labels": labels,
            "cumulative_pnl": cumulative_pnl
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@app.get("/api/logs")
def get_system_logs():
    """Endpoint untuk mengambil 20 baris terakhir dari terminal log."""
    log_file = "trading_log.txt"
    try:
        if not os.path.exists(log_file):
            return {"status": "success", "data": ["Menunggu aktivitas sistem pertama..."]}
        
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Ambil 25 baris terakhir agar tidak membebani browser, lalu hilangkan enter (\n)
            last_lines = [line.strip() for line in lines[-25:] if line.strip()]

            last_lines.reverse()
            return {"status": "success", "data": last_lines}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    print("🚀 API Server berjalan di http://localhost:8000")
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)