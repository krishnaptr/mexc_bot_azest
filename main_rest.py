import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import pandas_ta as ta
import logging
import sys
import threading
import matplotlib
import json
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any
from urllib.parse import urlencode

STATE_FILE = "bot_state.json"

# --- SETUP LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_log.txt", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- FUNGSI AUTO-RECOVERY (ANTI-AMNESIA) ---

def save_state():
    state = {
        "active_trade": active_trade,
        "paper_entry_price": paper_entry_price,
        "stop_loss": stop_loss,
        "highest_p": highest_p,
        "trade_count": trade_count,
        "total_simulated_profit": total_simulated_profit
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logging.error(f"Gagal menyimpan state: {e}")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Gagal memuat state: {e}")
    
    return {
        "active_trade": False,
        "paper_entry_price": 0.0,
        "stop_loss": 0.0,
        "highest_p": 0.0,
        "trade_count": 0,
        "total_simulated_profit": 0.0
    }

# --- HELPER SALDO SIMULASI ---
def save_sim_balance(balance):
    try:
        with open("simulated_balance.txt", "w") as f:
            f.write(f"{balance:.2f}")
    except Exception as e:
        logging.error(f"Gagal menyimpan saldo simulasi: {e}")

def load_sim_balance():
    if os.path.exists("simulated_balance.txt"):
        try:
            with open("simulated_balance.txt", "r") as f:
                return float(f.read())
        except:
            return 1000.0  # Jika file rusak, balik ke 1000
    return 1000.0 # Modal awal pertama kali bot dijalankan

# --- STATE KONTROL ---
bot_active = True  
force_buy = False  # Untuk memicu test buy manual
paper_usdt_balance = load_sim_balance() # Load saldo dari file
paper_coin_holdings = 0.0
USE_HARD_TP = False

# Load state dari file JSON
state_data = load_state()
active_trade = state_data["active_trade"]
paper_entry_price = state_data["paper_entry_price"]
stop_loss = state_data.get("stop_loss", 0.0)
highest_p = state_data.get("highest_p", 0.0)
trade_count = state_data["trade_count"]
total_simulated_profit = state_data["total_simulated_profit"]
stop_loss = 0.0
highest_p = 0.0
last_update_id = 0

if active_trade:
    logging.info(f"🔄 Auto-Recovery aktif! Melanjutkan trade yang menggantung. Harga Entry: {paper_entry_price}")
os.environ['no_proxy'] = '*'
load_dotenv()

# --- KONFIGURASI ---
API_KEY = os.getenv('API_KEY').strip() if os.getenv('API_KEY') else None
SECRET_KEY = os.getenv('SECRET_KEY').strip() if os.getenv('SECRET_KEY') else None
TELE_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELE_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BASE_URL = 'https://api.mexc.com'
SYMBOL = 'SIRENUSDT'
TIMEFRAME = '5m'
USDT_AMOUNT = 10.0
DRY_RUN = True  

# --- GLOBAL STRATEGY SETTINGS ---
STRATEGY_MODE = "SCALP"

STRATEGIES = {
    "TREND": {
        "rsi_min": 45,
        "rsi_max": 68,
        "vol_mult": 1.5,
        "use_ema_200": True,
        "tp_percent": 0.03,      # Target 3%
        "sl_atr_mult": 1.5,
        "trail_start": 0.008,    # Trailing mulai aktif di profit 0.8%
        "trail_dist": 0.005      # Jarak SL dari puncak adalah 0.5%
    },
    "SCALP": {
        "rsi_min": 30,           # Lebih rendah untuk tangkap pantulan
        "rsi_max": 50,
        "vol_mult": 1.2,         # Lebih sensitif terhadap volume
        "use_ema_200": False,    # Abaikan tren besar
        "tp_percent": 0.012,     # Target 1.2% (cepat bungkus)
        "sl_atr_mult": 1.0,
        "trail_start": 0.004,    # Trailing mulai aktif lebih cepat di 0.4%
        "trail_dist": 0.002      # Jarak SL sangat ketat: 0.2% saja
    }
}

# --- FUNGSI UTILS & PRESISI ---

def check_spread(symbol, max_spread_percent=2.0):
    """
    Mengecek selisih harga bid/ask langsung via API MEXC.
    """
    try:
        # Endpoint MEXC untuk ticker harga (Order Book Shortcut)
        url = f"{BASE_URL}/api/v3/ticker/bookTicker"
        params = {'symbol': symbol}
        
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            bid_price = float(data['bidPrice'])
            ask_price = float(data['askPrice'])
            
            # Hitung persentase spread
            spread_percent = ((ask_price - bid_price) / bid_price) * 100
            
            if spread_percent > max_spread_percent:
                logging.warning(f"⚠️ Sinyal diabaikan! Spread {symbol} terlalu lebar: {spread_percent:.2f}%")
                return False, spread_percent
            
            return True, spread_percent
        else:
            logging.error(f"❌ MEXC API Error: {data}")
            return False, 0.0
            
    except Exception as e:
        logging.error(f"❌ Gagal mengecek spread: {e}")
        return False, 0.0

def round_step(value: float, step_size: float) -> float:
    if step_size == 0: return float(value)
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    return round(float(value) - (float(value) % float(step_size)), precision)

def get_symbol_info(symbol: str):
    try:
        res = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", params={'symbol': symbol}, timeout=5).json()
        for s in res['symbols']:
            if s['symbol'] == symbol:
                info = {'price_step': 0.01, 'qty_step': 0.000001} # Default
                for f in s['filters']:
                    if f['filterType'] == 'PRICE_FILTER':
                        info['price_step'] = float(f['tickSize'])
                    if f['filterType'] == 'LOT_SIZE':
                        info['qty_step'] = float(f['stepSize'])
                return info
    except Exception as e:
        logging.error(f"Gagal mengambil info simbol: {e}")
    return {'price_step': 0.01, 'qty_step': 0.000001}


# --- FUNGSI PRIVATE REQUEST ---

def get_server_time() -> int:
    try:
        return requests.get(f"{BASE_URL}/api/v3/time").json()['serverTime']
    except:
        return int(time.time() * 1000)

def generate_signature(params: Dict[str, Any]) -> str:
    query_string = urlencode(params)
    return hmac.new(SECRET_KEY.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def mexc_request(method: str, path: str, params: Dict[str, Any] = None) -> Dict:
    if params is None: params = {}
    params['timestamp'] = get_server_time()
    params['recvWindow'] = 60000
    params['signature'] = generate_signature(params)
    headers = {'X-MEXC-APIKEY': API_KEY}
    url = f"{BASE_URL}{path}"
    try:
        # Tambahkan timeout 10 detik
        if method == 'GET':
            return requests.get(url, params=params, headers=headers, timeout=10).json()
        return requests.post(url, params=params, headers=headers, timeout=10).json()
    except Exception as e:
        logging.error(f"Request Error (Koneksi): {e}")
        return {"error": "connection_failed"}

# --- FUNGSI DATA & INDIKATOR ---

def fetch_data() -> Optional[pd.DataFrame]:
    try:
        url = f"{BASE_URL}/api/v3/klines"
        # Limit dinaikkan ke 250 agar EMA 200 bisa terbentuk dengan sempurna
        res = requests.get(url, params={'symbol': SYMBOL, 'interval': TIMEFRAME, 'limit': 250}).json()
        df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        # --- INDIKATOR LAMA ---
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['rsi'] = ta.rsi(df['close'], length=14)
        
        # --- INDIKATOR BARU (POWER FILTER) ---
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['ema_200'] = ta.ema(df['close'], length=200)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['vol_sma'] = ta.sma(df['volume'], length=20)
        
        return df
    except Exception as e:
        logging.error(f"Error data: {e}")
        return None

def get_balance():
    res = mexc_request('GET', '/api/v3/account')
    # Inisialisasi saldo kosong untuk aset yang sedang digunakan
    asset_name = SYMBOL.replace('USDT', '')
    bal = {'USDT': 0.0, asset_name: 0.0} 
    
    if 'balances' in res:
        for b in res['balances']:
            if b['asset'] in ['USDT', asset_name]:
                bal[b['asset']] = float(b['free'])
    return bal

# --- SISTEM TRADING ---

def log_paper_trade(side: str, price: float, pnl: float = 0.0):
    """TAMBAHAN: Mencatat transaksi ke file teks."""
    global trade_count
    with open("paper_trading_results.txt", "a", encoding="utf-8") as f:
        msg = f"[{datetime.now()}] {side} {SYMBOL} @ {price}"
        if side == "SELL":
            msg += f" | PNL Trade: {pnl*100:.2f}%"
            trade_count += 1
        f.write(msg + "\n")

def execute_trade(side: str, amount: float, order_type: str = "MARKET", forced_price: float = None):
    global paper_entry_price, total_simulated_profit, paper_usdt_balance, paper_coin_holdings, active_trade, trade_count
    
    info = get_symbol_info(SYMBOL)
    ticker_res = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
    
    # --- LOGIKA HARGA BARU ---
    if forced_price:
        price = forced_price  # Gunakan harga limit jika ada
    else:
        # Jika tidak ada forced_price, gunakan logika Ask/Bid market seperti biasa
        price = float(ticker_res['askPrice']) if side.upper() == 'BUY' else float(ticker_res['bidPrice'])
    
    # --- LOGIKA SIMULASI (Selebihnya kode kamu tetap sama) ---
    if DRY_RUN:
        if side.upper() == 'BUY':
            if paper_usdt_balance >= amount:
                paper_entry_price = price
                paper_coin_holdings = amount / price
                paper_usdt_balance -= amount
                active_trade = True 
                
                save_sim_balance(paper_usdt_balance)
                save_state()
                log_paper_trade("BUY", price)

                type_tag = "LIMIT" if forced_price else "MARKET"
                msg = (f"🚀 *SIMULASI {type_tag} BUY EXECUTED*\n"
                       f"Symbol: `{SYMBOL}`\n"
                       f"Price: `{price}`\n"
                       f"Amount: `${amount}`")
                send_telegram(msg)

            else:
                logging.warning("⚠️ Saldo Simulasi USDT tidak cukup!")
                return None
        else: # Logic SELL Simulasi
            if paper_entry_price > 0:
                pnl_trade = (price - paper_entry_price) / paper_entry_price
                total_simulated_profit += pnl_trade
                
                paper_usdt_balance += (paper_coin_holdings * price)
                paper_coin_holdings = 0.0
                active_trade = False # Tandai posisi sudah ditutup
                trade_count += 1     # Tambah hitungan trade
                
                save_sim_balance(paper_usdt_balance)
                save_state()  # <--- SIMPAN STATE (RECOVERY)
                log_paper_trade("SELL", price, pnl_trade)

                # --- TAMBAHKAN INI ---
                emoji = "💰" if pnl_trade > 0 else "📉"
                msg = (f"{emoji} *SIMULASI SELL EXECUTED*\n"
                       f"Symbol: `{SYMBOL}`\n"
                       f"Exit Price: `{price}`\n"
                       f"PNL: *{pnl_trade*100:.2f}%*")
                send_telegram(msg)
    
        logging.info(f"SIMULASI {side}: Harga {price} | Saldo: ${paper_usdt_balance:.2f}")
        return {'price': price, 'status': 'FILLED', 'orderId': 'SIMULASI'}
    
    # --- LOGIKA REAL TRADING ---
    params = {'symbol': SYMBOL, 'side': side.upper(), 'type': order_type}
    
    if order_type == "LIMIT":
        params['price'] = "{:f}".format(price)
        params['quantity'] = "{:f}".format(round_step(amount / price, info['qty_step']))
    elif side.upper() == 'BUY':
        params['quoteOrderQty'] = round_step(amount, info['price_step'])
    
    if side.upper() == 'BUY':
        params['quoteOrderQty'] = round_step(amount, info['price_step'])
        res = mexc_request('POST', '/api/v3/order', params)
        
        if 'orderId' in res:
            try:
                exec_qty = float(res.get('origQty', 0))
                hard_sl_price = round_step(price * 0.98, info['price_step'])
                
                sl_params = {
                    'symbol': SYMBOL,
                    'side': 'SELL',
                    'type': 'STOP_LOSS_LIMIT',
                    'quantity': "{:f}".format(round_step(exec_qty * 0.99, info['qty_step'])),
                    'price': "{:f}".format(hard_sl_price),
                    'stopPrice': "{:f}".format(hard_sl_price)
                }
                
                mexc_request('POST', '/api/v3/order', sl_params)
                logging.info(f"🛡️ Sabuk Pengaman Terpasang: {hard_sl_price}")
                send_telegram(f"🛡️ *Sabuk Pengaman Terpasang*\nHard SL: `{hard_sl_price}`")
            except Exception as e:
                logging.error(f"Gagal memasang Sabuk Pengaman: {e}")
        return res

    else:
        # 1. Batalkan Hard SL
        try:
            mexc_request('DELETE', '/api/v3/openOrders', {'symbol': SYMBOL})
            time.sleep(0.5) 
        except: 
            pass
        
        # 2. Ambil saldo
        asset_name = SYMBOL.replace('USDT', '')
        bal = get_balance()
        qty = bal.get(asset_name, 0.0)
        
        if qty <= 0: 
            logging.warning(f"⚠️ Percobaan SELL tapi saldo {asset_name} kosong.")
            return None
        
        # 3. Eksekusi Jual Market
        params['quantity'] = "{:f}".format(round_step(qty * 0.99, info['qty_step']))
        res_sell = mexc_request('POST', '/api/v3/order', params)
        
        # --- NOTIFIKASI TELEGRAM ---
        if 'orderId' in res_sell:
            # Ambil harga jual (jika tidak ada di response, gunakan harga ticker terakhir)
            exit_price = float(res_sell.get('price', price))
            pnl_pct = 0.0
            
            # Hitung PNL jika ada data harga masuk
            if paper_entry_price > 0:
                pnl_pct = (exit_price - paper_entry_price) / paper_entry_price
            
            emoji = "💰" if pnl_pct > 0 else "📉"
            msg = (f"{emoji} *TRADE COMPLETED*\n\n"
                   f"Symbol: `{SYMBOL}`\n"
                   f"Entry: `{paper_entry_price:.4f}`\n"
                   f"Exit: `{exit_price:.4f}`\n"
                   f"Net PNL: *{pnl_pct*100:.2f}%*")
            
            send_telegram(msg)
            # Reset harga entry setelah trade selesai
            paper_entry_price = 0 
            
        return res_sell

# --- TELEGRAM & MONITOR ---

def send_telegram(message: str):
    if not TELE_TOKEN: return
    try:
        # Tambahkan timeout agar bot tidak 'hang' jika internet putus
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      data={"chat_id": TELE_CHAT_ID, "text": message, "parse_mode": "Markdown"},
                      timeout=5) 
    except Exception as e:
        logging.error(f"Telegram gagal (mungkin internet putus): {e}")

def handle_status_command(status):
    global paper_entry_price, paper_usdt_balance, paper_coin_holdings, total_simulated_profit, trade_count
    try:
        ticker = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
        current_price = float(ticker['bidPrice'])
       # 1. Ambil Saldo (Live atau Simulasi)
        asset_name = SYMBOL.replace('USDT', '')
        if not DRY_RUN:
            bal = get_balance()
            usdt_display = bal.get('USDT', 0.0)
            coin_display = bal.get(asset_name, 0.0)
        else:
            # Menggunakan saldo simulasi
            usdt_display = paper_usdt_balance
            coin_display = paper_coin_holdings

        # 2. Hitung PNL berjalan
        floating_pnl_str = ""
        total_equity = usdt_display
        if active_trade and paper_entry_price > 0:
            f_pnl = (current_price - paper_entry_price) / paper_entry_price
            floating_pnl_str = f"\n🔄 *PNL Berjalan:* `{f_pnl*100:.2f}%`"
            current_value = paper_coin_holdings * current_price
            total_equity += current_value

        pnl_info = f"\n💰 *Total Profit (Selesai):* `{total_simulated_profit*100:.2f}%` ({trade_count} trades)"
        
       # 3. Rakit Pesan
        msg = (f"🤖 *Status Bot `{status}`*\n"
               f"Mode: `{'SIMULASI' if DRY_RUN else 'LIVE'}`\n"
               f"Harga {SYMBOL}: `${current_price}`"
               f"{floating_pnl_str}"
               f"{pnl_info}\n\n"
               f"🏦 *Info Saldo:*\n"
               f"💵 USDT (Tersedia): `{usdt_display:.2f}`\n"
               f"🪙 {asset_name} (Dimiliki): `{coin_display:.6f}`\n"
               f"💰 *Total Equity:* `{total_equity:.2f}`")

        send_telegram(msg)
    except Exception as e:
        logging.error(f"Error status command: {e}")

def handle_telegram_command(msg_text):
    global bot_active, force_buy, active_trade, stop_loss, highest_p
    global paper_usdt_balance, paper_coin_holdings, total_simulated_profit, trade_count, paper_entry_price
    global STRATEGY_MODE

    if msg_text == "/mode_trend":
        STRATEGY_MODE = "TREND"
        send_telegram("🚀 Mode diubah ke: *TREND FOLLOWING*\n(Fokus EMA 200 & Profit Besar)")
    
    elif msg_text == "/mode_scalp":
        STRATEGY_MODE = "SCALP"
        send_telegram("⚡ Mode diubah ke: *SCALPING/REBOUND*\n(Fokus RSI Bawah & Quick Profit)")

    elif msg_text == "/status":
        status_tele = ""
        status_log = "ON" if bot_active else "OFF"
        msg = f"🤖 🟢 ON" if bot_active else "🔴 OFF <==> *Bot Status*\nMode: `{STRATEGY_MODE}`\nActive Trade: `{active_trade}`"
        logging.info(f"User meminta status. Bot saat ini: {status_log}") 
        handle_status_command(status_tele) # Kirim teks status
        send_chart() # Kirim gambar grafik

    elif msg_text == "/testbuy":
        # Tombol konfirmasi
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Ya, Beli Sekarang", "callback_data": "confirm_buy"},
                {"text": "❌ Batal", "callback_data": "cancel_buy"}
            ]]
        }
        mode = "SIMULASI" if DRY_RUN else "ASLI (LIVE)"
        msg = f"⚠️ *KONFIRMASI TEST BUY*\nMode: `{mode}`\nApakah Anda yakin ingin melakukan pembelian manual?"
        
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      json={"chat_id": TELE_CHAT_ID, "text": msg, "reply_markup": keyboard, "parse_mode": "Markdown"})
        
    elif msg_text == "/stop":
        bot_active = False
        if active_trade:
            send_telegram("⚠️ *BOT STOPPED:* Menutup posisi aktif sebelum nonaktif...")
            execute_trade('SELL', USDT_AMOUNT)
            active_trade = False
            save_state()
        send_telegram("🛑 *BOT STOPPED & POSITION CLEARED* 🔴")
    
    elif msg_text == "/panic":
        send_telegram("🚨 *PANIC BUTTON TRIGGERED!* 🚨")
        
        # 1. Jual posisi jika ada
        if active_trade:
            send_telegram("📉 Sedang melikuidasi posisi...")
            execute_trade('SELL', USDT_AMOUNT)
            active_trade = False
        else:
            send_telegram("ℹ️ Tidak ada posisi aktif untuk dijual.")

        # 2. Matikan Bot
        bot_active = False
        save_state()
        
        send_telegram("🛑 *SISTEM DIMATIKAN TOTAL.* Bot tidak akan mencari sinyal sampai kamu ketik `/start` kembali.")

    elif msg_text == "/start":
        bot_active = True
        send_telegram("✅ *BOT STARTED* 🟢")
    
    elif msg_text == "/reset_sim":
        paper_usdt_balance = 1000.0
        paper_coin_holdings = 0.0
        total_simulated_profit = 0.0
        trade_count = 0
        active_trade = False
        paper_entry_price = 0.0
        
        save_sim_balance(1000.0)
        save_state() # Simpan reset ke JSON
        send_telegram("♻️ *Simulasi di-reset!* Saldo kembali ke `$1000.00` dan riwayat dibersihkan.")

    elif msg_text == "/exit":
        if active_trade:
            send_telegram("⚠️ *FORCED EXIT:* Menutup posisi sekarang...")
            # Eksekusi Jual
            execute_trade('SELL', USDT_AMOUNT)
            
            # Reset variabel state secara manual untuk keamanan
            active_trade = False
            paper_entry_price = 0.0
            stop_loss = 0.0
            highest_p = 0.0
            save_state()
            
            send_telegram("✅ *Posisi berhasil ditutup.* Bot tetap aktif mencari sinyal baru.")
        else:
            send_telegram("ℹ️ *Tidak ada posisi aktif* yang perlu ditutup.")    
    
    elif msg_text == "/help":
        msg = ("📜 *Daftar Perintah:*\n"
               "• `/start` - Aktifkan bot\n"
               "• `/stop` - Matikan bot (tanpa jual aset)\n"
               "• `/exit` - Jual paksa (bot tetap aktif mencari sinyal baru)\n"
               "• `/panic` - *Jual paksa & Matikan bot total* 🚨\n"
               "• `/status` - Cek PNL & Harga\n"
               "• `/testbuy` - Tes beli saat ini juga\n"
               "• `/mode_trend` - Ubah ke mode Trend Following\n"
               "• `/mode_scalp` - Ubah ke mode Scalping\n"
               "• `/reset_sim` - Reset saldo mode simulasi\n")
        send_telegram(msg)

def check_commands():
    global last_update_id, force_buy
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
        res = requests.get(url, params={"offset": last_update_id+1, "timeout": 1}).json()
        updates = res.get("result", [])
        if updates:
            # Update ID TERLEBIH DAHULU sebelum loop proses
            last_update_id = updates[-1]["update_id"]
            for u in res.get("result", []):
                last_update_id = u["update_id"]
                
                # --- CEK PESAN TEKS ---
                if "message" in u:
                    user_id = str(u["message"].get("from", {}).get("id"))
                    msg_text = u["message"].get("text")
                    if user_id == str(TELE_CHAT_ID):
                        handle_telegram_command(msg_text)
                
                # --- CEK KLIK TOMBOL (Callback Query) ---
                elif "callback_query" in u:
                    cb = u["callback_query"]
                    user_id = str(cb.get("from", {}).get("id"))
                    cb_data = cb.get("data")
                    cb_id = cb.get("id")
                    
                    if user_id == str(TELE_CHAT_ID):
                        if cb_data == "confirm_buy":
                            if not active_trade:
                                force_buy = True
                                send_telegram("🚀 *Konfirmasi Diterima:* Menjalankan order...")
                            else:
                                send_telegram("❌ *Gagal:* Posisi masih aktif.")
                        elif cb_data == "cancel_buy":
                            send_telegram("☕ *Dibatalkan:* Tidak ada order yang dibuat.")
                        
                        # Memberitahu Telegram bahwa callback sudah diproses (biar loading di tombol hilang)
                        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery", 
                                    data={"callback_query_id": cb_id})
    except Exception as e:
        logging.error(f"Error checking Telegram updates: {e}")

def monitor_position():
    global active_trade, stop_loss, highest_p, paper_entry_price, STRATEGY_MODE
    
    # --- AMBIL KONFIGURASI SESUAI MODE ---
    conf = STRATEGIES[STRATEGY_MODE]
    USE_HARD_TP = True
    target_profit_percent = conf['tp_percent']
    tp_price = paper_entry_price * (1 + target_profit_percent)
    
    # Inisialisasi awal jika SL masih 0
    if stop_loss == 0:
        # Default SL jika ATR gagal (misal 1% di bawah entry)
        stop_loss = paper_entry_price * 0.99 
        highest_p = paper_entry_price
        logging.info(f"[{STRATEGY_MODE}] Monitoring Start. TP: {tp_price:.4f}")

    try:
        # 1. Ambil Harga Saat Ini (Bid untuk Jual)
        ticker = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
        curr_p = float(ticker['bidPrice'])
        
        # Update harga tertinggi untuk patokan Trailing
        if curr_p > highest_p: 
            highest_p = curr_p
            
        pnl = (curr_p - paper_entry_price) / paper_entry_price

        # Log Monitoring berkala
        logging.info(f"[{STRATEGY_MODE}] {SYMBOL} | Price: {curr_p} | PNL: {pnl*100:.2f}% | SL: {stop_loss:.4f} | TP: {tp_price:.4f}")

        # 2. LOGIKA HARD TP
        if USE_HARD_TP and curr_p >= tp_price:
            logging.info(f"🎯 [{STRATEGY_MODE}] HARD TP HIT! Menjual...")
            execute_trade('SELL', USDT_AMOUNT)
            send_telegram(f"💰 *HARD TP EXECUTED*\nMode: `{STRATEGY_MODE}`\nNet PnL: *{pnl*100:.2f}%*")
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            save_state()
            return

        # 3. LOGIKA TRAILING STOP (DINAMIS)
        # Ambil trail_start dan trail_dist dari config
        if pnl >= conf['trail_start']: 
            # New SL = Harga tertinggi dikurangi jarak trailing sesuai mode
            new_sl = highest_p * (1 - conf['trail_dist']) 
            
            if new_sl > stop_loss:
                # Pastikan ada jarak aman 0.05% dari harga sekarang agar tidak langsung kena
                stop_loss = min(new_sl, curr_p * 0.9995) 
                logging.info(f"📈 Trailing Up! New SL: {stop_loss:.4f}")
                save_state() 

        # 4. LOGIKA EXIT (Sell jika harga menyentuh SL)
        if curr_p <= stop_loss:
            execute_trade('SELL', USDT_AMOUNT)
            emoji = "🏁" if pnl < 0 else "💰"
            send_telegram(f"{emoji} *POSITION CLOSED*\nMode: `{STRATEGY_MODE}`\nNet PnL: *{pnl*100:.2f}%*")
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            save_state()

    except Exception as e:
        logging.error(f"Monitor Error: {e}")

# --- THREAD LOOPS ---

def telegram_loop():
    logging.info("Jalur Telegram Siap.")
    while True:
        check_commands()
        time.sleep(1)

def trading_loop():
    global bot_active, force_buy, active_trade, stop_loss, highest_p, STRATEGY_MODE
    logging.info(f"Jalur Trading Siap. Mode: {'DRY RUN' if DRY_RUN else 'REAL MONEY'} | Strategy: {STRATEGY_MODE}")
    
    while True:
        try:
            if not bot_active:
                time.sleep(2)
                continue

            if active_trade:
                monitor_position() 
                time.sleep(2) 
            else:
                df = fetch_data()
                trigger_buy = False
                
                # Ambil konfigurasi aktif berdasarkan mode
                conf = STRATEGIES[STRATEGY_MODE] 

                if force_buy:
                    trigger_buy = True
                    force_buy = False
                    if df is not None and not df.empty:
                        last_atr = df.iloc[-2]['atr']
                        curr_price = df.iloc[-2]['close']
                        stop_loss = curr_price - (last_atr * 1.5) if not pd.isna(last_atr) else curr_price * 0.99
                        highest_p = curr_price
                
                elif df is not None and not df.empty:
                    last = df.iloc[-2]
                    if pd.isna(last['ema_200']) or pd.isna(last['vol_sma']):
                        time.sleep(2)
                        continue
                    
                    ticker_realtime = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()
                    curr_price = float(ticker_realtime['askPrice'])
                    curr_rsi = last['rsi'] 
                    
                    logging.info(f"🔍 [{STRATEGY_MODE}] Scan {SYMBOL} | RSI: {curr_rsi:.2f} | Price: {curr_price}")

                    # --- LOGIKA FILTER DINAMIS ---
                    # Jika TREND = Cek EMA200. Jika SCALP = Anggap True (Abaikan)
                    if conf["use_ema_200"]:
                        is_uptrend = (last['ema_50'] > last['ema_200']) and (curr_price > last['ema_200'])
                    else:
                        is_uptrend = True 

                    above_vwap = (curr_price > last['vwap']) and (curr_price < last['vwap'] * 1.015)
                    volume_breakout = last['volume'] > (last['vol_sma'] * conf["vol_mult"]) 
                    rsi_healthy = conf["rsi_min"] < curr_rsi < conf["rsi_max"] 
                    bullish_candle = curr_price > last['open']

                    if is_uptrend and above_vwap and volume_breakout and rsi_healthy and bullish_candle:
                        trigger_buy = True
                        stop_loss = curr_price - (last['atr'] * conf["sl_atr_mult"]) 
                        highest_p = curr_price
                        logging.info(f"🚀 {STRATEGY_MODE} SIGNAL VALID! SL: {stop_loss:.4f}")

                if trigger_buy and not active_trade:
                    # Naikkan batas toleransi spread ke 2.5% karena sekarang ada Limit Order
                    is_safe, current_spread = check_spread(SYMBOL, 2.5) 
                    
                    if is_safe:
                        # Ambil data harga bid/ask terbaru untuk penentuan harga limit
                        ticker_res = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()
                        bid_price = float(ticker_res['bidPrice'])
                        ask_price = float(ticker_res['askPrice'])

                        if current_spread <= 0.8:
                            # 1. MARKET BUY (Spread tipis, hajar langsung)
                            logging.info(f"✅ Spread Tipis ({current_spread:.2f}%). Menjalankan MARKET BUY...")
                            execute_trade('BUY', USDT_AMOUNT) 
                        else:
                            # 2. LIMIT BUY (Spread agak lebar, kita antre)
                            # Strategi: Antre di harga Bid + 5% dari jarak spread agar posisi di depan
                            limit_price = bid_price + (ask_price - bid_price) * 0.05
                            logging.info(f"🟡 Spread Lebar ({current_spread:.2f}%). Menjalankan LIMIT BUY di {limit_price}...")
                            execute_trade('BUY', USDT_AMOUNT, order_type="LIMIT", forced_price=limit_price)
                    else:
                        # 3. IGNORE (Spread terlalu berbahaya/di atas 2.5%)
                        msg = f"🚫 *SIGNAL IGNORED*\nSymbol: `{SYMBOL}`\nSpread: `{current_spread:.2f}%` (Terlalu Lebar)"
                        send_telegram(msg)
                
                # Jeda scan reguler
                for _ in range(20): 
                    if not bot_active or active_trade: break
                    time.sleep(1)

        except Exception as e:
            logging.error(f"⚠️ Error di Trading Loop: {e}")
            time.sleep(10)

# --- CHART ---
def send_chart():
    try:
        df = fetch_data()
        if df is None or df.empty: return
        
        df_plot = df.tail(30).copy()
        plt.clf() 
        plt.figure(figsize=(10, 6))
        plt.plot(df_plot['timestamp'], df_plot['close'], label='Price', color='#1f77b4', linewidth=2)
        plt.plot(df_plot['timestamp'], df_plot['vwap'].tail(30), label='VWAP', color='#ff7f0e', linestyle='--')
        plt.title(f"Chart {SYMBOL} - {datetime.now().strftime('%H:%M:%S')}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        chart_path = "current_chart.png"
        plt.savefig(chart_path)
        plt.close('all')
        
        with open(chart_path, 'rb') as photo:
            requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendPhoto", 
                          params={'chat_id': TELE_CHAT_ID}, files={'photo': photo}, timeout=10)
        
        if os.path.exists(chart_path): os.remove(chart_path)
            
    except Exception as e:
        logging.error(f"Gagal kirim chart: {e}")

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print("--- BOT MEXC REST API V3 ---")
    if force_buy:
        send_telegram("🤖 *Bot Started!* Mode: AUTOMATIC SCANNING")
    else:
        send_telegram("🤖 *Bot Started!* Mode: MANUAL SCANNING")
    print("Tekan Ctrl + C untuk berhenti total.")
    
    # 1. Validasi API Key
    if not API_KEY:
        logging.error("❌ ERROR: API KEY tidak ditemukan!")
        sys.exit()
    
    # 3. Inisialisasi Multitasking (Threading)
    t1 = threading.Thread(target=telegram_loop)
    t2 = threading.Thread(target=trading_loop)
    
    t1.daemon = True # Agar thread mati otomatis saat script utama mati
    t2.daemon = True
    
    t1.start()
    t2.start()
    
    # 4. Loop Utama untuk Menjaga Program Tetap Hidup
    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        bot_active = False  # Hentikan semua loop trading & telegram segera!
        print("\n🛑 Signal Shutdown Diterima (Ctrl+C)...")
        # Beri jeda 1 detik agar thread yang sedang berjalan bisa membaca bot_active = False
        time.sleep(1) 

        if active_trade:
            print("⚠️ Ada posisi aktif! Mencoba melakukan SELL otomatis...")
            send_telegram("⚠️ *Shutdown Alert*: Menutup posisi sebelum offline...")
            try:
                # Pastikan execute_trade sudah mendukung SELL
                execute_trade('SELL', USDT_AMOUNT)
                print("✅ Posisi berhasil ditutup.")
            except Exception as e:
                print(f"❌ Gagal menutup posisi: {e}")
        else:
            print("✅ Tidak ada posisi aktif. Aman untuk dimatikan.")

        try:
            send_telegram("🛑 *Bot Shutdown Selesai*\nStatus: Offline")
        except:
            pass
            
        print("Bot Berhenti Total. Sampai jumpa!")
        sys.exit(0)