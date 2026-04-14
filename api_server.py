from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import uvicorn
import config

# Inisialisasi Aplikasi Web
app = FastAPI(title="MEXC Bot API Server", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gunakan config di dalam fungsi
DB_FILE = config.DB_FILE
STATE_FILE = config.STATE_FILE

def read_bot_state():
    """Membaca memori terakhir bot dari file JSON."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except: pass
    return {}

@app.get("/api/stats")
def get_bot_stats():
    """Endpoint untuk Kartu Statistik di Dashboard Atas."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # 1. Hitung Total Trade (Hanya yang SELL yang dihitung selesai)
        cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL'")
        total_trades = cursor.fetchone()[0] or 0
        
        # 2. Hitung Total Profit Bersih (Net PNL)
        cursor.execute("SELECT SUM(net_pnl) FROM trades WHERE side='SELL'")
        sum_pnl = cursor.fetchone()[0] or 0.0
        
        # 3. Hitung Win Rate
        cursor.execute("SELECT COUNT(*) FROM trades WHERE side='SELL' AND net_pnl > 0")
        winning_trades = cursor.fetchone()[0] or 0
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        conn.close()
        
        # Baca status dari file state bot
        state = read_bot_state()
        
        return {
            "status": "success",
            "active_trade": state.get("active_trade", False),
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "total_net_pnl_percent": round(sum_pnl * 100, 2)
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/history")
def get_trade_history():
    """Endpoint untuk Tabel Riwayat Transaksi."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row # Ubah format baris jadi Dictionary
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

if __name__ == "__main__":
    print("🚀 API Server berjalan di http://localhost:8000")
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)