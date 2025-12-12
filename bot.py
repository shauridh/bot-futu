import ccxt
import pandas as pd
import pandas_ta as ta
import time
import os
import asyncio
from datetime import datetime
from telegram import Bot

# --- KONFIGURASI ---
API_KEY = os.getenv("BINANCE_API_KEY", "MASUKKAN_KEY_TESTNET")
API_SECRET = os.getenv("BINANCE_SECRET", "MASUKKAN_SECRET_TESTNET")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "TOKEN_BOT")
CHAT_ID = os.getenv("CHAT_ID", "ID_TELEGRAM")

# Setting Trading
SYMBOL = 'BTC/USDT'  # Pasangan koin
TIMEFRAME = '15m'    # Timeframe (15 menit cocok untuk bot)
LEVERAGE = 5         # Leverage (Jangan serakah, 5x - 10x cukup)
USDT_PER_TRADE = 20  # Modal per posisi (dalam USDT)

# Inisialisasi Exchange (Binance Futures Testnet)
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'options': {'defaultType': 'future'},
    'enableRateLimit': True
})
exchange.set_sandbox_mode(True) # AKTIFKAN INI UNTUK TESTNET! HAPUS UTK REAL.

# --- FUNGSI TELEGRAM ---
async def send_telegram(message):
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHAT_ID, text=message)
    except Exception as e:
        print(f"❌ Gagal kirim Telegram: {e}")

# --- SETUP AWAL ---
def setup_leverage():
    try:
        # Load market dulu
        exchange.load_markets()
        market = exchange.market(SYMBOL)
        
        # Set Leverage
        exchange.set_leverage(LEVERAGE, SYMBOL)
        print(f"✅ Leverage {SYMBOL} set ke {LEVERAGE}x")
    except Exception as e:
        print(f"⚠️ Gagal set leverage: {e}")

# --- ANALISIS TEKNIKAL ---
def fetch_data():
    try:
        # Ambil 100 candle terakhir
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=200)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # 1. EMA 200 (Tren Besar)
        df['EMA200'] = ta.ema(df['close'], length=200)
        
        # 2. ATR (Volatilitas)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        # 3. Supertrend (Sinyal)
        # return pandas_ta supertrend berupa DataFrame: ['SUPERT_7_3.0', 'SUPERTd_7_3.0', ...]
        supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
        df = pd.concat([df, supertrend], axis=1)
        
        # Rename kolom supertrend biar gampang (biasanya namanya panjang)
        # Ambil kolom pertama (Line Supertrend) dan kedua (Direction: 1=Up, -1=Down)
        st_col_line = supertrend.columns[0] 
        st_col_dir = supertrend.columns[1]
        df['ST_LINE'] = df[st_col_line]
        df['ST_DIR'] = df[st_col_dir]
        
        return df
    except Exception as e:
        print(f"❌ Error fetch data: {e}")
        return None

# --- EKSEKUSI ORDER ---
def execute_trade(signal, price, atr):
    try:
        # Hitung Quantity (USDT / Harga)
        amount = USDT_PER_TRADE / price 
        
        # Stop Loss & Take Profit berdasarkan ATR
        # Risk Reward Ratio 1:2
        sl_dist = atr * 2
        tp_dist = atr * 4
        
        if signal == 'LONG':
            sl_price = price - sl_dist
            tp_price = price + tp_dist
            side = 'buy'
            msg_head = "🚀 LONG SIGNAL"
            
        elif signal == 'SHORT':
            sl_price = price + sl_dist
            tp_price = price - tp_dist
            side = 'sell'
            msg_head = "🔻 SHORT SIGNAL"
            
        # 1. Eksekusi Market Order (Masuk Posisi)
        order = exchange.create_market_order(SYMBOL, side, amount)
        
        # 2. Pasang SL & TP (Binance butuh order terpisah untuk SL/TP di API)
        # Catatan: Ini versi simplifikasi. Untuk production, SL/TP harus presisi.
        # Di Binance Futures, SL/TP biasanya dipasang via parameter 'params' atau order terpisah.
        # Kita kirim notifikasi saja dulu untuk manual intervention atau advanced logic.
        
        msg = (f"{msg_head}\n"
               f"Pair: {SYMBOL}\n"
               f"Entry: {price}\n"
               f"Leverage: {LEVERAGE}x\n"
               f"🛑 SL: {sl_price:.2f}\n"
               f"🎯 TP: {tp_price:.2f}\n"
               f"(Auto-Order Executed on Testnet)")
               
        print(f"✅ Trade Executed: {side} {amount} @ {price}")
        asyncio.run(send_telegram(msg))
        
        return True

    except Exception as e:
        print(f"❌ Gagal Order: {e}")
        asyncio.run(send_telegram(f"⚠️ Gagal Eksekusi: {e}"))
        return False

# --- POSISI CEK ---
def check_positions():
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for pos in positions:
            # Cek jika ada posisi terbuka (contracts > 0)
            if float(pos['contracts']) > 0:
                return True, pos['side'] # 'long' atau 'short'
        return False, None
    except:
        return False, None

# --- ENGINE UTAMA ---
def run_bot():
    print("🤖 Binance Futures Bot Aktif (TESTNET)...")
    setup_leverage()
    asyncio.run(send_telegram("✅ Bot Futures Aktif (Supertrend Strategy)"))
    
    while True:
        try:
            df = fetch_data()
            if df is None:
                time.sleep(10)
                continue
                
            last = df.iloc[-1]    # Candle sekarang (belum close)
            prev = df.iloc[-2]    # Candle terakhir yg sudah close
            
            # Cek apakah kita punya posisi?
            in_position, pos_side = check_positions()
            
            # --- LOGIKA ENTRY ---
            # Kita hanya entry jika TIDAK punya posisi
            if not in_position:
                
                # LONG: Harga > EMA200 DAN Supertrend berubah jadi Hijau (1)
                if (prev['close'] > prev['EMA200']) and (prev['ST_DIR'] == 1 and df.iloc[-3]['ST_DIR'] == -1):
                    print("Sinyal LONG terdeteksi...")
                    execute_trade('LONG', last['close'], last['ATR'])
                    
                # SHORT: Harga < EMA200 DAN Supertrend berubah jadi Merah (-1)
                elif (prev['close'] < prev['EMA200']) and (prev['ST_DIR'] == -1 and df.iloc[-3]['ST_DIR'] == 1):
                    print("Sinyal SHORT terdeteksi...")
                    execute_trade('SHORT', last['close'], last['ATR'])
            
            else:
                print(f"⏳ Sedang dalam posisi {pos_side}. Menunggu TP/SL...")

            # Jeda 15 detik (Binance rate limit aman)
            time.sleep(15)
            
        except Exception as e:
            print(f"Error Loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
