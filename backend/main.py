import os
import time
import hmac
import hashlib
import requests
import pandas as pd
import pandas_ta as ta
import logging
import sys
import json
import threading
import matplotlib
# Mode backend untuk render gambar di latar belakang tanpa membuka jendela UI baru di server
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from datetime import datetime
from typing import Optional, Dict, Any
from urllib.parse import urlencode

# --- IMPORT MODUL BUATAN SENDIRI ---
# Memanggil konfigurasi dan fungsi database yang sudah dipisah ke file lain
import config
import database
import telegram_bot

# --- SETUP LOGGING ---
# Mengatur agar catatan bot tampil di terminal sekaligus tersimpan permanen di file txt
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_log.txt", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- STATE KONTROL GLOBAL ---
bot_active = True  
force_buy = False  
paper_usdt_balance = database.load_sim_balance()
paper_coin_holdings = 0.0

# Muat memori terakhir dari file JSON via modul database
state_data = database.load_state()
active_trade = state_data["active_trade"]
entry_price = state_data["entry_price"]
stop_loss = state_data.get("stop_loss", 0.0)
highest_p = state_data.get("highest_p", 0.0)
trade_count = state_data["trade_count"]
total_accumulated_profit = state_data["total_accumulated_profit"]

last_update_id = 0
trigger_scan = threading.Event()
STRATEGY_MODE = "TREND"

last_known_status = True

# Deteksi jika bot baru direstart tapi masih punya posisi nyangkut
if active_trade:
    logging.info(f"🔄 Auto-Recovery aktif! Melanjutkan trade yang menggantung. Harga Entry: {entry_price}")

# Bypass proxy lokal jika ada, agar koneksi ke API MEXC tidak terhalang
os.environ['no_proxy'] = '*'

# --- FUNGSI PEMBUNGKUS MEMORI ---
def update_and_save_state():
    """
    Membungkus semua variabel status global dari main.py ke dalam sebuah dictionary, 
    lalu mengirimnya ke database.py untuk disimpan ke file JSON.
    """
    state = {
        "is_active": bot_active,
        "active_trade": active_trade,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "highest_p": highest_p,
        "trade_count": trade_count,
        "total_accumulated_profit": total_accumulated_profit
    }
    database.save_state(state)

def sync_dashboard_data():
    """Mengambil setting terbaru dari JSON dan menimpanya ke memori bot."""
    global bot_active, last_known_status, active_trade, entry_price, stop_loss, highest_p
    
    try:
        with open(config.STATE_FILE, "r") as f:
            state_data = json.load(f)
            
        # 1. CEK PANIC SELL DARI WEB
        if state_data.get("trigger_panic", False):
            logging.info("🚨 Sinyal PANIC SELL dari Web Dashboard diterima di main.py!")
            telegram_bot.send_message("🚨 *PANIC BUTTON WEB TRIGGERED!* 🚨\nMenutup posisi secara paksa...")
            
            try: 
                curr_p = float(requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()['bidPrice'])
            except: 
                curr_p = None
                
            # Eksekusi Jual Darurat (Fungsi ini otomatis menghitung profit & menyimpan state!)
            execute_trade('SELL', config.USDT_AMOUNT, forced_price=curr_p)
            
            # Reset variabel pelacakan cuaca lokal
            stop_loss = 0.0
            highest_p = 0.0
            
            with open(config.STATE_FILE, "r") as fr:
                fresh_state = json.load(fr)
                
            # Matikan panic di memori yang baru (fresh)
            fresh_state["trigger_panic"] = False
            with open(config.STATE_FILE, "w") as fw:
                json.dump(fresh_state, fw)
                
            logging.info("✅ Posisi berhasil ditutup via Web.")
            
            # Kembalikan state_data ke versi fresh agar sinkronisasi di bawah ini pakai data terbaru
            state_data = fresh_state

        # 2. UPDATE STATUS AKTIF/JEDA
        new_status = state_data.get("is_active", True)
        if new_status != last_known_status:
            if new_status:
                telegram_bot.send_message("✅ *Dashboard Alert*: Bot dijalankan kembali 🟢")
            else:
                telegram_bot.send_message("🛑 *Dashboard Alert*: Bot telah dijeda ⏸️")
            last_known_status = new_status
        bot_active = new_status

        state_data["last_heartbeat"] = time.time()
        with open(config.STATE_FILE, "w") as fw:
            json.dump(state_data, fw)
            
    except Exception:
        pass 

    # 4. UPDATE PARAMETER SETTING
    latest_cfg = config.get_settings()
    config.API_KEY = latest_cfg['env'].get('api_key', '')
    config.SECRET_KEY = latest_cfg['env'].get('secret_key', '')
    config.TELE_TOKEN = latest_cfg['env'].get('tele_token', '')
    config.TELE_CHAT_ID = latest_cfg['env'].get('tele_chat_id', '')
    
    config.SYMBOL = latest_cfg['general']['symbol']
    config.USDT_AMOUNT = latest_cfg['general']['usdt_amount']
    config.DRY_RUN = latest_cfg['general']['dry_run']
    config.USE_COMPOUNDING = latest_cfg['general'].get('use_compounding', False)
    config.RISK_PERCENTAGE = latest_cfg['general'].get('risk_percentage', 5.0)
    config.STRATEGIES = {
        "TREND": latest_cfg['trend'],
        "SCALP": latest_cfg['scalp']
    }

# --- FUNGSI UTILS & PRESISI ---
def format_crypto(value: float) -> str:
    """Mengubah float menjadi string tanpa notasi ilmiah (e) dengan presisi ketat (sampai 10 desimal)."""
    return f"{float(value):.10f}".rstrip('0').rstrip('.')

def check_spread(symbol, max_spread_percent=2.0):
    """Mengecek selisih harga Bid/Ask di bursa. Jika jaraknya > 2%, sinyal beli dibatalkan karena rawan rugi."""
    try:
        url = f"{config.BASE_URL}/api/v3/ticker/bookTicker"
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
        return False, 0.0
    except Exception as e:
        logging.error(f"❌ Gagal mengecek spread: {e}")
        return False, 0.0

def round_step(value: float, step_size: float) -> float:
    """Membulatkan angka order harga/kuantitas agar sesuai dengan aturan desimal ketat dari bursa."""
    if step_size == 0: return float(value)
    precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
    return round(float(value) - (float(value) % float(step_size)), precision)

def get_symbol_info(symbol: str):
    """Mengambil aturan batas desimal dari MEXC untuk koin spesifik (Tick Size & Step Size)."""
    try:
        res = requests.get(f"{config.BASE_URL}/api/v3/exchangeInfo", params={'symbol': symbol}, timeout=5).json()
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
    """Mengambil waktu dari server MEXC untuk mencegah error sinkronisasi waktu."""
    try: return requests.get(f"{config.BASE_URL}/api/v3/time").json()['serverTime']
    except: return int(time.time() * 1000)

def generate_signature(params: Dict[str, Any]) -> str:
    """Membuat tanda tangan kriptografi (HMAC-SHA256) wajib untuk keamanan Private API MEXC."""
    query_string = urlencode(params)
    return hmac.new(config.SECRET_KEY.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def mexc_request(method: str, path: str, params: Dict[str, Any] = None) -> Dict:
    """Fungsi pembungkus master untuk menembak API privat (Buy, Sell, Cek Saldo)."""
    if params is None: params = {}
    params['timestamp'] = get_server_time()
    params['recvWindow'] = 60000
    params['signature'] = generate_signature(params)
    headers = {'X-MEXC-APIKEY': config.API_KEY}
    url = f"{config.BASE_URL}{path}"
    try:
        if method == 'GET': return requests.get(url, params=params, headers=headers, timeout=10).json()
        return requests.post(url, params=params, headers=headers, timeout=10).json()
    except Exception:
        return {"error": "connection_failed"}

# --- FUNGSI DATA & INDIKATOR ---
def is_hammer(row):
    """Mendeteksi pola lilin pembalikan (Hammer). Ekor bawah minimal 2x dari panjang badannya."""
    open_p, close_p, high_p, low_p = row['open'], row['close'], row['high'], row['low']
    body = abs(close_p - open_p)
    if body == 0: body = 0.000001 
    lower_wick = min(open_p, close_p) - low_p
    upper_wick = high_p - max(open_p, close_p)
    return (lower_wick >= (2 * body)) and (upper_wick <= (lower_wick * 0.1))

def fetch_data(symbol: str, interval: str) -> Optional[pd.DataFrame]:
    """Menarik riwayat harga K-Line (Candlestick) dan menghitung semua indikator teknikal."""
    valid_intervals = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1M"]
    if interval not in valid_intervals:
        return None
    try:
        url = f"{config.BASE_URL}/api/v3/klines"
        res = requests.get(url, params={'symbol': symbol, 'interval': interval, 'limit': 250}, timeout=10).json()
        if not isinstance(res, list): return None

        df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        # Indikator dihitung menggunakan pustaka Pandas-TA
        df['rsi'] = ta.rsi(df['close'], length=14)
        df['ema_200'] = ta.ema(df['close'], length=200)
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        # (AUTO-REGIME)
        atr_sma = ta.sma(df['atr'], length=100)
        if atr_sma is not None and not atr_sma.empty:
            df['atr_sma'] = atr_sma
            df['vol_ratio'] = df['atr'] / df['atr_sma']
        else:
            # Fallback jika data kurang dari 100 candle
            df['atr_sma'] = df['atr'] 
            df['vol_ratio'] = 1.0
            
        df['vol_sma'] = ta.sma(df['volume'], length=20)

        # ---INDIKATOR KEKUATAN TREN (ADX) ---
        adx = ta.adx(df['high'], df['low'], df['close'], length=14)
        
        # Pastikan ADX tidak kosong sebelum diambil
        if adx is not None and not adx.empty:
            df['adx'] = adx['ADX_14']
        else:
            df['adx'] = 0.0 # Beri nilai 0 jika koin masih terlalu baru
            
        # Hitung VWAP (Volume Weighted Average Price)
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        
        return df
    except Exception as e: 
        logging.error(f"❌ CRASH DI FETCH_DATA: {str(e)}")
        return None

def get_balance():
    """Mengecek saldo aktual USDT dan Token di dompet MEXC Anda."""
    res = mexc_request('GET', '/api/v3/account')
    asset_name = config.SYMBOL.replace('USDT', '')
    bal = {'USDT': 0.0, asset_name: 0.0} 
    if 'balances' in res:
        for b in res['balances']:
            if b['asset'] in ['USDT', asset_name]: bal[b['asset']] = float(b['free'])
    return bal

# --- CHECK BUY SIGNAL (MTF) ---
def check_buy_signal(df: pd.DataFrame, conf: dict):
    if df is None or df.empty or len(df) < 3: return False, 0.0

    last, prev = df.iloc[-2], df.iloc[-3]
    try:
        ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}, timeout=5).json()
        curr_price = float(ticker['askPrice'])
    except: return False, 0.0
        
    curr_rsi = last.get('rsi')
    prev_rsi = prev.get('rsi')
    curr_adx = last.get('adx')
    
    # Pastikan RSI dan ADX tidak kosong
    if pd.isna(curr_rsi) or pd.isna(prev_rsi) or pd.isna(curr_adx):
        return False, curr_price
        
    rsi_moving_up = curr_rsi > prev_rsi 
    found_hammer = is_hammer(last)         
    
    # Fallback untuk Volume SMA
    vol_sma_val = last.get('vol_sma')
    if pd.isna(vol_sma_val): vol_sma_val = last['volume'] 
    volume_breakout = last['volume'] > (vol_sma_val * conf.get("vol_mult", 1.1))
    
    # Logika Trend vs Reversion (Abaikan ADX jika mode Scalp)
    is_trending_market = True if STRATEGY_MODE == "SCALP" else (curr_adx > 25.0)
    
    # Bypass EMA 200 jika koin terlalu baru
    ema_200_val = last.get('ema_200')
    if conf.get("use_ema_200", True) and not pd.isna(ema_200_val):
        is_micro_uptrend = curr_price > ema_200_val
    else:
        is_micro_uptrend = True # Anggap uptrend jika koin masih baru
        
    rsi_healthy = (conf.get("rsi_min", 30) < curr_rsi < conf.get("rsi_max", 75))

    # LOGIKA MULTI-TIMEFRAME (MTF) FILTER
    is_macro_uptrend = True 
    if conf.get('use_mtf', True):
        macro_tf = conf.get('macro_interval', '4h')
        df_macro = fetch_data(config.SYMBOL, macro_tf)
        if df_macro is not None and not df_macro.empty and len(df_macro) > 2:
            macro_ema = df_macro.iloc[-2].get('ema_200')
            
            # Bypass Macro EMA 200 jika koin terlalu baru
            if not pd.isna(macro_ema):
                if curr_price < macro_ema:
                    is_macro_uptrend = False
                    logging.info(f"🚫 Sinyal Mikro valid, TAPI dibatalkan! Tren Makro ({macro_tf}) sedang Bearish.")

    logging.info(f"🔍 [{STRATEGY_MODE}] Scan {config.SYMBOL} | Price: {curr_price} | RSI: {curr_rsi:.2f} | RSI_UP: {rsi_moving_up} | Hammer: {found_hammer}")

    if is_micro_uptrend and is_macro_uptrend and rsi_healthy and rsi_moving_up and is_trending_market:
        if found_hammer: return True, curr_price
        elif curr_price > last['open'] and volume_breakout: return True, curr_price
            
    return False, curr_price

# --- SISTEM TRADING EKSEKUSI ---
def execute_trade(side: str, amount: float, order_type: str = "MARKET", forced_price: float = None):
    """
    Mesin eksekutor utama. Menangani logika Jual dan Beli,
    serta memisahkan jalur eksekusi antara Mode Simulasi dan Uang Asli.
    """
    global entry_price, total_accumulated_profit, paper_usdt_balance, paper_coin_holdings, active_trade, trade_count
    
    info = get_symbol_info(config.SYMBOL)
    ticker_res = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}, timeout=5).json()
    
    # Prioritaskan harga paksaan jika ada (misal dari /panic), jika tidak ambil dari orderbook
    if forced_price: price = float(forced_price)
    else: price = float(ticker_res['askPrice']) if side.upper() == 'BUY' else float(ticker_res['bidPrice'])

    # ===============================
    # JALUR 1: MODE SIMULASI (DRY RUN)
    # ===============================
    if config.DRY_RUN:
        if side.upper() == 'BUY':
            if paper_usdt_balance >= amount:
                # Catat entry_price presisi tinggi
                entry_price = price  
                paper_coin_holdings = amount / entry_price
                paper_usdt_balance -= amount
                active_trade = True 
                
                database.save_sim_balance(paper_usdt_balance)
                update_and_save_state()
                database.log_trade_to_db(STRATEGY_MODE, "SIMULASI", "BUY", config.SYMBOL, entry_price)
                
                type_tag = order_type.upper()
                logging.info(f"✅ [SIMULASI] {type_tag} BUY EXECUTED | Price: {entry_price} | Amount: ${amount}")
                telegram_bot.send_message(f"🚀 *SIMULASI {type_tag} BUY*\nPrice: `{entry_price}`\nAmount: `${amount}`")
            else:
                logging.warning("⚠️ Saldo Simulasi tidak cukup!")
                return None
                
        else: # SIMULASI JUAL
            if entry_price > 0:
                # Hitung Profit Kotor dan Netto (Potongan Fee Simulasi)
                gross_pnl = (price - entry_price) / entry_price 
                net_pnl = gross_pnl - config.EXCHANGE_FEE
                
                total_accumulated_profit += net_pnl
                trade_count += 1
                paper_usdt_balance += (paper_coin_holdings * price)
                paper_coin_holdings = 0.0
                active_trade = False 
                
                database.save_sim_balance(paper_usdt_balance)
                update_and_save_state()
                database.log_trade_to_db(STRATEGY_MODE, "SIMULASI", "SELL", config.SYMBOL, price, gross_pnl, net_pnl)
                
                logging.info(f"✅ [SIMULASI] SELL EXECUTED | Price: {price} | Net PNL: {net_pnl*100:.2f}% (Gross: {gross_pnl*100:.2f}%)")
                emoji = "💰" if net_pnl > 0 else "📉"
                telegram_bot.send_message(f"{emoji} *SIMULASI SELL*\nExit: `{price}`\nNet PNL: *{net_pnl*100:.2f}%*")
        
        return {'price': str(price), 'status': 'FILLED', 'orderId': 'SIMULASI'}

    # ===============================
    # JALUR 2: MODE LIVE (REAL MONEY)
    # ===============================
    # Format pembulatan string WAJIB digunakan agar MEXC tidak menolak order (Error -1111)
    price_str = format_crypto(round_step(price, info['price_step']))
    params = {'symbol': config.SYMBOL, 'side': side.upper(), 'type': order_type}
    
    if order_type == "LIMIT":
        params['price'] = price_str
        params['quantity'] = format_crypto(round_step(amount / float(price_str), info['qty_step']))
        params['timeInForce'] = "GTC" 

    if side.upper() == 'BUY':
        if order_type == "MARKET":
            params['quoteOrderQty'] = format_crypto(round_step(amount, info['price_step']))
        
        res = mexc_request('POST', '/api/v3/order', params)
        if not res or 'orderId' not in res:
            logging.error(f"❌ LIVE BUY FAILED: {res}")
            return None
        
        active_trade = True 
        entry_price = float(price_str)
        update_and_save_state()
        database.log_trade_to_db(STRATEGY_MODE, "LIVE", "BUY", config.SYMBOL, entry_price)
        
        logging.info(f"✅ [LIVE] {order_type} BUY EXECUTED | Price: {entry_price} | Amount: ${amount}")
        telegram_bot.send_message(f"✅ *LIVE {order_type} BUY*\nPrice: `{entry_price}`")
        
        # Lempar Order Stop-Loss Limit ke Bursa sebagai "Sabuk Pengaman" ekstra
        try:
            exec_qty = float(res.get('origQty', amount / entry_price))
            hard_sl_price = round_step(entry_price * 0.985, info['price_step']) 
            sl_params = {
                'symbol': config.SYMBOL, 'side': 'SELL', 'type': 'STOP_LOSS_LIMIT',
                'quantity': format_crypto(round_step(exec_qty * 0.99, info['qty_step'])),
                'price': format_crypto(hard_sl_price), 'stopPrice': format_crypto(hard_sl_price)
            }
            mexc_request('POST', '/api/v3/order', sl_params)
        except: pass
        return res

    else: # LIVE SELL
        # Hapus antrean Stop-Loss lama di bursa agar saldo bisa dijual
        try: mexc_request('DELETE', '/api/v3/openOrders', {'symbol': config.SYMBOL}) 
        except: pass
        
        asset_name = config.SYMBOL.replace('USDT', '')
        bal = get_balance()
        qty = bal.get(asset_name, 0.0)
        
        if qty <= 0: return None 
        
        params['quantity'] = format_crypto(round_step(qty * 0.99, info['qty_step']))
        res_sell = mexc_request('POST', '/api/v3/order', params)
        
        if res_sell and 'orderId' in res_sell:
            exit_price = float(res_sell.get('price', price))
            gross_pnl = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            net_pnl = gross_pnl - config.EXCHANGE_FEE
            
            total_accumulated_profit += net_pnl
            trade_count += 1
            active_trade = False
            entry_price = 0.0
            update_and_save_state()

            database.log_trade_to_db(STRATEGY_MODE, "LIVE", "SELL", config.SYMBOL, exit_price, gross_pnl, net_pnl)
            
            logging.info(f"✅ [REAL] SELL EXECUTED | Price: {exit_price} | Net PNL: {net_pnl*100:.2f}%")
            emoji = "💰" if net_pnl > 0 else "📉"
            telegram_bot.send_message(f"{emoji} *REAL SELL EXECUTED*\nNet PNL: *{net_pnl*100:.2f}%*")
            return res_sell
        else:
            logging.error(f"❌ LIVE SELL DITOLAK BURSA: {res_sell}")
            # Jika MEXC menolak karena nilainya sudah di bawah $5 (-1013) atau saldo tidak cukup (-2010)
            if isinstance(res_sell, dict) and res_sell.get('code') in [-1013, -2010]:
                logging.warning("⚠️ Merelakan koin nyangkut (Dust) agar mesin bot tidak macet.")
                active_trade = False
                entry_price = 0.0
                update_and_save_state()
                telegram_bot.send_message("⚠️ *SELL Gagal: Min. $5.*\nKoin receh ditinggalkan, bot lanjut mencari target baru.")
            
            return res_sell
    
def monitor_position():
    global active_trade, stop_loss, highest_p, entry_price, STRATEGY_MODE
    conf = config.STRATEGIES[STRATEGY_MODE]
    tp_price = entry_price * (1 + conf['tp_percent'])
    
    if stop_loss == 0:
        stop_loss = entry_price * 0.99 
        highest_p = entry_price
        update_and_save_state()
    try:
        ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}, timeout=5).json()
        curr_p = float(ticker['bidPrice'])
        
        if curr_p > highest_p: highest_p = curr_p
        pnl_gross = (curr_p - entry_price) / entry_price
        pnl_net = pnl_gross - config.EXCHANGE_FEE
        
        sl_pct = ((stop_loss - entry_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100

        logging.info(f"[{STRATEGY_MODE}] {config.SYMBOL} | Price: {curr_p:.2f} | Net PNL: {pnl_net*100:.2f}% | SL: {stop_loss:.4f} ({sl_pct:.2f}%) | TP: {tp_price:.4f} (+{tp_pct:.2f}%)")

        if conf['use_hard_tp'] and curr_p >= tp_price:
            logging.info(f"🎯 HARD TP HIT! Menjual sebagai MAKER (0% Fee)...")
            ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()
            ask_p = float(ticker['askPrice'])
            
            execute_trade('SELL', config.USDT_AMOUNT, order_type="LIMIT", forced_price=ask_p)
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            update_and_save_state()
            return
        
        # RISK-FREE TRADE (BREAK-EVEN)
        # Tambahkan fee bursa (x2 untuk buy & sell) ditambah sedikit buffer 0.05%
        fee_buffer = (config.EXCHANGE_FEE * 2) + 0.0005
        break_even_price = entry_price * (1 + fee_buffer)
        
        # Ambil nilai breakeven_start dari config (misal 0.015). Jika tidak ada, gunakan 1.5% sebagai default.
        trigger_breakeven = conf.get('breakeven_start', 0.015)
        
        # Jika profit kotor sudah melewati batas trigger, tapi SL masih di bawah harga Break-Even
        if pnl_gross >= trigger_breakeven and stop_loss < break_even_price:
            stop_loss = break_even_price
            logging.info(f"🛡️ BREAK-EVEN AKTIF! Posisi sekarang Risk-Free. SL dinaikkan ke: {stop_loss:.4f}")
            update_and_save_state()

        if pnl_gross >= conf['trail_start']: 
            new_sl = highest_p * (1 - conf['trail_dist']) 
            if new_sl > stop_loss:
                stop_loss = min(new_sl, curr_p * 0.9995) 
                logging.info(f"📈 Trailing Up! New SL: {stop_loss:.4f}")
                update_and_save_state() 

        if curr_p <= stop_loss:
            if stop_loss == break_even_price:
                logging.info("🛡️ Tersenggol Break-Even. Aman (Impas)!")
            else:
                logging.info("🚨 SL/TRAILING HIT! Jual Market Darurat!")
                
            execute_trade('SELL', config.USDT_AMOUNT, order_type="MARKET")
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            update_and_save_state()

    except Exception as e:
        logging.error(f"Monitor Error: {e}")

def trading_loop():
    """Jantung bot. Mengatur ritme antara Standby, Memantau Harga, atau Mencari Sinyal Baru."""
    global bot_active, force_buy, active_trade, stop_loss, highest_p, STRATEGY_MODE, paper_usdt_balance
    logging.info(f"Jalur Trading Siap. Mode: {'DRY RUN' if config.DRY_RUN else 'REAL MONEY'} | Strategy: {STRATEGY_MODE}")
    
    while True:
        sync_dashboard_data()
        conf = config.STRATEGIES[STRATEGY_MODE] 

        if not config.API_KEY and not config.DRY_RUN:
            logging.error("🚨 API KEY KOSONG! Mode LIVE dimatikan demi keamanan.")
            telegram_bot.send_message("🚨 *CRITICAL ERROR*\nAPI Key kosong saat mode LIVE! Bot otomatis dijeda.")
            bot_active = False
            update_and_save_state()
            time.sleep(5)
            continue
        
        try:
            # 1. Bot sedang diam dimatikan via /stop
            if not bot_active:
                trigger_scan.wait(timeout=5)
                trigger_scan.clear()
                continue

            # 2. Bot sedang pegang koin, fokus monitor (interval cepat 2 detik)
            if active_trade:
                monitor_position() 
                time.sleep(2) 
            
            # 3. Bot sedang mencari mangsa (Scanning Indikator)
            else:
                logging.info(f"🔍 [{STRATEGY_MODE}] Memulai pemindaian pasar untuk {config.SYMBOL}...")
                
                df = fetch_data(config.SYMBOL, conf['interval'])
                trigger_buy = False
                
                weather_ratio = 1.0
                
                # Skenario Beli Paksa Manual
                if force_buy:
                    trigger_buy = True
                    force_buy = False
                    # Kosongkan agar fungsi monitor_position yang ambil alih perhitungannya
                    stop_loss = 0.0 
                    highest_p = 0.0
                
                # Skenario Beli Algoritma Penuh
                elif df is not None and not df.empty:
                    is_signal, c_price = check_buy_signal(df, conf)
                    if is_signal:
                        trigger_buy = True
                        last = df.iloc[-2]

                        weather_ratio = last.get('vol_ratio', 1.0)
                        if pd.isna(weather_ratio): weather_ratio = 1.0 # Fallback jika data kosong
                        
                        # (Max 2x lipat, Min 0.5x lipat)
                        weather_ratio = max(0.5, min(weather_ratio, 2.0))

                        # SL dikalikan dengan rasio cuaca. Makin liar pasar, SL makin lebar!
                        dynamic_sl_mult = conf.get("sl_atr_mult", 1.5) * weather_ratio
                        temp_sl = c_price - (last['atr'] * dynamic_sl_mult)
                        max_minus_price = c_price * (1 - 0.05) # Hard cap SL -5%
                        if temp_sl < max_minus_price: temp_sl = max_minus_price
                        
                        stop_loss = temp_sl
                        highest_p = c_price
                        logging.info(f"✅ {STRATEGY_MODE} SIGNAL VALID! SL: {stop_loss:.4f}")

                # Melaksanakan Trigger jika diputuskan Beli
                if trigger_buy and not active_trade:
                    ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()
                    bid_p = float(ticker['bidPrice'])
                    
                    # Menggunakan getattr untuk mencegah error jika config belum terupdate
                    if getattr(config, 'USE_COMPOUNDING', False):
                        if config.DRY_RUN:
                            current_balance = paper_usdt_balance
                        else:
                            current_balance = get_balance().get('USDT', 0.0)
                        base_risk = getattr(config, 'RISK_PERCENTAGE', 5.0)
                        
                        # Jika cuaca badai (ratio > 1), modal diturunkan. Jika sepi, modal dinaikkan.
                        dynamic_risk = base_risk / weather_ratio
                        trade_amount = current_balance * (dynamic_risk / 100.0)
                        
                        # MEXC punya batas minimum transaksi (biasanya $5)
                        if trade_amount < 5.0: 
                            trade_amount = 5.0
                    else:
                        # Fallback ke modal tetap jika compounding dimatikan
                        trade_amount = config.USDT_AMOUNT

                    logging.info(f"💸 Mengalokasikan dana trade sebesar: ${trade_amount:.2f}")
                    # ==========================================
                    
                    # 💎 ZERO-FEE MAKER: Selalu antre di harga Bid terbaik (Tidak memakan harga Ask)
                    logging.info(f"💎 ZERO-FEE MAKER: Antre Beli persis di {bid_p}")
                    execute_trade('BUY', trade_amount, order_type="LIMIT", forced_price=bid_p)
                
                # Jeda Pemindaian Adaptif (Cepat saat Scalp, Lambat saat Trend)
                if not active_trade:
                    logging.info(f"💤 Jeda {conf['delay_scan']}s.")
                    trigger_scan.wait(timeout=conf['delay_scan'])
                    trigger_scan.clear()

        except Exception as e:
            logging.error(f"⚠️ Error di Trading Loop: {e}")
            time.sleep(10)

def send_chart():
    """Menggambar riwayat harga 30 batang lilin terakhir dan mengirimnya sebagai PNG ke Telegram."""
    try:
        conf = config.STRATEGIES[STRATEGY_MODE] 
        df = fetch_data(config.SYMBOL, conf['interval'])
        if df is None or df.empty: return
        
        df_plot = df.tail(30).copy()
        plt.clf() 
        plt.figure(figsize=(10, 6))
        
        plt.plot(df_plot['timestamp'], df_plot['close'], label='Price', color='#1f77b4', linewidth=2)
        plt.plot(df_plot['timestamp'], df_plot['vwap'].tail(30), label='VWAP', color='#ff7f0e', linestyle='--')
        
        plt.title(f"Chart {config.SYMBOL} - {datetime.now().strftime('%H:%M:%S')}")
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        chart_path = "current_chart.png"
        plt.savefig(chart_path)
        plt.close('all')
        
        telegram_bot.send_photo(chart_path)
        
        if os.path.exists(chart_path): os.remove(chart_path)
            
    except Exception as e:
        logging.error(f"Gagal kirim chart: {e}")

def heartbeat_loop():
    """Thread khusus untuk mengirim detak jantung ke JSON setiap 5 detik"""
    while True:
        try:
            if os.path.exists(config.STATE_FILE):
                with open(config.STATE_FILE, "r") as f:
                    data = json.load(f)
                
                data["last_heartbeat"] = time.time()
                
                with open(config.STATE_FILE, "w") as f:
                    json.dump(data, f)
        except:
            pass
        time.sleep(5) # Berdetak setiap 5 detik

# --- MAIN EXECUTION (Garis Start) ---
if __name__ == "__main__":
    database.init_db() # Inisialisasi database
    bot_active = True
    update_and_save_state()

    sync_dashboard_data()
    print("--- BOT MEXC REST API V3 ---")
    status_msg = "🤖 *Bot Started!*\nMode: ⚡ *FORCE BUY*" if force_buy else "🤖 *Bot Started!*\nMode: 🔍 *AUTO SCAN*"
    telegram_bot.send_message(status_msg)
    print("Tekan Ctrl + C untuk berhenti total.")
    
    if not config.API_KEY:
        logging.error("❌ ERROR: API KEY tidak ditemukan di konfigurasi!")
        sys.exit()
    
    t_heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
    t_heartbeat.start()
    
    # Jalankan Telegram di latar belakang, berikan file main.py (sys.modules[__name__]) 
    # sebagai "remote control" kepada file telegram_bot.py
    t1 = threading.Thread(target=telegram_bot.start_polling, args=(sys.modules[__name__],))
    t2 = threading.Thread(target=trading_loop)
    
    t1.daemon = True 
    t2.daemon = True
    
    t1.start()
    t2.start()
    
    try:
        # Menjaga bot tetap hidup selamanya kecuali ditutup paksa
        while True:
            time.sleep(5)
            # Jika koneksi putus dan Telegram Crash, coba pancing agar hidup lagi
            if not t1.is_alive():
                logging.warning("⚠️ Jalur Telegram terputus/mati! Membangkitkan ulang...")
                t1 = threading.Thread(target=telegram_bot.start_polling, args=(sys.modules[__name__],))
                t1.daemon = True
                t1.start()
                
    except KeyboardInterrupt:
        # Pemicu Graceful Shutdown jika Anda menekan Ctrl+C
        bot_active = False
        update_and_save_state()
        print("\n🛑 Signal Shutdown Diterima (Ctrl+C)...")
        time.sleep(1) 

        try:
            with open(config.STATE_FILE, "r") as f:
                state = json.load(f)
            
            state["is_active"] = False
            state["last_heartbeat"] = 0 
            
            with open(config.STATE_FILE, "w") as f:
                json.dump(state, f)
        except Exception as e:
            pass

        # Auto-Sell Protektif untuk menyelamatkan aset yang ditinggal mati
        if active_trade:
            print("⚠️ Ada posisi aktif! Mencoba melakukan SELL otomatis...")
            telegram_bot.send_message("⚠️ *Shutdown Alert*: Menutup posisi sebelum offline...")
            try:
                execute_trade('SELL', config.USDT_AMOUNT)
                print("✅ Posisi berhasil ditutup.")
            except Exception as e:
                print(f"❌ Gagal menutup posisi: {e}")
        else:
            print("✅ Tidak ada posisi aktif. Aman untuk dimatikan.")

        try: telegram_bot.send_message("🛑 *Bot Shutdown Selesai*\nStatus: Offline")
        except: pass
            
        print("Bot Berhenti Total. Sampai jumpa!")
        sys.exit(0)