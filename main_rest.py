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
import json
import matplotlib
matplotlib.use('Agg') # Mode backend untuk render gambar tanpa buka window UI
import matplotlib.pyplot as plt
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional, Dict, Any
from urllib.parse import urlencode

# File untuk menyimpan memori bot agar tidak lupa ingatan saat direstart
STATE_FILE = "bot_state.json" 

# --- SETUP LOGGING ---
# Mengatur agar log tampil di terminal sekaligus tersimpan di file trading_log.txt
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
    """Menyimpan status trading saat ini ke file JSON agar aman jika mati lampu/crash."""
    state = {
        "active_trade": active_trade,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "highest_p": highest_p,
        "trade_count": trade_count,
        "total_accumulated_profit": total_accumulated_profit
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        logging.error(f"Gagal menyimpan state: {e}")

def load_state():
    """Memuat kembali memori bot saat pertama kali dijalankan."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
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

# --- HELPER SALDO SIMULASI ---
def save_sim_balance(balance):
    """Menyimpan saldo uang bohongan (Paper Trading) ke file txt."""
    try:
        with open("simulated_balance.txt", "w") as f:
            f.write(f"{balance:.2f}")
    except Exception as e:
        logging.error(f"Gagal menyimpan saldo simulasi: {e}")

def load_sim_balance():
    """Memuat saldo uang bohongan. Default modal awal adalah $1000."""
    if os.path.exists("simulated_balance.txt"):
        try:
            with open("simulated_balance.txt", "r") as f:
                return float(f.read())
        except:
            return 1000.0
    return 1000.0

# --- STATE KONTROL GLOBAL ---
bot_active = True  
force_buy = False  
paper_usdt_balance = load_sim_balance()
paper_coin_holdings = 0.0

# Muat memori terakhir dari file JSON
state_data = load_state()
active_trade = state_data["active_trade"]
entry_price = state_data["entry_price"]
stop_loss = state_data.get("stop_loss", 0.0)
highest_p = state_data.get("highest_p", 0.0)
trade_count = state_data["trade_count"]
total_accumulated_profit = state_data["total_accumulated_profit"]

last_update_id = 0
trigger_scan = threading.Event()

if active_trade:
    logging.info(f"🔄 Auto-Recovery aktif! Melanjutkan trade yang menggantung. Harga Entry: {entry_price}")
os.environ['no_proxy'] = '*'
load_dotenv()

# --- KONFIGURASI API & USER ---
API_KEY = os.getenv('API_KEY').strip() if os.getenv('API_KEY') else None
SECRET_KEY = os.getenv('SECRET_KEY').strip() if os.getenv('SECRET_KEY') else None
TELE_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELE_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

BASE_URL = 'https://api.mexc.com'
SYMBOL = 'ALGOUSDT'
USDT_AMOUNT = 50.0   # Nominal uang per transaksi
DRY_RUN = True       # True = Simulasi/Paper Trading, False = Uang Asli
EXCHANGE_FEE = 0.001 # MEXC Spot (Maksimal Taker + Taker = 0.10% Total)
# --- GLOBAL STRATEGY SETTINGS ---
STRATEGY_MODE = "SCALP" # Mode default saat bot pertama menyala

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
        "rsi_min": 20, "rsi_max": 52,     # Jangkauan RSI oversold sampai area netral bawah
        "vol_mult": 1.0,                  # Syarat volume meledak (1.0 = normal)
        "use_ema_200": True,              # Wajib EMA200 untuk hindari pisau jatuh
        "tp_percent": 0.015,              # Target profit keras (1.5%)
        "sl_atr_mult": 2.5,               # Jarak Stop Loss dari ATR
        "trail_start": 0.005,             # Naikkan dari 0.007 ke 0.01 (Bot baru pasang jaring saat profit 1%)
        "trail_dist": 0.003,              # Jarak jaring dari puncak adalah 0.3%
        "delay_scan": 10,                 # Scan setiap 10 detik
        "use_hard_tp": False              
    }
}

# --- FUNGSI UTILS & PRESISI ---
def check_spread(symbol, max_spread_percent=2.0):
    """Mengecek selisih Bid/Ask. Jika selisih > 2%, sinyal batal karena rawan rugi instan."""
    try:
        url = f"{BASE_URL}/api/v3/ticker/bookTicker"
        response = requests.get(url, params={'symbol': symbol}, timeout=10)
        data = response.json()
        
        if response.status_code == 200:
            bid_price = float(data['bidPrice'])
            ask_price = float(data['askPrice'])
            spread_percent = ((ask_price - bid_price) / bid_price) * 100
            
            if spread_percent > max_spread_percent:
                logging.warning(f"⚠️ Sinyal diabaikan! Spread terlalu lebar: {spread_percent:.2f}%")
                return False, spread_percent
            return True, spread_percent
        else:
            return False, 0.0
    except Exception as e:
        logging.error(f"❌ Gagal mengecek spread: {e}")
        return False, 0.0

def round_step(value: float, step_size: float) -> float:
    """Membulatkan angka sesuai aturan ketat bursa (MEXC). Jika tidak, order akan ditolak."""
    if step_size == 0: return float(value)
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    return round(float(value) - (float(value) % float(step_size)), precision)

def get_symbol_info(symbol: str):
    """Mengambil aturan desimal harga dan kuantitas untuk koin tertentu dari bursa."""
    try:
        res = requests.get(f"{BASE_URL}/api/v3/exchangeInfo", params={'symbol': symbol}, timeout=5).json()
        for s in res['symbols']:
            if s['symbol'] == symbol:
                info = {'price_step': 0.01, 'qty_step': 0.000001} 
                for f in s['filters']:
                    if f['filterType'] == 'PRICE_FILTER': info['price_step'] = float(f['tickSize'])
                    if f['filterType'] == 'LOT_SIZE': info['qty_step'] = float(f['stepSize'])
                return info
    except: pass
    return {'price_step': 0.01, 'qty_step': 0.000001}

def get_server_time() -> int:
    try: return requests.get(f"{BASE_URL}/api/v3/time").json()['serverTime']
    except: return int(time.time() * 1000)

def generate_signature(params: Dict[str, Any]) -> str:
    """Membuat tanda tangan kriptografi (HMAC SHA256) wajib untuk MEXC Private API."""
    query_string = urlencode(params)
    return hmac.new(SECRET_KEY.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def mexc_request(method: str, path: str, params: Dict[str, Any] = None) -> Dict:
    """Fungsi pembungkus untuk memanggil Private API MEXC (Buy, Sell, Balance)."""
    if params is None: params = {}
    params['timestamp'] = get_server_time()
    params['recvWindow'] = 60000
    params['signature'] = generate_signature(params)
    headers = {'X-MEXC-APIKEY': API_KEY}
    url = f"{BASE_URL}{path}"
    try:
        if method == 'GET': return requests.get(url, params=params, headers=headers, timeout=10).json()
        return requests.post(url, params=params, headers=headers, timeout=10).json()
    except Exception as e:
        return {"error": "connection_failed"}

# --- FUNGSI DATA & INDIKATOR ---
def is_hammer(row):
    """Mendeteksi pola candle pembalikan arah (Hammer). Ekor bawah harus 2x panjang badan."""
    open_p, close_p, high_p, low_p = row['open'], row['close'], row['high'], row['low']
    body = abs(close_p - open_p)
    if body == 0: body = 0.000001 
    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)
    return (lower_wick >= (2 * body)) and (upper_wick <= (lower_wick * 0.1))

def fetch_data(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Mengambil data riwayat harga dari bursa dan menghitung semua indikator teknikal."""
    # Validasi interval agar tidak kena Error -1121 Invalid Interval MEXC
    valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1M"]
    if interval not in valid_intervals:
        logging.error(f"❌ Error: Interval '{interval}' tidak valid untuk MEXC!")
        return None

    try:
        url = f"{BASE_URL}/api/v3/klines"
        res = requests.get(url, params={'symbol': symbol, 'interval': interval, 'limit': 250}, timeout=10).json()
        
        if not isinstance(res, list): return None

        df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Hitung Indikator via pandas_ta
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema_200'] = ta.ema(df['close'], length=200)
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['vol_sma'] = ta.sma(df['volume'], length=20)
        
        # Hitung VWAP secara manual
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        
        return df
    except: return None

def get_balance():
    """Mengecek saldo real USDT dan token target dari akun MEXC."""
    res = mexc_request('GET', '/api/v3/account')
    asset_name = SYMBOL.replace('USDT', '')
    bal = {'USDT': 0.0, asset_name: 0.0} 
    if 'balances' in res:
        for b in res['balances']:
            if b['asset'] in ['USDT', asset_name]: bal[b['asset']] = float(b['free'])
    return bal

# --- SISTEM TRADING EKSUSI ---
def log_paper_trade(side: str, price: float, pnl: float = 0.0):
    """Mencatat histori transaksi simulasi ke dalam file teks."""
    with open("paper_trading_results.txt", "a", encoding="utf-8") as f:
        msg = f"[{datetime.now()}] {side} {SYMBOL} @ {price}"
        if side == "SELL": msg += f" | PNL Trade: {pnl*100:.2f}%"
        f.write(msg + "\n")

def execute_trade(side: str, amount: float, order_type: str = "MARKET", forced_price: float = None):
    """Fungsi inti untuk melakukan Beli atau Jual, menangani mode Simulasi & Live."""
    global entry_price, total_accumulated_profit, paper_usdt_balance, paper_coin_holdings, active_trade, trade_count
    
    info = get_symbol_info(SYMBOL)
    ticker_res = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
    
    # Penentuan Harga (Menggunakan parameter forced_price jika dipaksa via /panic atau /exit)
    if forced_price: price = float(forced_price)
    else: price = float(ticker_res['askPrice']) if side.upper() == 'BUY' else float(ticker_res['bidPrice'])

    # --- MODE SIMULASI (DRY RUN) ---
    if DRY_RUN:
        if side.upper() == 'BUY':
            if paper_usdt_balance >= amount:
                # Catat harga entry menggunakan format Float murni agar pembagian PNL tepat
                entry_price = price  
                paper_coin_holdings = amount / entry_price
                paper_usdt_balance -= amount
                active_trade = True 
                save_sim_balance(paper_usdt_balance)
                save_state()
                log_paper_trade("BUY", entry_price)
                
                type_tag = order_type.upper()
                send_telegram(f"🚀 *SIMULASI {type_tag} BUY*\nPrice: `{entry_price}`\nAmount: `${amount}`")
            else:
                logging.warning("⚠️ Saldo Simulasi tidak cukup!")
                return None
        else: # LOGIKA SIMULASI JUAL
            if entry_price > 0:
                # Perhitungan Keuntungan Kotor vs Bersih
                gross_pnl = (price - entry_price) / entry_price 
                net_pnl = gross_pnl - EXCHANGE_FEE # Potong biaya bursa
                
                total_accumulated_profit += net_pnl
                trade_count += 1
                paper_usdt_balance += (paper_coin_holdings * price)
                paper_coin_holdings = 0.0
                active_trade = False 
                save_sim_balance(paper_usdt_balance)
                save_state()
                
                log_paper_trade("SELL", price, net_pnl)
                logging.info(f"✅ [SIMULASI] SELL EXECUTED | Price: {price} | Net PNL: {net_pnl*100:.2f}% (Gross: {gross_pnl*100:.2f}%)")
                
                emoji = "💰" if net_pnl > 0 else "📉"
                send_telegram(f"{emoji} *SIMULASI SELL*\nExit: `{price}`\nNet PNL: *{net_pnl*100:.2f}%*")
        
        return {'price': str(price), 'status': 'FILLED', 'orderId': 'SIMULASI'}

    # --- MODE LIVE (REAL MONEY) ---
    # WAJIB dibulatkan menjadi string sesuai step bursa agar API tidak menolak
    price_str = "{:f}".format(round_step(price, info['price_step']))
    params = {'symbol': SYMBOL, 'side': side.upper(), 'type': order_type}
    
    # Format Khusus Limit Order
    if order_type == "LIMIT":
        params['price'] = price_str
        params['quantity'] = "{:f}".format(round_step(amount / float(price_str), info['qty_step']))
        params['timeInForce'] = "GTC" 

    if side.upper() == 'BUY':
        if order_type == "MARKET":
            params['quoteOrderQty'] = round_step(amount, info['price_step'])
        
        # Eksekusi Tembak ke API
        res = mexc_request('POST', '/api/v3/order', params)
        if not res or 'orderId' not in res:
            logging.error(f"❌ LIVE BUY FAILED: {res}")
            return None
        
        active_trade = True 
        entry_price = float(price_str)
        save_state()
        send_telegram(f"✅ *LIVE {order_type} BUY*\nPrice: `{entry_price}`")
        
        # Pasang Sabuk Pengaman Otomatis ke Bursa (Hard Stop Loss Limit)
        try:
            exec_qty = float(res.get('origQty', amount / entry_price))
            hard_sl_price = round_step(entry_price * 0.985, info['price_step']) # Jaring awal 1.5% di bawah
            sl_params = {
                'symbol': SYMBOL, 'side': 'SELL', 'type': 'STOP_LOSS_LIMIT',
                'quantity': "{:f}".format(round_step(exec_qty * 0.99, info['qty_step'])),
                'price': "{:f}".format(hard_sl_price), 'stopPrice': "{:f}".format(hard_sl_price)
            }
            mexc_request('POST', '/api/v3/order', sl_params)
        except: pass
        return res

    else: # LOGIKA JUAL LIVE
        # Hapus Stop Loss lama yang menggantung di bursa agar tidak bentrok
        try: mexc_request('DELETE', '/api/v3/openOrders', {'symbol': SYMBOL}) 
        except: pass
        
        asset_name = SYMBOL.replace('USDT', '')
        bal = get_balance()
        qty = bal.get(asset_name, 0.0)
        
        if qty <= 0: return None # Cegah jual jika saldo 0
        
        params['quantity'] = "{:f}".format(round_step(qty * 0.99, info['qty_step']))
        res_sell = mexc_request('POST', '/api/v3/order', params)
        
        if res_sell and 'orderId' in res_sell:
            exit_price = float(res_sell.get('price', price))
            
            # Hitung net profit
            gross_pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            net_pnl = gross_pnl - EXCHANGE_FEE
            
            total_accumulated_profit += net_pnl
            trade_count += 1
            active_trade = False
            entry_price = 0.0
            save_state()
            
            logging.info(f"✅ [REAL] SELL EXECUTED | Price: {exit_price} | Net PNL: {net_pnl*100:.2f}%")
            emoji = "💰" if net_pnl > 0 else "📉"
            send_telegram(f"{emoji} *REAL SELL EXECUTED*\nNet PNL: *{net_pnl*100:.2f}%*")
        return res_sell

# --- TELEGRAM & MONITOR ---
def send_telegram(message: str):
    """Kirim pesan ke Telegram. Dilengkapi timeout agar bot tidak gantung jika internet putus."""
    if not TELE_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      data={"chat_id": TELE_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5) 
    except: pass

def handle_status_command(status):
    """Menangani perhitungan Floating PNL dan Equity yang dikirim saat perintah /status."""
    global entry_price, paper_usdt_balance, paper_coin_holdings, total_accumulated_profit, trade_count
    try:
        ticker = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
        current_price = float(ticker['bidPrice'])
        asset_name = SYMBOL.replace('USDT', '')
        
        if not DRY_RUN:
            bal = get_balance()
            usdt_display, coin_display = bal.get('USDT', 0.0), bal.get(asset_name, 0.0)
        else:
            usdt_display, coin_display = paper_usdt_balance, paper_coin_holdings

        floating_pnl_str = ""
        current_value = coin_display * current_price
        total_equity = usdt_display + current_value
        
        if active_trade and entry_price > 0:
            f_pnl_gross = (current_price - entry_price) / entry_price
            f_pnl_net = f_pnl_gross - EXCHANGE_FEE
            floating_pnl_str = f"\n🔄 *PNL Berjalan (Net):* `{f_pnl_net*100:.2f}%`"

        pnl_info = f"\n💰 *Total Profit:* `{total_accumulated_profit*100:.2f}%` ({trade_count} trades)"
  
        msg = (f"🤖 *BOT STATUS:* {status}\n"
               f"━━━━━━━━━━━━━━━\n"
               f"📈 Mode: `{'SIMULASI' if DRY_RUN else 'LIVE'}`\n"
               f"⚙️ Strategy: `{STRATEGY_MODE}`\n"
               f"🪙 Token: `{SYMBOL}`\n"
               f"💵 Harga: `${current_price:.4f}`"
               f"{floating_pnl_str}{pnl_info}\n\n"
               f"🏦 *INFO SALDO:*\n"
               f"💵 USDT: `{usdt_display:.2f}`\n"
               f"🪙 {asset_name}: `{coin_display:.6f}`\n"
               f"💰 *Total Equity:* `{total_equity:.2f}`")
        send_telegram(msg)
    except: pass

def handle_telegram_command(msg_text):
    """Fungsi pemroses semua ketikan yang masuk ke Bot Telegram."""
    global bot_active, force_buy, active_trade, stop_loss, highest_p, SYMBOL
    global paper_usdt_balance, paper_coin_holdings, total_accumulated_profit, trade_count, entry_price
    global STRATEGY_MODE

    # Pengubah Strategi
    if msg_text == "/mode_trend":
        STRATEGY_MODE = "TREND"; trigger_scan.set(); send_telegram("🚀 Mode diubah ke: *TREND*")
    elif msg_text == "/mode_scalp":
        STRATEGY_MODE = "SCALP"; trigger_scan.set(); send_telegram("⚡ Mode diubah ke: *SCALP*")
    
    elif msg_text == "/status":
        handle_status_command("🟢 ON" if bot_active else "🔴 OFF"); send_chart()
    
    # Pengubah Target Koin (Dilarang ganti kalau posisi nyangkut)
    elif msg_text.startswith("/symbol"):
        if active_trade:
            send_telegram(f"❌ *DITOLAK:* Bot menahan posisi di `{SYMBOL}`. Jual dulu."); return
        parts = msg_text.split()
        if len(parts) > 1:
            new_symbol = parts[1].upper().strip() 
            try:
                cek_koin = requests.get(f"{BASE_URL}/api/v3/ticker/price", params={'symbol': new_symbol}).json()
                if 'price' in cek_koin: 
                    SYMBOL = new_symbol 
                    send_telegram(f"✅ Target diubah ke `{SYMBOL}` (${cek_koin['price']})")
                    trigger_scan.set()
                else: send_telegram(f"❌ Koin `{new_symbol}` *TIDAK DITEMUKAN*")
            except: send_telegram("⚠️ Gagal verifikasi koin.")
    
    # Test Buy Manual
    elif msg_text == "/testbuy":
        keyboard = {"inline_keyboard": [[{"text": "✅ Beli", "callback_data": "confirm_buy"}, {"text": "❌ Batal", "callback_data": "cancel_buy"}]]}
        requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendMessage", 
                      json={"chat_id": TELE_CHAT_ID, "text": f"⚠️ *TEST BUY* `{SYMBOL}`?", "reply_markup": keyboard, "parse_mode": "Markdown"})
    
    # --- SISTEM FORCED EXIT ---
    # Jual paksa dengan harga REALTIME agar PNL akurat
    elif msg_text in ["/stop", "/panic", "/exit"]:
        if msg_text == "/panic": send_telegram("🚨 *PANIC BUTTON TRIGGERED!* 🚨")
        
        if active_trade:
            try: curr_p = float(requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()['bidPrice'])
            except: curr_p = None
            
            send_telegram(f"⚠️ Menutup posisi di harga `{curr_p if curr_p else 'Market'}`...")
            execute_trade('SELL', USDT_AMOUNT, forced_price=curr_p)
            
            active_trade, entry_price, stop_loss, highest_p = False, 0.0, 0.0, 0.0
            save_state()
            send_telegram("✅ *Posisi ditutup.*")
        else:
            send_telegram("ℹ️ Tidak ada posisi aktif.")
        
        if msg_text in ["/stop", "/panic"]: 
            bot_active = False; save_state(); send_telegram("🛑 *BOT STOPPED*")

    elif msg_text == "/start":
        bot_active = True; trigger_scan.set(); send_telegram("✅ *BOT STARTED* 🟢")
    
    elif msg_text == "/reset_sim":
        paper_usdt_balance, paper_coin_holdings, total_accumulated_profit, trade_count = 1000.0, 0.0, 0.0, 0
        active_trade, entry_price = False, 0.0
        save_sim_balance(1000.0); save_state()
        send_telegram("♻️ *Simulasi di-reset ke $1000!*")
        
    elif msg_text == "/help":
        send_telegram("📜 *Daftar Perintah:*\n`/start` `/stop` `/exit` `/panic` `/symbol [KOIN]` `/status` `/testbuy` `/mode_trend` `/mode_scalp` `/reset_sim`")

def check_commands():
    """Fungsi Long-Polling API Telegram. Mengecek pesan baru setiap detik."""
    global last_update_id, force_buy
    try:
        url = f"https://api.telegram.org/bot{TELE_TOKEN}/getUpdates"
        res = requests.get(url, params={"offset": last_update_id+1, "timeout": 5}, timeout=10).json()
        updates = res.get("result", [])
        if updates:
            last_update_id = updates[-1]["update_id"]
            for u in updates:
                # Cek Pesan Teks
                if "message" in u and str(u["message"].get("from", {}).get("id")) == str(TELE_CHAT_ID):
                    handle_telegram_command(u["message"].get("text"))
                
                # Cek Klik Tombol Inline
                elif "callback_query" in u and str(u["callback_query"].get("from", {}).get("id")) == str(TELE_CHAT_ID):
                    cb = u["callback_query"]
                    if cb.get("data") == "confirm_buy" and not active_trade:
                        force_buy = True; trigger_scan.set(); send_telegram("🚀 *Menjalankan order instan...*")
                    requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/answerCallbackQuery", data={"callback_query_id": cb.get("id")})
    except: pass

def monitor_position():
    """Fungsi menjaga profit dan mengawal kerugian. Berjalan cepat saat posisi sedang aktif."""
    global active_trade, stop_loss, highest_p, entry_price, STRATEGY_MODE
    conf = STRATEGIES[STRATEGY_MODE]
    tp_price = entry_price * (1 + conf['tp_percent'])
    
    # Inisialisasi awal Stop Loss jika belum ada (misal kena auto-recovery)
    if stop_loss == 0:
        stop_loss = entry_price * 0.99 
        highest_p = entry_price

    try:
        ticker = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}, timeout=5).json()
        curr_p = float(ticker['bidPrice'])
        
        # Puncak harga terbaru untuk patokan trailing
        if curr_p > highest_p: highest_p = curr_p
        
        # PNL Kotor untuk patokan pemicu Trailing Stop (berdasarkan grafik harga)
        pnl_gross = (curr_p - entry_price) / entry_price
        
        # PNL Bersih untuk ditampilkan ke layar (realita dompet)
        pnl_net = pnl_gross - EXCHANGE_FEE

        logging.info(f"[{STRATEGY_MODE}] {SYMBOL} | Price: {curr_p} | Net PNL: {pnl_net*100:.2f}% | SL: {stop_loss:.4f} | TP: {tp_price:.4f}")


        # 1. HARD TP (Take Profit Paksa)
        if conf['use_hard_tp'] and curr_p >= tp_price:
            logging.info(f"🎯 HARD TP HIT! Menjual...")
            execute_trade('SELL', USDT_AMOUNT)
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            save_state()
            return

        # 2. LOGIKA TRAILING STOP (Mengangkat jaring pelindung jika harga naik tinggi)
        if pnl_gross >= conf['trail_start']: 
            new_sl = highest_p * (1 - conf['trail_dist']) 
            if new_sl > stop_loss:
                stop_loss = min(new_sl, curr_p * 0.9995) # Pastikan jarak aman 0.05%
                logging.info(f"📈 Trailing Up! New SL: {stop_loss:.4f}")
                save_state() 

        # 3. EXIT / STOP LOSS HIT
        if curr_p <= stop_loss:
            execute_trade('SELL', USDT_AMOUNT)
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            save_state()

    except Exception as e:
        logging.error(f"Monitor Error: {e}")

# --- THREAD LOOPS ---
def telegram_loop():
    """Menjalankan bot Telegram terpisah agar tidak mengganggu kecepatan scan harga trading."""
    logging.info("Jalur Telegram Siap.")
    while bot_active:
        check_commands()
        time.sleep(1)

def trading_loop():
    """Jantung utama Algoritma Trading."""
    global bot_active, force_buy, active_trade, stop_loss, highest_p, STRATEGY_MODE
    logging.info(f"Jalur Trading Siap. Mode: {'DRY RUN' if DRY_RUN else 'REAL MONEY'} | Strategy: {STRATEGY_MODE}")
    
    while True:
        conf = STRATEGIES[STRATEGY_MODE] 
        try:
            # 1. STANDBY MODE (Mati via /stop)
            if not bot_active:
                trigger_scan.wait(timeout=5)
                trigger_scan.clear()
                continue

            # 2. SEDANG MEMEGANG KOIN -> Alihkan ke Monitor
            if active_trade:
                monitor_position() 
                time.sleep(2) 
            
            # 3. SEDANG MENCARI KOIN / SCANNING
            else:
                df = fetch_data(SYMBOL, conf['interval'])
                trigger_buy = False
                
                # OPSI A: Beli Manual via /testbuy
                if force_buy:
                    trigger_buy = True
                    force_buy = False
                    if df is not None and not df.empty:
                        last_atr = df.iloc[-2]['atr']
                        curr_price = df.iloc[-2]['close']
                        stop_loss = curr_price - (last_atr * 1.5) if not pd.isna(last_atr) else curr_price * 0.99
                        highest_p = curr_price
                
                # OPSI B: Analisis Harga Otomatis
                elif df is not None and not df.empty:
                    last = df.iloc[-2] # Data Candle yang baru saja tutup
                    prev = df.iloc[-3] # Data Candle sebelumnya
                    
                    ticker_realtime = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()
                    curr_price = float(ticker_realtime['askPrice'])
                    
                    # --- INDIKATOR & KONFIRMASI ---
                    curr_rsi = last['rsi']
                    rsi_moving_up = curr_rsi > prev['rsi'] # Konfirmasi Pantulan (Hook)
                    found_hammer = is_hammer(last)         # Deteksi Pola Pembalikan Ekor Panjang
                    volume_breakout = last['volume'] > (last['vol_sma'] * conf["vol_mult"])
                    
                    logging.info(f"🔍 [{STRATEGY_MODE}] Scan {SYMBOL} | Price: {curr_price} | RSI: {curr_rsi:.2f} | Up: {rsi_moving_up} | Hammer: {found_hammer}")
                    
                    # --- FILTER STRATEGI (Tren & Level Murah) ---
                    is_uptrend = curr_price > last['ema_200'] if conf["use_ema_200"] else True
                    rsi_healthy = (conf["rsi_min"] < curr_rsi < conf["rsi_max"])

                    # --- LOGIKA TRIGGER (Aggressive vs Standard) ---
                    # Syarat Wajib: Harus searah tren besar (Uptrend), RSI area bawah, dan sedang memantul naik.
                    if is_uptrend and rsi_healthy and rsi_moving_up:
                        
                        # Trigger Jalur Cepat: Jika bentuk candlenya Hammer, langsung beli
                        if found_hammer:
                            trigger_buy = True
                            logging.info(f"🚀 AGGRESSIVE ENTRY: Hammer Detected!")
                            
                        # Trigger Standar: Jika candle ditutup hijau dan volume besar
                        elif curr_price > last['open'] and volume_breakout:
                            trigger_buy = True
                            logging.info(f"🚀 STANDARD ENTRY: Bullish Momentum!")

                        # Kalkulasi awal batas kerugian saat sinyal terkonfirmasi
                        if trigger_buy:
                            stop_loss = curr_price - (last['atr'] * conf["sl_atr_mult"]) 
                            highest_p = curr_price
                            logging.info(f"✅ {STRATEGY_MODE} SIGNAL VALID! SL: {stop_loss:.4f}")

                # 4. EKSEKUSI JIKA SINYAL VALID
                if trigger_buy and not active_trade:
                    # Pastikan selisih harga aman dari slippage
                    is_safe, current_spread = check_spread(SYMBOL, 2.0) 
                    
                    if is_safe:
                        info = get_symbol_info(SYMBOL)
                        ticker_res = requests.get(f"{BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': SYMBOL}).json()
                        bid_price = float(ticker_res['bidPrice'])
                        ask_price = float(ticker_res['askPrice'])
                        
                        # Teknik "Front-Running": Jika spread rapat eksekusi instan, jika renggang antre di depan (LIMIT)
                        if current_spread <= 0.05:
                            execute_trade('BUY', USDT_AMOUNT, order_type="MARKET")
                        else:
                            tick_size = info['price_step'] 
                            limit_price = bid_price + tick_size 
                            if limit_price >= ask_price: limit_price = bid_price 

                            logging.info(f"🟡 Mengantre di depan (Bid+1): {limit_price}")
                            execute_trade('BUY', USDT_AMOUNT, order_type="LIMIT", forced_price=limit_price)
                
                # 5. JEDA ISTIRAHAT (Delay Scan Adaptif)
                if not active_trade:
                    logging.info(f"💤 Jeda {conf['delay_scan']}s.")
                    trigger_scan.wait(timeout=conf['delay_scan'])
                    trigger_scan.clear() # Reset agar siklus tidak berantakan

        except Exception as e:
            logging.error(f"⚠️ Error di Trading Loop: {e}")
            time.sleep(10) # Jeda panjang jika API Error/Koneksi Putus

# --- FUNGSI MENGGAMBAR CHART KOTAK-KOTAK (Matplotlib) ---
def send_chart():
    try:
        conf = STRATEGIES[STRATEGY_MODE] 
        df = fetch_data(SYMBOL, conf['interval'])
        if df is None or df.empty: return
        
        df_plot = df.tail(30).copy()
        plt.clf() 
        plt.figure(figsize=(10, 6))
        
        # Gambar Harga & Garis VWAP
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
        
        # Upload ke Telegram
        with open(chart_path, 'rb') as photo:
            requests.post(f"https://api.telegram.org/bot{TELE_TOKEN}/sendPhoto", 
                          params={'chat_id': TELE_CHAT_ID}, files={'photo': photo}, timeout=10)
        
        if os.path.exists(chart_path): os.remove(chart_path)
            
    except Exception as e:
        logging.error(f"Gagal kirim chart: {e}")

# --- MAIN EXECUTION (Garis Start) ---
if __name__ == "__main__":
    print("--- BOT MEXC REST API V3 ---")
    status_msg = "🤖 *Bot Started!*\nMode: ⚡ *FORCE BUY*" if force_buy else "🤖 *Bot Started!*\nMode: 🔍 *AUTO SCAN*"
    send_telegram(status_msg)
    print("Tekan Ctrl + C untuk berhenti total.")
    
    # 1. Validasi Keamanan API Key
    if not API_KEY:
        logging.error("❌ ERROR: API KEY tidak ditemukan!")
        sys.exit()
    
    # 2. Menjalankan Mesin Telegram & Trading secara Paralel (Multitasking)
    t1 = threading.Thread(target=telegram_loop)
    t2 = threading.Thread(target=trading_loop)
    
    t1.daemon = True # Agar thread ikut mati jika terminal ditutup
    t2.daemon = True
    
    t1.start()
    t2.start()
    
    # 3. Penjaga Kelangsungan Hidup & Auto-Sell Shutdown (Graceful Exit)
    try:
        while True:
            time.sleep(5)
            # Jika Telegram mati mendadak (Connection Timeout), bangkitkan lagi
            if not t1.is_alive():
                logging.warning("⚠️ Jalur Telegram terputus/mati! Membangkitkan ulang...")
                t1 = threading.Thread(target=telegram_loop)
                t1.daemon = True
                t1.start()
                
    except KeyboardInterrupt:
        # Jika ditekan Ctrl + C di terminal
        bot_active = False 
        print("\n🛑 Signal Shutdown Diterima (Ctrl+C)...")
        time.sleep(1) 

        # Auto-Sell Penyelamat
        if active_trade:
            print("⚠️ Ada posisi aktif! Mencoba melakukan SELL otomatis...")
            send_telegram("⚠️ *Shutdown Alert*: Menutup posisi sebelum offline...")
            try:
                execute_trade('SELL', USDT_AMOUNT)
                print("✅ Posisi berhasil ditutup.")
            except Exception as e:
                print(f"❌ Gagal menutup posisi: {e}")
        else:
            print("✅ Tidak ada posisi aktif. Aman untuk dimatikan.")

        try: send_telegram("🛑 *Bot Shutdown Selesai*\nStatus: Offline")
        except: pass
            
        print("Bot Berhenti Total. Sampai jumpa!")
        sys.exit(0)