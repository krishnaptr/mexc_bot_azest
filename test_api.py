import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

exchange = ccxt.mexc({
    'apiKey': os.getenv('API_KEY').strip(),
    'secret': os.getenv('SECRET_KEY').strip(),
})

try:
    balance = exchange.fetch_balance()
    print("✅ Koneksi Berhasil! Saldo USDT Anda:", balance['total'].get('USDT', 0))
except Exception as e:
    print(f"❌ Tetap Error: {e}")