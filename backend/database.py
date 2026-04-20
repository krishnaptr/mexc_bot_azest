import os
import json
import sqlite3
import logging
from datetime import datetime
import config

def save_state(state_data):
    """Menyimpan status trading saat ini ke file JSON."""
    try:
        with open(config.STATE_FILE, "w") as f:
            json.dump(state_data, f)
    except Exception as e:
        logging.error(f"Gagal menyimpan state: {e}")

def load_state():
    """Memuat kembali memori bot saat pertama kali dijalankan."""
    if os.path.exists(config.STATE_FILE):
        try:
            with open(config.STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Gagal memuat state: {e}")
    
    # Nilai default jika file belum ada
    return {
        "active_trade": False,
        "entry_price": 0.0,
        "stop_loss": 0.0,
        "highest_p": 0.0,
        "trade_count": 0,
        "total_accumulated_profit": 0.0
    }

def save_sim_balance(balance):
    """Menyimpan saldo uang bohongan (Paper Trading) ke file txt."""
    try:
        with open("simulated_balance.txt", "w") as f:
            f.write(f"{balance:.2f}")
    except Exception as e:
        logging.error(f"Gagal menyimpan saldo simulasi: {e}")

def load_sim_balance():
    """Memuat saldo uang bohongan."""
    if os.path.exists("simulated_balance.txt"):
        try:
            with open("simulated_balance.txt", "r") as f:
                return float(f.read())
        except:
            return 1000.0
    return 1000.0

def init_db():
    """Membuat tabel database jika belum ada."""
    conn = sqlite3.connect(config.DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            symbol TEXT,
            strategy TEXT,
            mode TEXT,
            side TEXT,
            price REAL,
            gross_pnl REAL,
            net_pnl REAL
        )
    ''')
    conn.commit()
    conn.close()

def log_trade_to_db(strategy_mode: str, mode: str, side: str, symbol: str, price: float, gross_pnl: float = 0.0, net_pnl: float = 0.0):
    """Menyimpan riwayat transaksi (Beli/Jual) ke SQLite Database."""
    try:
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()
        
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        cursor.execute('''
            INSERT INTO trades (timestamp, symbol, strategy, mode, side, price, gross_pnl, net_pnl)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (timestamp, symbol, strategy_mode, mode, side, price, gross_pnl, net_pnl))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"❌ Gagal menyimpan ke Database: {e}")