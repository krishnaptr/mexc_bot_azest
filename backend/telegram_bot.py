import time
import requests
import logging
import threading
import json
from urllib.parse import urlencode

# Import modul buatan kita
import config
import database

# Variabel Global untuk Polling Telegram
last_update_id = 0

def send_message(message: str):
    """Mengirim pesan notifikasi ke Telegram dengan perlindungan batas waktu (Timeout 5 detik)."""
    if not config.TELE_TOKEN: return
    try:
        requests.post(f"https://api.telegram.org/bot{config.TELE_TOKEN}/sendMessage", 
                      data={"chat_id": config.TELE_CHAT_ID, "text": message, "parse_mode": "Markdown"}, timeout=5) 
    except Exception as e:
        logging.error(f"Gagal kirim Telegram: {e}")

def send_photo(photo_path: str):
    """Mengirim gambar (chart) ke Telegram."""
    if not config.TELE_TOKEN: return
    try:
        with open(photo_path, 'rb') as photo:
            requests.post(f"https://api.telegram.org/bot{config.TELE_TOKEN}/sendPhoto", 
                          params={'chat_id': config.TELE_CHAT_ID}, files={'photo': photo}, timeout=10)
    except Exception as e:
        logging.error(f"Gagal kirim foto Telegram: {e}")

def handle_status_command(bot_engine_module, status: str):
    """Menyusun dan mengirim laporan komprehensif ketika pengguna mengetik /status."""
    try:
        # Mengambil data langsung dari modul bot utama (main.py / engine)
        ticker = requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}, timeout=5).json()
        current_price = float(ticker['bidPrice'])
        asset_name = config.SYMBOL.replace('USDT', '')
        
        # Ambil state terbaru dari memori
        state_data = database.load_state()
        active_trade = state_data.get("active_trade", False)
        entry_price = state_data.get("entry_price", 0.0)
        total_accumulated_profit = state_data.get("total_accumulated_profit", 0.0)
        trade_count = state_data.get("trade_count", 0)

        if not config.DRY_RUN:
            bal = bot_engine_module.get_balance() # Memanggil fungsi get_balance dari engine
            usdt_display, coin_display = bal.get('USDT', 0.0), bal.get(asset_name, 0.0)
        else:
            usdt_display = database.load_sim_balance()
            # Asumsi sederhana untuk display jika ada koin nyangkut di simulasi
            coin_display = (config.USDT_AMOUNT / entry_price) if active_trade else 0.0

        floating_pnl_str = ""
        current_value = coin_display * current_price
        total_equity = usdt_display + current_value
        
        # Hitung PNL mengambang hanya jika bot sedang nyangkut beli koin
        if active_trade and entry_price > 0:
            f_pnl_gross = (current_price - entry_price) / entry_price
            f_pnl_net = f_pnl_gross - config.EXCHANGE_FEE
            floating_pnl_str = f"\n🔄 *PNL Berjalan (Net):* `{f_pnl_net*100:.2f}%`"

        pnl_info = f"\n💰 *Total Profit:* `{total_accumulated_profit*100:.2f}%` ({trade_count} trades)"
  
        msg = (f"🤖 *BOT STATUS:* {status}\n"
               f"━━━━━━━━━━━━━━━\n"
               f"📈 Mode: `{'SIMULASI' if config.DRY_RUN else 'LIVE'}`\n"
               f"⚙️ Strategy: `{bot_engine_module.STRATEGY_MODE}`\n"
               f"🪙 Token: `{config.SYMBOL}`\n"
               f"💵 Harga: `${current_price:.4f}`"
               f"{floating_pnl_str}{pnl_info}\n\n"
               f"🏦 *INFO SALDO:*\n"
               f"💵 USDT: `{usdt_display:.2f}`\n"
               f"🪙 {asset_name}: `{coin_display:.6f}`\n"
               f"💰 *Total Equity:* `{total_equity:.2f}`")
        send_message(msg)
    except Exception as e:
        logging.error(f"Error status Telegram: {e}")

def handle_command(bot_engine_module, msg_text: str):
    """Pusat saraf untuk membaca dan merespons segala bentuk interaksi dari pengguna di Telegram."""
    
    # Command Perubahan Strategi
    if msg_text == "/mode_trend":
        bot_engine_module.STRATEGY_MODE = "TREND"
        bot_engine_module.trigger_scan.set()
        send_message("🚀 Mode diubah ke: *TREND*")
        
    elif msg_text == "/mode_scalp":
        bot_engine_module.STRATEGY_MODE = "SCALP"
        bot_engine_module.trigger_scan.set()
        send_message("⚡ Mode diubah ke: *SCALP*")
    
    elif msg_text == "/status":
        status_text = "🟢 ON" if bot_engine_module.bot_active else "🔴 OFF"
        handle_status_command(bot_engine_module, status_text)
        bot_engine_module.send_chart() # Suruh engine menggambar dan mengirim chart
    
    # Command Ganti Koin
    elif msg_text.startswith("/symbol"):
        if bot_engine_module.active_trade:
            send_message(f"❌ *DITOLAK:* Bot menahan posisi di `{config.SYMBOL}`. Jual dulu.")
            return
            
        parts = msg_text.split()
        if len(parts) > 1:
            new_symbol = parts[1].upper().strip() 
            try:
                cek_koin = requests.get(f"{config.BASE_URL}/api/v3/ticker/price", params={'symbol': new_symbol}).json()
                if 'price' in cek_koin: 
                    try:
                        with open("settings.json", "r") as f:
                            settings_data = json.load(f)
                        
                        settings_data["general"]["symbol"] = new_symbol
                        
                        with open("settings.json", "w") as f:
                            json.dump(settings_data, f, indent=4)
                            
                        config.SYMBOL = new_symbol 
                        send_message(f"✅ Target permanen diubah ke `{config.SYMBOL}` (${cek_koin['price']})")
                        bot_engine_module.trigger_scan.set()
                        
                    except Exception as e:
                        send_message(f"❌ Gagal menyimpan ke settings.json: {e}")
                else: 
                    send_message(f"❌ Koin `{new_symbol}` *TIDAK DITEMUKAN*")
            except: 
                send_message("⚠️ Gagal verifikasi koin.")
    
    # Command Trigger Beli Paksa
    elif msg_text == "/forcebuy":
        keyboard = {"inline_keyboard": [[{"text": "✅ Beli Sekarang", "callback_data": "confirm_buy"}, {"text": "❌ Batal", "callback_data": "cancel_buy"}]]}
        requests.post(f"https://api.telegram.org/bot{config.TELE_TOKEN}/sendMessage", 
                      json={"chat_id": config.TELE_CHAT_ID, "text": f"⚠️ *FORCE BUY* `{config.SYMBOL}`?\nPeringatan: Ini akan menggunakan uang asli jika dalam mode LIVE!", "reply_markup": keyboard, "parse_mode": "Markdown"})
    
    # Command Jual Paksa Darurat
    elif msg_text in ["/stop", "/panic", "/exit"]:
        if msg_text == "/panic": send_message("🚨 *PANIC BUTTON TRIGGERED!* 🚨")
        
        if bot_engine_module.active_trade:
            try: 
                curr_p = float(requests.get(f"{config.BASE_URL}/api/v3/ticker/bookTicker", params={'symbol': config.SYMBOL}).json()['bidPrice'])
            except: 
                curr_p = None
            
            send_message(f"⚠️ Menutup posisi di harga `{curr_p if curr_p else 'Market'}`...")
            
            # Suruh engine mengeksekusi trade jual paksa
            bot_engine_module.execute_trade('SELL', config.USDT_AMOUNT, forced_price=curr_p)
            
            # Reset state di engine
            bot_engine_module.active_trade = False
            bot_engine_module.entry_price = 0.0
            bot_engine_module.stop_loss = 0.0
            bot_engine_module.highest_p = 0.0
            bot_engine_module.update_and_save_state()
            
            send_message("✅ *Posisi ditutup.*")
        else:
            send_message("ℹ️ Tidak ada posisi aktif.")
        
        # Hentikan operasi background jika itu perintah mati total
        if msg_text in ["/stop", "/panic"]: 
            bot_engine_module.bot_active = False
            bot_engine_module.update_and_save_state()
            send_message("🛑 *BOT STOPPED*")

    elif msg_text == "/start":
        bot_engine_module.bot_active = True
        bot_engine_module.trigger_scan.set()
        send_message("✅ *BOT STARTED* 🟢")
    
    elif msg_text == "/reset_sim":
        # Reset saldo simulasi ke 1000
        database.save_sim_balance(1000.0)
        bot_engine_module.paper_usdt_balance = 1000.0
        bot_engine_module.paper_coin_holdings = 0.0
        
        # Reset memory profit
        bot_engine_module.total_accumulated_profit = 0.0
        bot_engine_module.trade_count = 0
        bot_engine_module.active_trade = False
        bot_engine_module.entry_price = 0.0
        
        bot_engine_module.update_and_save_state()
        send_message("♻️ *Simulasi di-reset ke $1000!*")
        
    elif msg_text == "/help":
        send_message("📜 *Daftar Perintah:*\n`/start` `/stop` `/exit` `/panic` `/symbol [KOIN]` `/status` `/forcebuy` `/mode_trend` `/mode_scalp` `/reset_sim`")

def start_polling(bot_engine_module):
    """Fungsi Long-Polling API Telegram. Mengecek pesan baru terus menerus di latar belakang."""
    global last_update_id
    logging.info("Jalur Telegram Siap (Dipisahkan).")
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{config.TELE_TOKEN}/getUpdates"
            res = requests.get(url, params={"offset": last_update_id+1, "timeout": 5}, timeout=10).json()
            updates = res.get("result", [])
            
            if updates:
                last_update_id = updates[-1]["update_id"]
                for u in updates:
                    # Evaluasi Text Command biasa
                    if "message" in u and str(u["message"].get("from", {}).get("id")) == str(config.TELE_CHAT_ID):
                        msg_text = u["message"].get("text", "")
                        handle_command(bot_engine_module, msg_text)
                    
                    # Evaluasi Klik Tombol Inline GUI
                    elif "callback_query" in u and str(u["callback_query"].get("from", {}).get("id")) == str(config.TELE_CHAT_ID):
                        cb = u["callback_query"]
                        if cb.get("data") == "confirm_buy" and not bot_engine_module.active_trade:
                            bot_engine_module.force_buy = True
                            bot_engine_module.trigger_scan.set()
                            send_message("🚀 *Menjalankan order instan...*")
                        
                        # Beri tahu Telegram bahwa tombol sudah diklik (hilangkan efek loading di tombol)
                        requests.post(f"https://api.telegram.org/bot{config.TELE_TOKEN}/answerCallbackQuery", data={"callback_query_id": cb.get("id")})
        except Exception:
            pass # Abaikan error koneksi (timeout dll) agar tidak spamming log
            
        time.sleep(1)