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
        "symbol": "BTCUSDT", "usdt_amount": 50.0, "dry_run": True
    },
    "trend": {
        "interval": "15m", "rsi_min": 30, "rsi_max": 75, "vol_mult": 1.1,
        "use_ema_200": True, "tp_percent": 0.04, "sl_atr_mult": 1.5, 
        "trail_start": 0.02, "trail_dist": 0.01, "delay_scan": 60, "use_hard_tp": True
    },
    "scalp": {
        "interval": "1m", "rsi_min": 20, "rsi_max": 52, "vol_mult": 1.0,
        "use_ema_200": True, "tp_percent": 0.02, "sl_atr_mult": 2.5, 
        "trail_start": 0.015, "trail_dist": 0.008, "delay_scan": 10, "use_hard_tp": True
    }
}

def read_settings():
    """Membaca pengaturan dari file JSON"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except: pass
    return DEFAULT_SETTINGS

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
        # Catatan: Di bot sungguhan, Anda mungkin perlu memanggil fungsi 
        # reload_config() di sini agar bot langsung memakai setting baru.
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
        # 1. BACA SETTINGS UNTUK MENENTUKAN JALUR
        settings = read_settings()
        is_dry_run = settings.get("general", {}).get("dry_run", True)
        api_key = settings.get("env", {}).get("api_key", "")
        secret_key = settings.get("env", {}).get("secret_key", "")
        
        # Tentukan filter database (Asumsi kolom di SQLite bernama 'mode')
        mode_filter = "SIMULASI" if is_dry_run else "LIVE"

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        state = read_bot_state()
        is_active_intent = state.get("is_active", True)
        last_heartbeat = state.get("last_heartbeat", 0)
        
        # Hitung selisih waktu sekarang dengan detak jantung terakhir
        current_time = time.time()
        # Jika lebih dari 15 detik tidak ada update, berarti main.py mati
        is_engine_alive = (current_time - last_heartbeat) < 15

        settings = read_settings() 
        is_dry_run = settings.get("general", {}).get("dry_run", True)
        
        # 2. HITUNG STATISTIK (HANYA UNTUK MODE YANG AKTIF SAAT INI)
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
        
        # 3. PERHITUNGAN SALDO (EQUITY) YANG TEPAT
        if is_dry_run:
            # Jika simulasi, gunakan modal virtual statis
            MODAL_AWAL_SIMULASI = 1000.0
            equity = MODAL_AWAL_SIMULASI + sum_pnl
        else:
            # Jika Uang Asli, tembak API MEXC untuk melihat sisa USDT aktual di dompet
            equity = get_real_usdt_balance(api_key, secret_key)
            
        state = read_bot_state()
        
        return {
            "status": "success",
            "is_active": is_active_intent and is_engine_alive,
            "engine_status": "ONLINE" if is_engine_alive else "OFFLINE",
            "active_trade": state.get("active_trade", False),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "equity": round(equity, 2),
            "total_net_pnl_percent": round(sum_pnl * 100, 2),
            "dry_run": is_dry_run
        }
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
        conn = sqlite3.connect(DB_FILE)
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
    """Endpoint untuk Grafik Garis PNL di Angular."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Ambil waktu dan PNL dari setiap penjualan (dari terlama ke terbaru)
        cursor.execute("SELECT timestamp, net_pnl FROM trades WHERE side='SELL' ORDER BY id ASC")
        rows = cursor.fetchall()
        conn.close()
        
        labels = []
        data_points = []
        cumulative_pnl = 0.0
        
        for row in rows:
            # Format waktu agar lebih rapi di chart (misal: "14 Apr, 16:30")
            labels.append(row[0]) 
            cumulative_pnl += (row[1] * 100) # Ubah ke bentuk persen (misal: 0.005 -> 0.5%)
            data_points.append(round(cumulative_pnl, 2))
            
        return {
            "status": "success",
            "labels": labels,
            "cumulative_pnl": data_points
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