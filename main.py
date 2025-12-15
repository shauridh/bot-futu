import ccxt
import pandas as pd
import time
import os
import requests
import sys
from datetime import datetime

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# --- SETTING TRADING ---
SYMBOL = 'BTC/USDT'      
TIMEFRAME = '1h'         
VIRTUAL_BALANCE = 1000   # Kita pura-pura punya 1000 USDT
LEVERAGE = 5

# --- VARIABLE SIMULASI (PAPER TRADING) ---
# Menyimpan status posisi di memori bot
current_position = None # None, 'LONG', atau 'SHORT'
entry_price = 0
sl_price = 0
tp_price = 0

print("--- STARTING PAPER TRADING BOT ---")

# Inisialisasi Exchange (MODE PUBLIC - TANPA API KEY)
# Kita hanya butuh data harga, jadi tidak perlu login
try:
    exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })
    # Cek koneksi dengan ambil harga terakhir
    ticker = exchange.fetch_ticker(SYMBOL)
    print(f"✅ Koneksi Data Real-Time Berhasil! Harga {SYMBOL}: {ticker['last']}")
except Exception as e:
    print(f"❌ Gagal koneksi ke Binance: {e}")
    sys.exit(1)

def send_telegram(msg):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"}
    try: 
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"⚠️ Error Telegram: {e}")

def calculate_indicators(df):
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # ATR Calculation
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift())
    df['tr3'] = abs(df['low'] - df['close'].shift())
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    df['ATR'] = df['tr'].rolling(window=14).mean()
    return df

def get_data():
    try:
        # Ambil data REAL MARKET (Bukan Testnet)
        bars = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=250)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        return calculate_indicators(df)
    except Exception as e:
        print(f"Error fetch data: {e}")
        return None

def execute_simulation(action, price, atr):
    global current_position, entry_price, sl_price, tp_price
    
    # Hitung TP/SL
    sl_pips = atr * 1.5
    
    if action == 'LONG':
        current_position = 'LONG'
        entry_price = price
        sl_real = price - sl_pips
        tp_real = price + (sl_pips * 2.0)
    elif action == 'SHORT':
        current_position = 'SHORT'
        entry_price = price
        sl_real = price + sl_pips
        tp_real = price - (sl_pips * 2.0)
        
    sl_price = sl_real
    tp_price = tp_real
    
    print(f"🚀 SIMULASI OPEN {action} at {price}")
    
    msg = (
        f"📝 <b>SIMULASI PAPER TRADING</b>\n"
        f"Action: <b>{action}</b> {SYMBOL}\n"
        f"Price: {price}\n"
        f"🎯 TP: {tp_real:.2f}\n"
        f"🛑 SL: {sl_real:.2f}\n"
        f"<i>(Ini bukan order asli, hanya simulasi)</i>"
    )
    send_telegram(msg)

def check_exit_simulation(current_price):
    global current_position, entry_price, sl_price, tp_price
    
    if current_position is None: return

    pnl_pct = 0
    exit_reason = ""
    
    # LOGIKA EXIT LONG
    if current_position == 'LONG':
        if current_price >= tp_price:
            exit_reason = "✅ TAKE PROFIT"
            pnl_pct = (tp_price - entry_price) / entry_price * 100 * LEVERAGE
        elif current_price <= sl_price:
            exit_reason = "❌ STOP LOSS"
            pnl_pct = (sl_price - entry_price) / entry_price * 100 * LEVERAGE
            
    # LOGIKA EXIT SHORT
    elif current_position == 'SHORT':
        if current_price <= tp_price:
            exit_reason = "✅ TAKE PROFIT"
            pnl_pct = (entry_price - tp_price) / entry_price * 100 * LEVERAGE
        elif current_price >= sl_price:
            exit_reason = "❌ STOP LOSS"
            pnl_pct = (entry_price - sl_price) / entry_price * 100 * LEVERAGE

    # Jika kena TP atau SL
    if exit_reason:
        print(f"EXIT {current_position}: {exit_reason}")
        msg = (
            f"🏁 <b>POSISI DITUTUP (SIMULASI)</b>\n"
            f"Status: <b>{exit_reason}</b>\n"
            f"Close Price: {current_price}\n"
            f"Estimasi PnL: {pnl_pct:.2f}% (Lev {LEVERAGE}x)"
        )
        send_telegram(msg)
        
        # Reset Posisi
        current_position = None
        entry_price = 0
        sl_price = 0
        tp_price = 0

def run_bot():
    send_telegram(f"🤖 <b>Bot Paper Trading Aktif</b>\nPair: {SYMBOL}\nData: REAL MARKET (Simulasi)")
    print(f"Bot mulai monitoring {SYMBOL} (Real Data)...")

    while True:
        try:
            # Print log biar kelihatan di Coolify (di-force unbuffered)
            print(f"[{datetime.now().strftime('%H:%M')}] Cek Market...", flush=True)
            
            df = get_data()
            if df is None: 
                time.sleep(10)
                continue
                
            last = df.iloc[-1]
            prev = df.iloc[-2]
            current_price = last['close']
            
            # 1. Cek apakah harus Close Posisi (TP/SL)?
            if current_position is not None:
                check_exit_simulation(current_price)
            
            # 2. Cek Entry Baru (Jika tidak ada posisi)
            if current_position is None:
                cross_up = prev['EMA_9'] < prev['EMA_21'] and last['EMA_9'] > last['EMA_21']
                trend_up = last['close'] > last['EMA_200']
                
                cross_down = prev['EMA_9'] > prev['EMA_21'] and last['EMA_9'] < last['EMA_21']
                trend_down = last['close'] < last['EMA_200']
                
                if cross_up and trend_up:
                    execute_simulation('LONG', current_price, last['ATR'])
                elif cross_down and trend_down:
                    execute_simulation('SHORT', current_price, last['ATR'])
            else:
                print(f"   -> Sedang dalam posisi {current_position}. Menunggu exit...", flush=True)
            
            time.sleep(60) # Cek setiap 1 menit
            
        except Exception as e:
            print(f"Loop Error: {e}", flush=True)
            time.sleep(10)

if __name__ == "__main__":
    run_bot()
