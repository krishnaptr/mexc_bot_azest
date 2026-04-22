import pandas as pd
import pandas_ta as ta
import requests
import time
import config

print("⏳ Menginisialisasi Mesin Backtest...")

# 1. AMBIL KONFIGURASI
STRATEGY = "TREND"
conf = config.get_settings()[STRATEGY.lower()]
symbol = config.get_settings()['general']['symbol']
interval = conf['interval']
fee_maker = 0.0000  # 0% Fee untuk Maker (Antre Limit)
fee_taker = 0.0010  # 0.1% Fee untuk Taker (Hajar Market)

print(f"📊 Mengunduh 1000 data historis {symbol} ({interval})...")

# 2. UNDUH DATA HISTORIS (1000 Candle = Maksimal dari API MEXC)
url = f"{config.BASE_URL}/api/v3/klines"
res = requests.get(url, params={'symbol': symbol, 'interval': interval, 'limit': 1000}).json()

df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'ct', 'qav'])
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = pd.to_numeric(df[col])

# 3. HITUNG INDIKATOR
df['rsi'] = ta.rsi(df['close'], length=14)
df['ema_200'] = ta.ema(df['close'], length=200)
df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
df['vol_sma'] = ta.sma(df['volume'], length=20)
df['adx'] = ta.adx(df['high'], df['low'], df['close'], length=14)['ADX_14']

# 4. VARIABEL SIMULASI
balance = 1000.0 # Modal awal virtual $1000
use_compounding = config.get_settings()['general'].get('use_compounding', False)
risk_percentage = config.get_settings()['general'].get('risk_percentage', 5.0)
usdt_per_trade = config.get_settings()['general']['usdt_amount']
position_size = 0.0
entry_price = 0.0
stop_loss = 0.0
highest_p = 0.0

trades = []
winning_trades = 0
losing_trades = 0
breakeven_trades = 0

print("⚙️ Memulai Simulasi Mesin Waktu...\n")

# Mulai dari index 200 agar EMA-200 sudah memiliki nilai yang valid
for i in range(200, len(df)):
    curr = df.iloc[i]
    prev = df.iloc[i-1]
    
    # JIKA SEDANG MEMEGANG KOIN (MONITORING)
    if position_size > 0:
        # Update Highest Price
        if curr['high'] > highest_p: highest_p = curr['high']
            
        pnl_gross_high = (curr['high'] - entry_price) / entry_price
        pnl_gross_close = (curr['close'] - entry_price) / entry_price
        
        tp_price = entry_price * (1 + conf['tp_percent'])
        # Total fee adalah Beli (Maker) + Jual (Taker)
        fee_buffer = (fee_maker + fee_taker) + 0.0005
        break_even_price = entry_price * (1 + fee_buffer)
        
        sell_price = 0.0
        sell_reason = ""
        
        # Skenario 1: Tersenggol TP (Hard TP)
        if conf['use_hard_tp'] and curr['high'] >= tp_price:
            sell_price = tp_price
            sell_reason = "🎯 TAKE PROFIT"
            
        # Skenario 2: Tersenggol Stop Loss / Trailing / Break-Even (Harga Low menyentuh SL)
        elif curr['low'] <= stop_loss:
            sell_price = stop_loss
            if stop_loss == break_even_price: sell_reason = "🛡️ BREAK-EVEN"
            elif stop_loss > entry_price: sell_reason = "📈 TRAIL PROFIT"
            else: sell_reason = "📉 STOP LOSS"
        
        # Jika belum terjual, cek apakah perlu update SL untuk candle berikutnya
        if sell_price == 0.0:
            # Update Break-Even
            if pnl_gross_close >= conf.get('breakeven_start', 0.015) and stop_loss < break_even_price:
                stop_loss = break_even_price
            # Update Trailing
            if pnl_gross_close >= conf['trail_start']:
                new_sl = highest_p * (1 - conf['trail_dist'])
                if new_sl > stop_loss: stop_loss = new_sl
        
        # Eksekusi Penjualan Virtual
        else:
            # Beli selalu Maker (0%). Jual tergantung alasan: TP = Maker (0%), SL/Trail = Taker (0.1%)
            fee_buy = fee_maker 
            fee_sell = fee_maker if "TAKE PROFIT" in sell_reason else fee_taker
            total_fee_percent = fee_buy + fee_sell

            net_pnl = ((sell_price - entry_price) / entry_price) - total_fee_percent
            profit_usdt = usdt_per_trade * net_pnl
            balance += profit_usdt
            
            if net_pnl > 0.001: winning_trades += 1
            elif net_pnl < -0.001: losing_trades += 1
            else: breakeven_trades += 1
                
            trades.append(net_pnl)
            position_size, entry_price, stop_loss, highest_p = 0.0, 0.0, 0.0, 0.0
            
    # JIKA TIDAK MEMEGANG KOIN (MENCARI SINYAL)
    else:
        # Logika Sinyal (Sederhana tanpa MTF Eksternal untuk kecepatan backtest)
        rsi_moving_up = prev['rsi'] > df.iloc[i-2]['rsi']
        is_uptrend = prev['close'] > prev['ema_200'] if conf['use_ema_200'] else True
        rsi_healthy = conf['rsi_min'] < prev['rsi'] < conf['rsi_max']
        is_trending = True if STRATEGY == "SCALP" else prev['adx'] > 25.0
        volume_breakout = prev['volume'] > (prev['vol_sma'] * conf['vol_mult'])
        
        if is_uptrend and rsi_healthy and rsi_moving_up and is_trending and volume_breakout:
            if use_compounding:
                usdt_per_trade = balance * (risk_percentage / 100.0)
                if usdt_per_trade < 5.0: usdt_per_trade = 5.0

            # Beli di harga open candle saat ini
            entry_price = curr['open']
            position_size = usdt_per_trade / entry_price
            highest_p = entry_price
            
            # Set SL Awal
            temp_sl = entry_price - (prev['atr'] * conf.get("sl_atr_mult", 1.5))
            max_sl = entry_price * 0.95 # Max -5%
            stop_loss = max_sl if temp_sl < max_sl else temp_sl

# 5. LAPORAN HASIL
total_trades = len(trades)
win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

print("========================================")
print(f"📊 HASIL BACKTEST: {symbol} | Strategi: {STRATEGY}")
print("========================================")
print(f"Total Trade      : {total_trades} kali")
print(f"Menang (Win)     : {winning_trades}")
print(f"Kalah (Loss)     : {losing_trades}")
print(f"Impas (Break-Ev) : {breakeven_trades}")
print(f"Win Rate         : {win_rate:.2f}%")
print("----------------------------------------")
print(f"Modal Awal       : $1000.00")
print(f"Modal Akhir      : ${balance:.2f}")
print(f"Net Profit       : ${(balance - 1000):.2f} ({((balance - 1000)/1000)*100:.2f}%)")
print("========================================")
if balance > 1000:
    print("✅ Strategi ini MENGUNTUNGKAN di masa lalu. Siap digunakan!")
else:
    print("❌ Strategi ini MERUGIKAN. Jangan digunakan di akun real. Ubah parameter!")