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
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any
from urllib.parse import urlencode

# --- SETUP LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_log.txt", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

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
active_trade = False 
force_buy = False           # Untuk memicu test buy manual
paper_entry_price = 0.0     # Harga masuk simulasi
total_simulated_profit = 0.0 # Akumulasi PNL
trade_count = 0             # Jumlah trade

paper_usdt_balance = load_sim_balance() # Load saldo dari file
paper_coin_holdings = 0.0

os.environ['no_proxy'] = '*'
load_dotenv()

# --- KONFIGURASI ---
API_KEY = os.getenv('API_KEY').strip() if os.getenv('API_KEY') else None
SECRET_KEY = os.getenv('SECRET_KEY').strip() if os.getenv('SECRET_KEY') else None
TELE_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELE_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BASE_URL = 'https://api.mexc.com'
SYMBOL = 'BTCUSDT'
TIMEFRAME = '5m'
USDT_AMOUNT = 10.0
DRY_RUN = True  

last_update_id = 0

# --- FUNGSI UTILS & PRESISI ---

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
        res = requests.get(url, params={'symbol': SYMBOL, 'interval': TIMEFRAME, 'limit': 100}).json()
        df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (df['tp'] * df['volume']).cumsum() / df['volume'].cumsum()
        df['rsi'] = ta.rsi(df['close'], length=14)
        
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

def execute_trade(side: str, amount: float):
    global paper_entry_price, total_simulated_profit, paper_usdt_balance, paper_coin_holdings
    info = get_symbol_info(SYMBOL)
    
    ticker_res = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
    price = float(ticker_res['askPrice']) if side.upper() == 'BUY' else float(ticker_res['bidPrice'])
    
   # --- LOGIKA SIMULASI (DRY RUN) ---
    if DRY_RUN:
        if side.upper() == 'BUY':
            if paper_usdt_balance >= amount:
                paper_entry_price = price
                # Hitung berapa koin yang didapat (amount / harga)
                paper_coin_holdings = amount / price
                paper_usdt_balance -= amount
                log_paper_trade("BUY", price)
            else:
                logging.warning("⚠️ Saldo Simulasi USDT tidak cukup!")
                return None
        else: # Logic SELL Simulasi
            if paper_entry_price > 0:
                pnl_trade = (price - paper_entry_price) / paper_entry_price
                total_simulated_profit += pnl_trade
                
                # Update saldo USDT
                paper_usdt_balance += (paper_coin_holdings * price)
                paper_coin_holdings = 0.0
                
                # SIMPAN KE FILE AGAR PERMANEN
                save_sim_balance(paper_usdt_balance)
                
                log_paper_trade("SELL", price, pnl_trade)
        
        logging.info(f"SIMULASI {side}: Harga {price} | Saldo: ${paper_usdt_balance:.2f}")
        return {'price': price, 'status': 'FILLED', 'orderId': 'SIMULASI'}
    
    # --- LOGIKA REAL TRADING ---
    params = {'symbol': SYMBOL, 'side': side.upper(), 'type': 'MARKET'}
    
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
               f"💰 *Total Equity:* `{total_equity:.2f}`") # Total nilai akun

        send_telegram(msg)
    except Exception as e:
        logging.error(f"Error status command: {e}")

def handle_telegram_command(msg_text):
    global bot_active, force_buy
    
    if msg_text == "/status":
        status_tele = "🟢 ON" if bot_active else "🔴 OFF"
        status_log = "ON" if bot_active else "OFF"
        
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
        send_telegram("⚠️ *BOT STOPPED* 🔴")
        
    elif msg_text == "/start":
        bot_active = True
        send_telegram("✅ *BOT STARTED* 🟢")
    
    elif msg_text == "/reset_sim":
        global paper_usdt_balance, paper_coin_holdings, total_simulated_profit, trade_count
        paper_usdt_balance = 1000.0
        paper_coin_holdings = 0.0
        total_simulated_profit = 0.0
        trade_count = 0
        save_sim_balance(1000.0)
        send_telegram("♻️ *Simulasi di-reset!* Saldo kembali ke `$1000.00` dan PNL dibersihkan.")
    
    elif msg_text == "/help":
        msg = ("📜 *Daftar Perintah:*\n"
               "• `/start` - Aktifkan bot\n"
               "• `/stop` - Matikan bot\n"
               "• `/status` - Cek PNL & Harga\n"
               "• `/testbuy` - Tes beli saat ini juga\n"
               "• `/reset_sim` - Reset saldo mode simulasi\n")
        send_telegram(msg)

def check_commands():
    global last_update_id, force_buy
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
        res = requests.get(url, params={"offset": last_update_id+1, "timeout": 1}).json()
        
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

def monitor_position(entry_price: float):
    global active_trade
    active_trade = True
    stop_loss = entry_price * 0.994 
    highest_p = entry_price
    
    logging.info(f"Mulai Monitoring. Entry: {entry_price}, SL: {stop_loss}")

    while True:
        try:
            ticker = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()
            curr_p = float(ticker['bidPrice'])
            if curr_p > highest_p: highest_p = curr_p
            pnl = (curr_p - entry_price) / entry_price

            logging.info(f"Monitoring {SYMBOL} | Price: {curr_p} | PNL: {pnl*100:.2f}% | SL: {stop_loss:.2f}")

            if pnl >= 0.005: 
                new_sl = highest_p * 0.998 
                if new_sl > stop_loss:
                    stop_loss = new_sl
                    logging.info(f"Trailing Up! New SL: {stop_loss}")

            if curr_p <= stop_loss:
                execute_trade('SELL', USDT_AMOUNT)
                send_telegram(f"🏁 *EXIT POSITION* | PnL: `{pnl*100:.2f}%`")
                break
            
            time.sleep(3) 
        except Exception as e:
            logging.error(f"Monitor Error: {e}")
            time.sleep(5)
            
    active_trade = False

# --- THREAD LOOPS ---

def telegram_loop():
    logging.info("Jalur Telegram Siap.")
    while True:
        check_commands()
        time.sleep(1)

def trading_loop():
    global bot_active, force_buy
    logging.info(f"Jalur Trading Siap. Mode: {'DRY RUN' if DRY_RUN else 'REAL MONEY'}")
    
    while True:
        try:
            if bot_active and not active_trade:
                df = fetch_data()
                trigger_buy = False
                
                # Cek Sinyal Testing atau Sinyal Asli
                if force_buy:
                    trigger_buy = True
                    force_buy = False
                    logging.info("🛠️ Testing Buy dipicu user.")
                elif df is not None and not df.empty:
                    last = df.iloc[-2]
                    curr_rsi = last['rsi']
                    if last['close'] > (last['vwap'] * 1.01) and last['close'] > last['open'] and curr_rsi < 70:
                        trigger_buy = True
                        logging.info(f"🚀 SIGNAL BUY! RSI: {curr_rsi:.2f}")

                if trigger_buy:
                    # Ambil harga real-time untuk monitor
                    ticker = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={'symbol': SYMBOL}).json()
                    entry_p = float(ticker['price'])
                    
                    if execute_trade('BUY', USDT_AMOUNT): 
                        monitor_position(entry_p)
                
                time.sleep(20)
            else:
                time.sleep(2)
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
    print("Tekan Ctrl + C untuk berhenti total.")
    
    if not API_KEY:
        print("❌ ERROR: API KEY tidak ditemukan di file .env!")
        sys.exit()

    # Memberitahu Telegram saat bot baru dijalankan
    send_telegram("🤖 *Bot Started!* (Multitasking Mode Aktif)")
    
    # Inisialisasi Thread
    t1 = threading.Thread(target=telegram_loop)
    t2 = threading.Thread(target=trading_loop)
    
    t1.daemon = True
    t2.daemon = True
    
    t1.start()
    t2.start()
    
    try:
        while True:
            time.sleep(1) # Menjaga script tetap hidup
    except KeyboardInterrupt:
        print("\n🛑 Signal Shutdown Diterima (Ctrl+C)...")
        
        # --- FITUR SAFETY SELL SEBELUM MATI ---
        if active_trade:
            print("⚠️ Ada posisi aktif! Mencoba melakukan SELL otomatis sebelum shutdown...")
            send_telegram("⚠️ *Shutdown Alert*: Menutup posisi terbuka secara otomatis...")
            try:
                # Memanggil fungsi sell yang sudah ada di kode Anda
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