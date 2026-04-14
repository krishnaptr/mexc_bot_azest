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
STRATEGY_MODE = "SCALP"

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
        "active_trade": active_trade,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "highest_p": highest_p,
        "trade_count": trade_count,
        "total_accumulated_profit": total_accumulated_profit
    }
    database.save_state(state)

# --- FUNGSI UTILS & PRESISI ---
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
        df['vol_sma'] = ta.sma(df['volume'], length=20)
        
        # Hitung VWAP (Volume Weighted Average Price)
        tp = (df['high'] + df['low'] + df['close']) / 3
        df['vwap'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
        
        return df
    except: return None

def get_balance():
    """Mengecek saldo aktual USDT dan Token di dompet MEXC Anda."""
    res = mexc_request('GET', '/api/v3/account')
    asset_name = config.SYMBOL.replace('USDT', '')
    bal = {'USDT': 0.0, asset_name: 0.0} 
    if 'balances' in res:
        for b in res['balances']:
            if b['asset'] in ['USDT', asset_name]: bal[b['asset']] = float(b['free'])
    return bal

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
    price_str = "{:f}".format(round_step(price, info['price_step']))
    params = {'symbol': config.SYMBOL, 'side': side.upper(), 'type': order_type}
    
    if order_type == "LIMIT":
        params['price'] = price_str
        params['quantity'] = "{:f}".format(round_step(amount / float(price_str), info['qty_step']))
        params['timeInForce'] = "GTC" 

    if side.upper() == 'BUY':
        if order_type == "MARKET":
            params['quoteOrderQty'] = round_step(amount, info['price_step'])
        
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
                'quantity': "{:f}".format(round_step(exec_qty * 0.99, info['qty_step'])),
                'price': "{:f}".format(hard_sl_price), 'stopPrice': "{:f}".format(hard_sl_price)
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
        
        params['quantity'] = "{:f}".format(round_step(qty * 0.99, info['qty_step']))
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
    
def monitor_position():
    global active_trade, stop_loss, highest_p, entry_price, STRATEGY_MODE
    conf = config.STRATEGIES[STRATEGY_MODE]
    tp_price = entry_price * (1 + conf['tp_percent'])
    
    if stop_loss == 0:
        stop_loss = entry_price * 0.99 
        highest_p = entry_price

    try:
        ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}, timeout=5).json()
        curr_p = float(ticker['bidPrice'])
        
        if curr_p > highest_p: highest_p = curr_p
        pnl_gross = (curr_p - entry_price) / entry_price
        pnl_net = pnl_gross - config.EXCHANGE_FEE

        logging.info(f"[{STRATEGY_MODE}] {config.SYMBOL} | Price: {curr_p} | Net PNL: {pnl_net*100:.2f}% | SL: {stop_loss:.4f} | TP: {tp_price:.4f}")

        if conf['use_hard_tp'] and curr_p >= tp_price:
            logging.info(f"🎯 HARD TP HIT! Menjual...")
            execute_trade('SELL', config.USDT_AMOUNT)
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            update_and_save_state()
            return

        if pnl_gross >= conf['trail_start']: 
            new_sl = highest_p * (1 - conf['trail_dist']) 
            if new_sl > stop_loss:
                stop_loss = min(new_sl, curr_p * 0.9995) 
                logging.info(f"📈 Trailing Up! New SL: {stop_loss:.4f}")
                update_and_save_state() 

        if curr_p <= stop_loss:
            execute_trade('SELL', config.USDT_AMOUNT)
            active_trade, stop_loss, highest_p = False, 0.0, 0.0
            update_and_save_state()

    except Exception as e:
        logging.error(f"Monitor Error: {e}")

def trading_loop():
    """Jantung bot. Mengatur ritme antara Standby, Memantau Harga, atau Mencari Sinyal Baru."""
    global bot_active, force_buy, active_trade, stop_loss, highest_p, STRATEGY_MODE
    logging.info(f"Jalur Trading Siap. Mode: {'DRY RUN' if config.DRY_RUN else 'REAL MONEY'} | Strategy: {STRATEGY_MODE}")
    
    while True:
        conf = config.STRATEGIES[STRATEGY_MODE] 
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
                df = fetch_data(config.SYMBOL, conf['interval'])
                trigger_buy = False
                
                # Skenario Beli Paksa Manual
                if force_buy:
                    trigger_buy = True
                    force_buy = False
                    # Kosongkan agar fungsi monitor_position yang ambil alih perhitungannya
                    stop_loss = 0.0 
                    highest_p = 0.0
                
                # Skenario Beli Algoritma Penuh
                elif df is not None and not df.empty:
                    last = df.iloc[-2] # Candle yang ditutup terakhir
                    prev = df.iloc[-3] # Candle pendahulunya
                    
                    ticker_realtime = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()
                    curr_price = float(ticker_realtime['askPrice'])
                    
                    # Parameter Konfirmasi Momentum
                    curr_rsi = last['rsi']
                    rsi_moving_up = curr_rsi > prev['rsi'] 
                    found_hammer = is_hammer(last)         
                    volume_breakout = last['volume'] > (last['vol_sma'] * conf["vol_mult"])
                    
                    logging.info(f"🔍 [{STRATEGY_MODE}] Scan {config.SYMBOL} | Price: {curr_price} | RSI: {curr_rsi:.2f} | Up: {rsi_moving_up} | Hammer: {found_hammer}")
                    
                    # Parameter Tren Utama
                    is_uptrend = curr_price > last['ema_200'] if conf["use_ema_200"] else True
                    rsi_healthy = (conf["rsi_min"] < curr_rsi < conf["rsi_max"])

                    # Eksekusi Evaluasi Sinyal
                    if is_uptrend and rsi_healthy and rsi_moving_up:
                        if found_hammer:
                            trigger_buy = True
                            logging.info(f"🚀 AGGRESSIVE ENTRY: Hammer Detected!")
                        elif curr_price > last['open'] and volume_breakout:
                            trigger_buy = True
                            logging.info(f"🚀 STANDARD ENTRY: Bullish Momentum!")

                        # Set SL Dasar Berdasarkan Volatilitas (ATR)
                        if trigger_buy:
                            stop_loss = curr_price - (last['atr'] * conf["sl_atr_mult"]) 
                            highest_p = curr_price
                            logging.info(f"✅ {STRATEGY_MODE} SIGNAL VALID! SL: {stop_loss:.4f}")

                # Melaksanakan Trigger jika diputuskan Beli
                if trigger_buy and not active_trade:
                    is_safe, current_spread = check_spread(config.SYMBOL, 2.0) 
                    
                    if is_safe:
                        info = get_symbol_info(config.SYMBOL)
                        ticker_res = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()
                        bid_price = float(ticker_res['bidPrice'])
                        ask_price = float(ticker_res['askPrice'])
                        
                        # Keputusan Pintar (Front-Running vs Market)
                        if current_spread <= 0.05:
                            execute_trade('BUY', config.USDT_AMOUNT, order_type="MARKET")
                        else:
                            tick_size = info['price_step'] 
                            limit_price = bid_price + tick_size 
                            if limit_price >= ask_price: limit_price = bid_price 

                            logging.info(f"🟡 Mengantre di depan (Bid+1): {limit_price}")
                            execute_trade('BUY', config.USDT_AMOUNT, order_type="LIMIT", forced_price=limit_price)
                
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

# --- MAIN EXECUTION (Garis Start) ---
if __name__ == "__main__":
    database.init_db() # Inisialisasi database
    
    print("--- BOT MEXC REST API V3 ---")
    status_msg = "🤖 *Bot Started!*\nMode: ⚡ *FORCE BUY*" if force_buy else "🤖 *Bot Started!*\nMode: 🔍 *AUTO SCAN*"
    telegram_bot.send_message(status_msg)
    print("Tekan Ctrl + C untuk berhenti total.")
    
    if not config.API_KEY:
        logging.error("❌ ERROR: API KEY tidak ditemukan di konfigurasi!")
        sys.exit()
    
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
        print("\n🛑 Signal Shutdown Diterima (Ctrl+C)...")
        time.sleep(1) 

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